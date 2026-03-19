"""Tests for AgentStateService corrupt-database recovery."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import DatabaseError as SADatabaseError

from claw_forge.state.service import AgentStateService


class TestDbPath:
    """Tests for _db_path() helper."""

    def test_extracts_path_from_sqlite_url(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        svc = AgentStateService(f"sqlite+aiosqlite:///{db_path}")
        assert svc._db_path() == db_path


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
            result = MagicMock()
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
