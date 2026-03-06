"""Tests for three-phase (coding→testing→reviewer) task generation in _write_plan_to_db."""
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
async def test_backend_feature_creates_three_tasks(tmp_path: Path) -> None:
    from claw_forge.cli import _write_plan_to_db

    await _write_plan_to_db(tmp_path, "proj", _features(["backend"]))
    tasks = await _load_tasks(tmp_path / ".claw-forge" / "state.db")

    assert len(tasks) == 3
    plugins = {t.plugin_name for t in tasks}
    assert plugins == {"coding", "testing", "reviewer"}


@pytest.mark.asyncio
async def test_docs_feature_creates_one_task(tmp_path: Path) -> None:
    from claw_forge.cli import _write_plan_to_db

    await _write_plan_to_db(tmp_path, "proj", _features(["docs"]))
    tasks = await _load_tasks(tmp_path / ".claw-forge" / "state.db")

    assert len(tasks) == 1
    assert tasks[0].plugin_name == "coding"


@pytest.mark.asyncio
async def test_infra_feature_creates_one_task(tmp_path: Path) -> None:
    from claw_forge.cli import _write_plan_to_db

    await _write_plan_to_db(tmp_path, "proj", _features(["infra"]))
    tasks = await _load_tasks(tmp_path / ".claw-forge" / "state.db")

    assert len(tasks) == 1
    assert tasks[0].plugin_name == "coding"


@pytest.mark.asyncio
async def test_task_names_have_prefix(tmp_path: Path) -> None:
    from claw_forge.cli import _write_plan_to_db

    await _write_plan_to_db(tmp_path, "proj", _features(["frontend"]))
    tasks = await _load_tasks(tmp_path / ".claw-forge" / "state.db")

    by_plugin = {t.plugin_name: t for t in tasks}
    assert "Test:" in by_plugin["testing"].description
    assert "Review:" in by_plugin["reviewer"].description
    # coding task has no prefix
    assert "Test:" not in by_plugin["coding"].description
    assert "Review:" not in by_plugin["coding"].description


@pytest.mark.asyncio
async def test_coding_testing_reviewer_chain(tmp_path: Path) -> None:
    """testing.depends_on == [coding.id], reviewer.depends_on == [testing.id]."""
    from claw_forge.cli import _write_plan_to_db

    await _write_plan_to_db(tmp_path, "proj", _features(["security"]))
    tasks = await _load_tasks(tmp_path / ".claw-forge" / "state.db")

    by_plugin = {t.plugin_name: t for t in tasks}
    coding = by_plugin["coding"]
    testing = by_plugin["testing"]
    reviewer = by_plugin["reviewer"]

    assert testing.depends_on == [coding.id]
    assert reviewer.depends_on == [testing.id]
    assert coding.depends_on == []


@pytest.mark.asyncio
async def test_cross_feature_dep_points_to_terminal_reviewer(tmp_path: Path) -> None:
    """Feature B's coding task must depend on Feature A's reviewer (terminal) task."""
    from claw_forge.cli import _write_plan_to_db

    feats = _features(["backend", "backend"])
    await _write_plan_to_db(tmp_path, "proj", feats)
    tasks = await _load_tasks(tmp_path / ".claw-forge" / "state.db")

    # Identify Feature A: its coding task has no depends_on
    feat_a_coding = next(t for t in tasks if t.plugin_name == "coding" and not t.depends_on)
    feat_a_testing = next(
        t for t in tasks if t.plugin_name == "testing" and feat_a_coding.id in t.depends_on
    )
    feat_a_reviewer = next(
        t for t in tasks if t.plugin_name == "reviewer" and feat_a_testing.id in t.depends_on
    )

    # Feature B's coding task depends on Feature A's reviewer (the terminal)
    feat_b_coding = next(t for t in tasks if t.plugin_name == "coding" and t.depends_on)
    assert feat_a_reviewer.id in feat_b_coding.depends_on


@pytest.mark.asyncio
async def test_cross_feature_dep_docs_points_to_coding_terminal(tmp_path: Path) -> None:
    """Feature B depends on Feature A (docs). B's coding task must depend on A's coding task."""
    from claw_forge.cli import _write_plan_to_db

    feats = [
        {"index": 0, "name": "Write docs", "description": "d", "category": "docs",
         "steps": [], "depends_on_indices": []},
        {"index": 1, "name": "Build API", "description": "d", "category": "backend",
         "steps": [], "depends_on_indices": [0]},
    ]
    await _write_plan_to_db(tmp_path, "proj", feats)
    tasks = await _load_tasks(tmp_path / ".claw-forge" / "state.db")

    # docs feature → 1 task (coding only)
    docs_coding = next(t for t in tasks if t.plugin_name == "coding" and t.depends_on == [])
    # backend feature's coding task depends on docs' coding task (its terminal)
    backend_coding = next(
        t for t in tasks
        if t.plugin_name == "coding" and docs_coding.id in (t.depends_on or [])
    )
    assert backend_coding is not None


@pytest.mark.asyncio
async def test_all_coding_categories_get_three_tasks(tmp_path: Path) -> None:
    """backend, frontend, testing, security categories all produce 3 tasks."""
    from claw_forge.cli import _write_plan_to_db

    for cat in ["backend", "frontend", "testing", "security"]:
        proj = tmp_path / cat
        await _write_plan_to_db(proj, "proj", _features([cat]))
        tasks = await _load_tasks(proj / ".claw-forge" / "state.db")
        plugins = {t.plugin_name for t in tasks}
        assert plugins == {"coding", "testing", "reviewer"}, f"Failed for category={cat}"
