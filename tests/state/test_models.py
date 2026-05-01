"""Tests for state ORM models."""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from claw_forge.state.models import Base, Session, Task


@pytest.mark.asyncio
async def test_task_merged_to_target_branch_defaults_true() -> None:
    """A freshly inserted Task has merged_to_target_branch=True by default."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Maker = async_sessionmaker(engine, expire_on_commit=False)
    async with Maker() as db:
        sess = Session(project_path="/tmp/x")
        db.add(sess)
        await db.flush()
        t = Task(session_id=sess.id, plugin_name="coding", description="X")
        db.add(t)
        await db.commit()
        await db.refresh(t)
        assert t.merged_to_target_branch is True


@pytest.mark.asyncio
async def test_ensure_task_columns_adds_missing_merged_to_target_branch(
    tmp_path: Path,
) -> None:
    """If an existing DB lacks the column (and no legacy one), the helper adds it."""
    import sqlite3

    db_path = tmp_path / "old.db"
    # Build a "legacy" tasks table without merged_to_target_branch (and no merged_to_main).
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE sessions (id TEXT PRIMARY KEY, project_path TEXT,
          status TEXT, project_paused INTEGER, created_at TIMESTAMP,
          updated_at TIMESTAMP, manifest_json TEXT);
        CREATE TABLE tasks (id TEXT PRIMARY KEY, session_id TEXT,
          plugin_name TEXT, description TEXT, status TEXT, priority INTEGER,
          depends_on TEXT, category TEXT, steps TEXT, result_json TEXT,
          error_message TEXT, human_question TEXT, human_answer TEXT,
          input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL,
          active_subagents INTEGER, parent_task_id TEXT,
          bugfix_retry_count INTEGER, created_at TIMESTAMP,
          started_at TIMESTAMP, completed_at TIMESTAMP);
        INSERT INTO tasks (id, session_id, plugin_name, status, priority)
          VALUES ('t1', 's1', 'coding', 'completed', 0);
        """
    )
    con.commit()
    con.close()

    from claw_forge.state.service import _ensure_task_columns

    # Helper runs without error on legacy schema and is a no-op on second run.
    await _ensure_task_columns(f"sqlite+aiosqlite:///{db_path}")
    await _ensure_task_columns(f"sqlite+aiosqlite:///{db_path}")

    con = sqlite3.connect(db_path)
    cols = [row[1] for row in con.execute("PRAGMA table_info(tasks)").fetchall()]
    val = con.execute("SELECT merged_to_target_branch FROM tasks WHERE id='t1'").fetchone()[0]
    con.close()
    assert "merged_to_target_branch" in cols
    # Default is 1 (True) so legacy completed tasks aren't retroactively gated.
    assert val == 1


@pytest.mark.asyncio
async def test_ensure_task_columns_renames_pre_v0_5_31_merged_to_main(tmp_path: Path) -> None:
    """A pre-v0.5.31 DB with the old merged_to_main column is renamed in place."""
    import sqlite3

    db_path = tmp_path / "old.db"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE sessions (id TEXT PRIMARY KEY);
        CREATE TABLE tasks (id TEXT PRIMARY KEY, session_id TEXT,
          plugin_name TEXT,
          merged_to_main INTEGER NOT NULL DEFAULT 1);
        INSERT INTO tasks (id, session_id, plugin_name, merged_to_main)
          VALUES ('t1', 's1', 'coding', 0);
        """
    )
    con.commit()
    con.close()

    from claw_forge.state.service import _ensure_task_columns

    await _ensure_task_columns(f"sqlite+aiosqlite:///{db_path}")
    await _ensure_task_columns(f"sqlite+aiosqlite:///{db_path}")  # idempotent

    con = sqlite3.connect(db_path)
    cols = {row[1] for row in con.execute("PRAGMA table_info(tasks)").fetchall()}
    val = con.execute("SELECT merged_to_target_branch FROM tasks WHERE id='t1'").fetchone()[0]
    con.close()
    # Old column gone, new column present, value preserved (was 0, still 0).
    assert "merged_to_main" not in cols
    assert "merged_to_target_branch" in cols
    assert val == 0


@pytest.mark.asyncio
async def test_file_claim_unique_per_session() -> None:
    """The same (session_id, file_path) cannot be claimed twice."""
    from sqlalchemy.exc import IntegrityError

    from claw_forge.state.models import FileClaim

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Maker = async_sessionmaker(engine, expire_on_commit=False)
    async with Maker() as db:
        sess = Session(project_path="/tmp/x")
        db.add(sess)
        await db.flush()
        t1 = Task(session_id=sess.id, plugin_name="coding")
        t2 = Task(session_id=sess.id, plugin_name="coding")
        db.add_all([t1, t2])
        await db.flush()
        db.add(FileClaim(session_id=sess.id, task_id=t1.id, file_path="x.py"))
        await db.commit()
        db.add(FileClaim(session_id=sess.id, task_id=t2.id, file_path="x.py"))
        with pytest.raises(IntegrityError):
            await db.commit()


@pytest.mark.asyncio
async def test_task_touches_files_defaults_empty_list() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Maker = async_sessionmaker(engine, expire_on_commit=False)
    async with Maker() as db:
        sess = Session(project_path="/tmp/x")
        db.add(sess)
        await db.flush()
        t = Task(session_id=sess.id, plugin_name="coding")
        db.add(t)
        await db.commit()
        await db.refresh(t)
        assert t.touches_files == []
