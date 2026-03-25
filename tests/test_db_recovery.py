"""Tests for AgentStateService corrupt-database recovery."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError as SADatabaseError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from claw_forge.state.models import Base, Session, Task
from claw_forge.state.service import AgentStateService


class TestDbPath:
    """Tests for _db_path() helper."""

    def test_extracts_path_from_sqlite_url(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        svc = AgentStateService(f"sqlite+aiosqlite:///{db_path}")
        assert svc._db_path() == db_path


class TestOrphanAdoption:
    """Tests for _init_db_inner adopting orphaned tasks."""

    @pytest.mark.asyncio
    async def test_adopts_orphaned_tasks_on_startup(self, tmp_path: Path) -> None:
        """Tasks whose session_id doesn't exist are re-parented on startup."""
        db_path = tmp_path / "state.db"
        db_url = f"sqlite+aiosqlite:///{db_path}"
        project_path = tmp_path / "my_project"
        project_path.mkdir()

        # Create the DB with a valid session
        engine = create_async_engine(db_url, echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as db:
            session = Session(project_path=str(project_path))
            db.add(session)
            await db.flush()
            valid_sid = session.id

            # Create a task with a non-existent session_id (orphan)
            orphan = Task(
                session_id="ghost-session-id",
                plugin_name="coding",
                description="Orphaned task",
                status="completed",
            )
            db.add(orphan)
            await db.commit()
            orphan_id = orphan.id
        await engine.dispose()

        # Now start the service — _init_db_inner should adopt the orphan
        svc = AgentStateService(db_url, project_path=project_path)
        try:
            await svc.init_db()

            # Verify the orphan was adopted
            engine2 = create_async_engine(db_url, echo=False)
            async with async_sessionmaker(engine2, expire_on_commit=False)() as db:
                result = await db.execute(
                    text("SELECT session_id FROM tasks WHERE id = :tid"),
                    {"tid": orphan_id},
                )
                row = result.first()
                assert row is not None
                assert row[0] == valid_sid
            await engine2.dispose()
        finally:
            await svc.dispose()

    @pytest.mark.asyncio
    async def test_sanitizes_empty_string_datetimes(self, tmp_path: Path) -> None:
        """Empty string datetime columns from DB recovery are sanitized."""
        db_path = tmp_path / "state.db"
        db_url = f"sqlite+aiosqlite:///{db_path}"
        project_path = tmp_path / "my_project"
        project_path.mkdir()

        # Create DB with a task that has empty-string datetimes
        engine = create_async_engine(db_url, echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Insert directly via SQL to bypass ORM validation
            await conn.execute(text(
                "INSERT INTO sessions (id, project_path, status, project_paused, created_at, updated_at) "
                "VALUES ('s1', :pp, 'pending', 0, '2026-01-01', '2026-01-01')"
            ), {"pp": str(project_path)})
            await conn.execute(text(
                "INSERT INTO tasks (id, session_id, plugin_name, status, priority, "
                "depends_on, steps, created_at, started_at, completed_at, "
                "input_tokens, output_tokens, cost_usd, active_subagents, bugfix_retry_count) "
                "VALUES ('t1', 's1', 'coding', 'completed', 0, '[]', '[]', '', '', '', "
                "0, 0, 0.0, 0, 0)"
            ))
        await engine.dispose()

        # init_db should sanitize the empty strings without crashing
        svc = AgentStateService(db_url, project_path=project_path)
        try:
            await svc.init_db()

            # Verify the task is now readable via ORM
            app = svc.create_app()
            from httpx import ASGITransport, AsyncClient
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/sessions/s1/tasks")
                assert resp.status_code == 200
                tasks = resp.json()
                assert len(tasks) == 1
                assert tasks[0]["id"] == "t1"
        finally:
            await svc.dispose()

    @pytest.mark.asyncio
    async def test_no_adoption_without_orphans(self, tmp_path: Path) -> None:
        """No errors when there are no orphaned tasks."""
        db_path = tmp_path / "state.db"
        db_url = f"sqlite+aiosqlite:///{db_path}"
        project_path = tmp_path / "my_project"
        project_path.mkdir()

        svc = AgentStateService(db_url, project_path=project_path)
        try:
            await svc.init_db()  # Should not raise
        finally:
            await svc.dispose()


class TestInitDbRecovery:
    """Tests for init_db() corrupt-database recovery."""

    @pytest.mark.asyncio
    async def test_healthy_db_no_recovery(self, tmp_path: Path) -> None:
        """init_db works normally when DB is healthy."""
        db_path = tmp_path / "state.db"
        svc = AgentStateService(f"sqlite+aiosqlite:///{db_path}")
        try:
            await svc.init_db()
        finally:
            await svc.dispose()

    @pytest.mark.asyncio
    async def test_level1_wal_only_recovery(self, tmp_path: Path) -> None:
        """Level 1: removing WAL/SHM recovers when main DB is intact."""
        db_path = tmp_path / "state.db"
        svc = AgentStateService(f"sqlite+aiosqlite:///{db_path}")
        call_count = 0
        original_init = svc._init_db_inner

        # Create WAL/SHM files that should be deleted during recovery
        wal_path = Path(f"{db_path}-wal")
        shm_path = Path(f"{db_path}-shm")
        wal_path.write_bytes(b"\x00" * 1024)
        shm_path.write_bytes(b"\x00" * 32768)

        async def _fail_then_succeed() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise SADatabaseError(
                    statement="test",
                    params=None,
                    orig=Exception("database disk image is malformed"),
                )
            return await original_init()

        try:
            with patch.object(
                svc, "_init_db_inner", side_effect=_fail_then_succeed
            ):
                await svc.init_db()
            # Recovery should have been attempted (2 calls: fail + succeed)
            assert call_count == 2
        finally:
            await svc.dispose()

    @pytest.mark.asyncio
    async def test_level2_sqlite3_recover(self, tmp_path: Path) -> None:
        """Level 2: sqlite3 .recover salvages data from corrupt DB."""
        db_path = tmp_path / "state.db"
        db_path.write_bytes(b"\x00" * 4096)

        svc = AgentStateService(f"sqlite+aiosqlite:///{db_path}")
        call_count = 0
        original_init = svc._init_db_inner

        async def _fail_twice_then_succeed() -> None:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise SADatabaseError(
                    statement="test",
                    params=None,
                    orig=Exception("database disk image is malformed"),
                )
            return await original_init()

        recover_sql = (
            "BEGIN;\n"
            "CREATE TABLE t (id INTEGER PRIMARY KEY);\n"
            "COMMIT;\n"
        )

        _real_run = subprocess.run

        def mock_subprocess_run(cmd, **kwargs):  # noqa: ANN001, ANN003
            result = Mock()
            if ".recover" in cmd:
                result.returncode = 0
                result.stdout = recover_sql
            else:
                # Use the real subprocess.run to import the recovered SQL
                result = _real_run(cmd, **kwargs)  # noqa: S603
            return result

        try:
            with (
                patch.object(
                    svc, "_init_db_inner", side_effect=_fail_twice_then_succeed
                ),
                patch("subprocess.run", side_effect=mock_subprocess_run),
            ):
                await svc.init_db()

            assert db_path.with_suffix(".db.corrupt").exists()
            assert call_count == 3
        finally:
            await svc.dispose()

    @pytest.mark.asyncio
    async def test_level3_raises_when_recovery_fails(
        self, tmp_path: Path
    ) -> None:
        """Level 3: raises with actionable message when all recovery fails."""
        db_path = tmp_path / "state.db"
        db_path.write_bytes(b"\x00" * 4096)

        svc = AgentStateService(f"sqlite+aiosqlite:///{db_path}")

        async def _always_fail() -> None:
            raise SADatabaseError(
                statement="test",
                params=None,
                orig=Exception("database disk image is malformed"),
            )

        try:
            with (
                patch.object(svc, "_init_db_inner", side_effect=_always_fail),
                patch(
                    "subprocess.run",
                    side_effect=OSError("sqlite3 not found"),
                ),pytest.raises(SADatabaseError, match="recovery failed")
            ):
                await svc.init_db()
        finally:
            await svc.dispose()

    @pytest.mark.asyncio
    async def test_non_corruption_error_propagates(
        self, tmp_path: Path
    ) -> None:
        """Non-corruption DatabaseErrors are not caught by recovery."""
        db_path = tmp_path / "state.db"
        svc = AgentStateService(f"sqlite+aiosqlite:///{db_path}")

        async def _raise_other() -> None:
            raise SADatabaseError(
                statement="test",
                params=None,
                orig=Exception("no such table: foobar"),
            )

        try:
            with (
                patch.object(svc, "_init_db_inner", side_effect=_raise_other),
                pytest.raises(SADatabaseError, match="foobar"),
            ):
                await svc.init_db()
        finally:
            await svc.dispose()

    @pytest.mark.asyncio
    async def test_recover_timeout_falls_through(
        self, tmp_path: Path
    ) -> None:
        """sqlite3 .recover timeout falls through to level 3."""
        db_path = tmp_path / "state.db"
        db_path.write_bytes(b"\x00" * 4096)

        svc = AgentStateService(f"sqlite+aiosqlite:///{db_path}")

        async def _always_fail() -> None:
            raise SADatabaseError(
                statement="test",
                params=None,
                orig=Exception("database disk image is malformed"),
            )

        try:
            with (
                patch.object(svc, "_init_db_inner", side_effect=_always_fail),
                patch(
                    "subprocess.run",
                    side_effect=subprocess.TimeoutExpired("sqlite3", 30),
                ),pytest.raises(SADatabaseError, match="recovery failed")
            ):
                await svc.init_db()
        finally:
            await svc.dispose()
