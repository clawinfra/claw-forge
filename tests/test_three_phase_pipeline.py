"""Tests for single-task-per-feature generation in _write_plan_to_db.

Each feature produces exactly one coding task. The coding agent handles
TDD inline (write failing tests → implement → verify green).
Cross-feature dependency edges connect directly between coding task UUIDs.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from claw_forge.state.models import Task


async def _load_tasks(db_path: Path) -> list[Task]:
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        result = await db.execute(select(Task))
        tasks = result.scalars().all()
    await engine.dispose()
    return list(tasks)


def _features(cats: list[str]) -> list[dict]:
    return [
        {
            "index": i,
            "name": f"Feature {i}",
            "description": f"Desc {i}",
            "category": cat,
            "steps": [],
            "depends_on_indices": [i - 1] if i > 0 else [],
        }
        for i, cat in enumerate(cats)
    ]


@pytest.mark.asyncio
async def test_each_feature_creates_one_task(tmp_path: Path) -> None:
    from claw_forge.cli import _write_plan_to_db

    for cat in ["backend", "frontend", "testing", "security", "docs", "infra"]:
        proj = tmp_path / cat
        await _write_plan_to_db(proj, "proj", _features([cat]))
        tasks = await _load_tasks(proj / ".claw-forge" / "state.db")
        assert len(tasks) == 1, f"Expected 1 task for category={cat}, got {len(tasks)}"
        assert tasks[0].plugin_name == "coding"


@pytest.mark.asyncio
async def test_multiple_independent_features(tmp_path: Path) -> None:
    from claw_forge.cli import _write_plan_to_db

    # 3 features with no cross-deps — all schedulable in parallel (wave 0)
    feats = [
        {"index": i, "name": f"F{i}", "description": "d", "category": "backend",
         "steps": [], "depends_on_indices": []}
        for i in range(3)
    ]
    await _write_plan_to_db(tmp_path, "proj", feats)
    tasks = await _load_tasks(tmp_path / ".claw-forge" / "state.db")

    assert len(tasks) == 3
    assert all(t.plugin_name == "coding" for t in tasks)
    assert all(t.depends_on == [] for t in tasks)


@pytest.mark.asyncio
async def test_cross_feature_dep_wiring(tmp_path: Path) -> None:
    """Feature B's task must depend on Feature A's task UUID."""
    from claw_forge.cli import _write_plan_to_db

    feats = _features(["backend", "backend"])
    await _write_plan_to_db(tmp_path, "proj", feats)
    tasks = await _load_tasks(tmp_path / ".claw-forge" / "state.db")

    feat_a = next(t for t in tasks if t.depends_on == [])
    feat_b = next(t for t in tasks if t.depends_on != [])
    assert feat_a.id in feat_b.depends_on


@pytest.mark.asyncio
async def test_sequential_chain_deps(tmp_path: Path) -> None:
    """A→B→C chain: B depends on A, C depends on B."""
    from claw_forge.cli import _write_plan_to_db

    feats = _features(["backend", "backend", "backend"])
    await _write_plan_to_db(tmp_path, "proj", feats)
    tasks = await _load_tasks(tmp_path / ".claw-forge" / "state.db")

    task_a = next(t for t in tasks if t.depends_on == [])
    task_b = next(t for t in tasks if t.depends_on == [task_a.id])
    task_c = next(t for t in tasks if t.depends_on == [task_b.id])
    assert task_c is not None


@pytest.mark.asyncio
async def test_empty_features(tmp_path: Path) -> None:
    from claw_forge.cli import _write_plan_to_db

    await _write_plan_to_db(tmp_path, "proj", [])
    tasks = await _load_tasks(tmp_path / ".claw-forge" / "state.db")
    assert tasks == []


@pytest.mark.asyncio
async def test_task_description_includes_name_and_desc(tmp_path: Path) -> None:
    from claw_forge.cli import _write_plan_to_db

    feats = [{"index": 0, "name": "Auth Module", "description": "JWT login",
              "category": "backend", "steps": ["step1"], "depends_on_indices": []}]
    await _write_plan_to_db(tmp_path, "proj", feats)
    tasks = await _load_tasks(tmp_path / ".claw-forge" / "state.db")

    assert len(tasks) == 1
    assert "Auth Module" in tasks[0].description
    assert "JWT login" in tasks[0].description
    assert tasks[0].steps == ["step1"]


@pytest.mark.asyncio
async def test_cross_feature_dep_any_category(tmp_path: Path) -> None:
    """Dep wiring works regardless of category (docs, infra, backend, etc.)."""
    from claw_forge.cli import _write_plan_to_db

    feats = [
        {"index": 0, "name": "Write docs", "description": "d", "category": "docs",
         "steps": [], "depends_on_indices": []},
        {"index": 1, "name": "Build API", "description": "d", "category": "backend",
         "steps": [], "depends_on_indices": [0]},
    ]
    await _write_plan_to_db(tmp_path, "proj", feats)
    tasks = await _load_tasks(tmp_path / ".claw-forge" / "state.db")

    assert len(tasks) == 2
    docs_task = next(t for t in tasks if t.depends_on == [])
    api_task = next(t for t in tasks if t.depends_on != [])
    assert docs_task.id in api_task.depends_on
