"""Tests for plan reconciliation (_write_plan_to_db)."""

from __future__ import annotations

from pathlib import Path

import pytest

from claw_forge.cli import _write_plan_to_db


def _make_features(names: list[str], deps: dict[int, list[int]] | None = None) -> list[dict]:
    """Build a feature list matching the format InitializerPlugin produces."""
    return [
        {
            "index": i,
            "name": name,
            "description": f"Full description of {name}",
            "category": "General",
            "steps": [],
            "depends_on_indices": (deps or {}).get(i, []),
        }
        for i, name in enumerate(names)
    ]


@pytest.mark.asyncio
class TestPlanReconcile:
    async def test_fresh_creates_all_tasks(self, tmp_path: Path) -> None:
        features = _make_features(["A", "B", "C"])
        summary = await _write_plan_to_db(tmp_path, "proj", features, fresh=True)
        assert summary["new"] == 3
        assert summary["existing_completed"] == 0

    async def test_reconcile_skips_existing(self, tmp_path: Path) -> None:
        features = _make_features(["A", "B", "C"])
        # First plan — creates all 3
        s1 = await _write_plan_to_db(tmp_path, "proj", features)
        assert s1["new"] == 3

        # Second plan with same features — creates 0 new
        s2 = await _write_plan_to_db(tmp_path, "proj", features)
        assert s2["new"] == 0
        assert s2["existing_pending"] == 3

    async def test_reconcile_adds_only_missing(self, tmp_path: Path) -> None:
        features_v1 = _make_features(["A", "B", "C"])
        await _write_plan_to_db(tmp_path, "proj", features_v1)

        # V2 adds two new features
        features_v2 = _make_features(["A", "B", "C", "D", "E"])
        s2 = await _write_plan_to_db(tmp_path, "proj", features_v2)
        assert s2["new"] == 2
        assert s2["existing_pending"] == 3

    async def test_reconcile_preserves_completed(self, tmp_path: Path) -> None:
        """Completed tasks are preserved and counted correctly."""
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from claw_forge.state.models import Task

        features = _make_features(["A", "B", "C"])
        await _write_plan_to_db(tmp_path, "proj", features)

        # Mark task A as completed directly in DB
        db_url = f"sqlite+aiosqlite:///{tmp_path / '.claw-forge' / 'state.db'}"
        engine = create_async_engine(db_url)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            result = await db.execute(select(Task))
            tasks = {t.description: t for t in result.scalars()}
            tasks["A: Full description of A"].status = "completed"
            await db.commit()
        await engine.dispose()

        # Re-plan with an extra feature
        features_v2 = _make_features(["A", "B", "C", "D"])
        s2 = await _write_plan_to_db(tmp_path, "proj", features_v2)
        assert s2["existing_completed"] == 1
        assert s2["existing_pending"] == 2
        assert s2["new"] == 1

    async def test_fresh_ignores_existing_session(self, tmp_path: Path) -> None:
        """--fresh creates a new session even when one exists."""
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from claw_forge.state.models import Task
        from claw_forge.state.models import Session as DbSession

        features = _make_features(["A", "B"])
        await _write_plan_to_db(tmp_path, "proj", features)

        # Fresh plan creates a new session with all tasks
        s2 = await _write_plan_to_db(tmp_path, "proj", features, fresh=True)
        assert s2["new"] == 2
        assert s2["existing_completed"] == 0

        # Verify two sessions exist
        db_url = f"sqlite+aiosqlite:///{tmp_path / '.claw-forge' / 'state.db'}"
        engine = create_async_engine(db_url)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            sessions = (await db.execute(select(DbSession))).scalars().all()
            assert len(sessions) == 2
            tasks = (await db.execute(select(Task))).scalars().all()
            assert len(tasks) == 4  # 2 from each session
        await engine.dispose()

    async def test_reconcile_counts_other_statuses(self, tmp_path: Path) -> None:
        """Tasks with non-standard statuses are counted as 'other'."""
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from claw_forge.state.models import Task

        features = _make_features(["A", "B"])
        await _write_plan_to_db(tmp_path, "proj", features)

        # Mark task A as "blocked" (non-standard status)
        db_url = f"sqlite+aiosqlite:///{tmp_path / '.claw-forge' / 'state.db'}"
        engine = create_async_engine(db_url)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            result = await db.execute(select(Task))
            for t in result.scalars():
                if "A:" in (t.description or ""):
                    t.status = "blocked"
            await db.commit()
        await engine.dispose()

        features_v2 = _make_features(["A", "B", "C"])
        s2 = await _write_plan_to_db(tmp_path, "proj", features_v2)
        assert s2["existing_other"] == 1
        assert s2["existing_pending"] == 1
        assert s2["new"] == 1

    async def test_reconcile_ignores_tasks_with_no_description(self, tmp_path: Path) -> None:
        """Tasks with NULL description are skipped during matching."""
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from claw_forge.state.models import Base, Task
        from claw_forge.state.models import Session as DbSession

        db_url = f"sqlite+aiosqlite:///{tmp_path / '.claw-forge' / 'state.db'}"
        (tmp_path / ".claw-forge").mkdir(parents=True, exist_ok=True)
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            sess = DbSession(project_path=str(tmp_path), status="pending")
            db.add(sess)
            await db.flush()
            # Task with no description — should be ignored by reconciliation
            db.add(Task(
                session_id=sess.id, plugin_name="coding",
                description=None, status="pending",
            ))
            await db.commit()
        await engine.dispose()

        features = _make_features(["A"])
        summary = await _write_plan_to_db(tmp_path, "proj", features)
        # The null-description task isn't matched, so A is new
        assert summary["new"] == 1
        # Null-description tasks are excluded from matching (not in summary)
        assert summary["existing_pending"] == 0

    async def test_new_task_depends_on_existing(self, tmp_path: Path) -> None:
        """New tasks can depend on existing completed tasks."""
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from claw_forge.state.models import Task

        # V1: features A, B
        features_v1 = _make_features(["A", "B"])
        await _write_plan_to_db(tmp_path, "proj", features_v1)

        # Get task A's UUID
        db_url = f"sqlite+aiosqlite:///{tmp_path / '.claw-forge' / 'state.db'}"
        engine = create_async_engine(db_url)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            result = await db.execute(select(Task))
            tasks = {t.description: t for t in result.scalars()}
            a_id = tasks["A: Full description of A"].id
        await engine.dispose()

        # V2: adds C which depends on A (index 0)
        features_v2 = _make_features(["A", "B", "C"], deps={2: [0]})
        await _write_plan_to_db(tmp_path, "proj", features_v2)

        # Verify C's depends_on contains A's existing UUID
        engine2 = create_async_engine(db_url)
        async with async_sessionmaker(engine2, expire_on_commit=False)() as db:
            result = await db.execute(select(Task))
            tasks = {t.description: t for t in result.scalars()}
            c_task = tasks["C: Full description of C"]
            assert a_id in c_task.depends_on
        await engine2.dispose()
