"""Tests for state ORM models."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from claw_forge.state.models import Base, Session, Task


@pytest.mark.asyncio
async def test_task_merged_to_main_defaults_true() -> None:
    """A freshly inserted Task has merged_to_main=True by default."""
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
        assert t.merged_to_main is True
