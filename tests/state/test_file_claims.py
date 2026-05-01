"""Tests for the file-claim helpers."""
from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from claw_forge.state.file_claims import (
    claims_for_session,
    release_for_task,
    try_claim,
)
from claw_forge.state.models import Base, Session, Task


@pytest.fixture()
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Maker = async_sessionmaker(engine, expire_on_commit=False)
    async with Maker() as session:
        yield session
    await engine.dispose()


@pytest.fixture()
async def session_with_two_tasks(
    db: AsyncSession,
) -> tuple[str, str, str]:
    sess = Session(project_path="/tmp/x")
    db.add(sess)
    await db.flush()
    t1 = Task(session_id=sess.id, plugin_name="coding")
    t2 = Task(session_id=sess.id, plugin_name="coding")
    db.add_all([t1, t2])
    await db.commit()
    return sess.id, t1.id, t2.id


@pytest.mark.asyncio
async def test_try_claim_succeeds_when_no_conflict(
    db: AsyncSession, session_with_two_tasks: tuple[str, str, str]
) -> None:
    sess_id, t1, _ = session_with_two_tasks
    result = await try_claim(db, sess_id, t1, ["a.py", "b.py"])
    assert result["claimed"] is True
    assert result["conflicts"] == []
    rows = await claims_for_session(db, sess_id)
    assert sorted(r.file_path for r in rows) == ["a.py", "b.py"]


@pytest.mark.asyncio
async def test_try_claim_fails_atomically_on_conflict(
    db: AsyncSession, session_with_two_tasks: tuple[str, str, str]
) -> None:
    sess_id, t1, t2 = session_with_two_tasks
    await try_claim(db, sess_id, t1, ["a.py"])
    # t2 wants a.py (conflict) and b.py (free) — must fail with ZERO partial claims.
    result = await try_claim(db, sess_id, t2, ["a.py", "b.py"])
    assert result["claimed"] is False
    assert "a.py" in result["conflicts"]
    rows = await claims_for_session(db, sess_id)
    # Only t1's a.py exists — b.py was rolled back.
    assert sorted((r.task_id, r.file_path) for r in rows) == [(t1, "a.py")]


@pytest.mark.asyncio
async def test_release_for_task_drops_all_claims(
    db: AsyncSession, session_with_two_tasks: tuple[str, str, str]
) -> None:
    sess_id, t1, _ = session_with_two_tasks
    await try_claim(db, sess_id, t1, ["a.py", "b.py", "c.py"])
    n = await release_for_task(db, t1)
    assert n == 3
    rows = await claims_for_session(db, sess_id)
    assert rows == []


@pytest.mark.asyncio
async def test_release_for_task_idempotent(
    db: AsyncSession, session_with_two_tasks: tuple[str, str, str]
) -> None:
    sess_id, t1, _ = session_with_two_tasks
    await try_claim(db, sess_id, t1, ["a.py"])
    assert await release_for_task(db, t1) == 1
    assert await release_for_task(db, t1) == 0  # second call is a no-op


@pytest.mark.asyncio
async def test_try_claim_idempotent_for_same_task(
    db: AsyncSession, session_with_two_tasks: tuple[str, str, str]
) -> None:
    """A task re-claiming files it already holds is a no-op success."""
    sess_id, t1, _ = session_with_two_tasks
    await try_claim(db, sess_id, t1, ["a.py"])
    result = await try_claim(db, sess_id, t1, ["a.py", "b.py"])
    assert result["claimed"] is True
    assert result["conflicts"] == []
    rows = await claims_for_session(db, sess_id)
    assert sorted(r.file_path for r in rows) == ["a.py", "b.py"]
