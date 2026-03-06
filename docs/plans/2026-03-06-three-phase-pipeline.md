# Three-Phase Per-Feature Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Generate `coding → testing → reviewer` chained tasks per feature so each phase is a distinct Kanban card, using existing `depends_on` machinery for failure/block propagation.

**Architecture:** Modify `_write_plan_to_db` in `cli.py` to emit up to three `Task` rows per feature instead of one. `index_to_uuid` maps each feature index to its terminal task ID (reviewer for coding-heavy categories, coding for docs/infra) so cross-feature dependency edges attach correctly. No changes needed to the scheduler, dispatcher, or UI.

**Tech Stack:** Python / SQLAlchemy async / pytest-asyncio / existing `Task` model

---

### Task 1: Write failing tests for three-phase task generation

**Files:**
- Create: `tests/test_three_phase_pipeline.py`

**Step 1: Write failing tests**

```python
"""Tests for three-phase (coding→testing→reviewer) task generation in _write_plan_to_db."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from claw_forge.state.models import Base, Task


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

    # Feature 0 = backend, Feature 1 = backend depends_on [0]
    feats = _features(["backend", "backend"])
    await _write_plan_to_db(tmp_path, "proj", feats)
    tasks = await _load_tasks(tmp_path / ".claw-forge" / "state.db")

    # Feature A tasks (no upstream deps)
    feat_a_coding = next(
        t for t in tasks
        if t.plugin_name == "coding" and t.depends_on == []
    )
    feat_a_reviewer = next(
        t for t in tasks
        if t.plugin_name == "reviewer" and feat_a_coding.id in (t.depends_on or []) is False
        and any(
            next((x for x in tasks if x.id == dep and x.plugin_name == "testing"), None)
            for dep in (t.depends_on or [])
        )
    )
    # Feature B's coding task must depend on Feature A's reviewer
    feat_b_coding = next(
        t for t in tasks
        if t.plugin_name == "coding" and t.depends_on != []
    )
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
```

**Step 2: Run to verify all fail**

```bash
uv run pytest tests/test_three_phase_pipeline.py -v
```

Expected: all tests FAIL with `AssertionError` (len(tasks) == 1, not 3)

---

### Task 2: Implement three-phase task generation in `_write_plan_to_db`

**Files:**
- Modify: `claw_forge/cli.py:1143-1171`

**Step 1: Replace the single-task loop**

In `_write_plan_to_db`, replace lines 1143–1171 with:

```python
        # Categories that only need a coding task (no testable artifact produced)
        _NON_CODING_CATEGORIES = {"docs", "infra"}

        # Map feature index → terminal task UUID for cross-feature dep wiring.
        # Terminal = reviewer task (if three phases) or coding task (if one phase).
        index_to_uuid: dict[int, str] = {}
        task_objs: list[Task] = []

        # Pass 1: allocate UUIDs and build task objects (depends_on filled in pass 2)
        # Store per-feature task IDs for chaining
        feature_task_ids: list[dict[str, str]] = []  # [{coding, testing, reviewer}]

        for feat in features:
            cat = (feat.get("category") or "").lower()
            is_coding_only = cat in _NON_CODING_CATEGORIES

            coding_tid   = str(uuid.uuid4())
            testing_tid  = str(uuid.uuid4()) if not is_coding_only else None
            reviewer_tid = str(uuid.uuid4()) if not is_coding_only else None
            terminal_tid = reviewer_tid if reviewer_tid else coding_tid

            index_to_uuid[feat["index"]] = terminal_tid
            feature_task_ids.append({
                "coding":   coding_tid,
                "testing":  testing_tid,
                "reviewer": reviewer_tid,
            })

            base_desc = f"{feat['name']}: {feat['description']}"
            priority  = feat.get("index", 0)

            task_objs.append(Task(
                id=coding_tid,
                session_id=session_id,
                plugin_name="coding",
                description=base_desc,
                category=feat.get("category"),
                steps=feat.get("steps", []),
                status="pending",
                priority=priority,
                depends_on=[],
            ))

            if testing_tid:
                task_objs.append(Task(
                    id=testing_tid,
                    session_id=session_id,
                    plugin_name="testing",
                    description=f"Test: {base_desc}",
                    category=feat.get("category"),
                    steps=[],
                    status="pending",
                    priority=priority,
                    depends_on=[],
                ))

            if reviewer_tid:
                task_objs.append(Task(
                    id=reviewer_tid,
                    session_id=session_id,
                    plugin_name="reviewer",
                    description=f"Review: {base_desc}",
                    category=feat.get("category"),
                    steps=[],
                    status="pending",
                    priority=priority,
                    depends_on=[],
                ))

        # Pass 2: wire depends_on
        for feat, tids in zip(features, feature_task_ids, strict=True):
            # Cross-feature deps: resolve upstream feature's terminal task UUID
            cross_deps = [
                index_to_uuid[i]
                for i in feat.get("depends_on_indices", [])
                if i in index_to_uuid
            ]

            # coding task gets cross-feature deps
            coding_task = next(t for t in task_objs if t.id == tids["coding"])
            coding_task.depends_on = cross_deps
            db.add(coding_task)

            # testing depends on coding
            if tids["testing"]:
                testing_task = next(t for t in task_objs if t.id == tids["testing"])
                testing_task.depends_on = [tids["coding"]]
                db.add(testing_task)

            # reviewer depends on testing
            if tids["reviewer"]:
                reviewer_task = next(t for t in task_objs if t.id == tids["reviewer"])
                reviewer_task.depends_on = [tids["testing"]]
                db.add(reviewer_task)

        await db.commit()
```

**Step 2: Run the new tests**

```bash
uv run pytest tests/test_three_phase_pipeline.py -v
```

Expected: all tests PASS

**Step 3: Run full suite to catch regressions**

```bash
uv run pytest tests/ -q --tb=short
```

Expected: 1337+ passed, 0 failed

**Step 4: Commit**

```bash
git add claw_forge/cli.py tests/test_three_phase_pipeline.py
git commit -m "feat: generate coding→testing→reviewer task chain per feature in _write_plan_to_db"
```

---

### Task 3: Fix the cross-feature reviewer dependency test helper

**Context:** The `test_cross_feature_dep_points_to_terminal_reviewer` test uses a fragile
lookup. Simplify it now that the implementation is in place.

**Files:**
- Modify: `tests/test_three_phase_pipeline.py`

**Step 1: Replace the fragile reviewer lookup**

Replace `test_cross_feature_dep_points_to_terminal_reviewer` with:

```python
@pytest.mark.asyncio
async def test_cross_feature_dep_points_to_terminal_reviewer(tmp_path: Path) -> None:
    """Feature B's coding task must depend on Feature A's reviewer (terminal) task."""
    from claw_forge.cli import _write_plan_to_db

    feats = _features(["backend", "backend"])
    await _write_plan_to_db(tmp_path, "proj", feats)
    tasks = await _load_tasks(tmp_path / ".claw-forge" / "state.db")

    # Identify Feature A: its coding task has no depends_on
    feat_a_coding   = next(t for t in tasks if t.plugin_name == "coding"   and not t.depends_on)
    feat_a_testing  = next(t for t in tasks if t.plugin_name == "testing"  and feat_a_coding.id in t.depends_on)
    feat_a_reviewer = next(t for t in tasks if t.plugin_name == "reviewer" and feat_a_testing.id in t.depends_on)

    # Feature B's coding task depends on Feature A's reviewer (the terminal)
    feat_b_coding = next(t for t in tasks if t.plugin_name == "coding" and t.depends_on)
    assert feat_a_reviewer.id in feat_b_coding.depends_on
```

**Step 2: Run tests**

```bash
uv run pytest tests/test_three_phase_pipeline.py -v
```

Expected: all PASS

**Step 3: Commit**

```bash
git add tests/test_three_phase_pipeline.py
git commit -m "test: simplify cross-feature reviewer dep assertion"
```

---

### Task 4: Coverage gate — verify new tests count toward the 90% requirement

**Step 1: Run with coverage**

```bash
uv run pytest tests/ -q --cov=claw_forge --cov-report=term-missing 2>&1 | tail -20
```

Expected: coverage stays at or above 90%. The new code paths in `cli.py:_write_plan_to_db`
are covered by `tests/test_three_phase_pipeline.py`.

**Step 2: Lint and type-check**

```bash
uv run ruff check claw_forge/ tests/
uv run mypy claw_forge/ --ignore-missing-imports
```

Expected: no errors

**Step 3: Final commit if any lint fixes were needed**

```bash
git add -p
git commit -m "chore: fix lint in three-phase pipeline"
```
