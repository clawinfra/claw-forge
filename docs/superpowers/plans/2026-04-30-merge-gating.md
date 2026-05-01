# Merge-Gating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent downstream tasks from running on stale `main` when their parent's squash-merge fails. Today, a task is marked `completed` *before* the merge attempt; if the merge fails, dependent tasks unblock anyway and run on a `main` that lacks the parent's code. After this change, a dependent is unblocked only when its parent is `completed AND merged_to_main`.

**Architecture:** Add a `merged_to_main` Boolean column to the `Task` model (default `True` for backward compat). The dispatcher flips it to `False` when a task starts on a feature branch and back to `True` after `squash_merge` returns `merged=True`. The scheduler treats a dep as satisfied only when both `status=="completed"` and `merged_to_main is True`. Tasks without git enabled (or `merge_strategy: manual`) keep the default `True` and are never gated. A small startup column-presence check uses `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` so existing SQLite DBs upgrade in place.

**Tech Stack:** Python 3.12, SQLAlchemy 2 (async), Pydantic, FastAPI, Typer, pytest, ruff, mypy.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `claw_forge/state/models.py` | Modify | Add `merged_to_main: Mapped[bool]` column on `Task` |
| `claw_forge/state/service.py` | Modify | Add `merged_to_main` to `UpdateTaskRequest`; PATCH handler honors it; emit field in WS payload; startup column-presence helper |
| `claw_forge/state/scheduler.py` | Modify | `TaskNode.merged_to_main` field; `get_ready_tasks` and `get_execution_order` gate on it |
| `claw_forge/cli.py` | Modify | Dispatcher PATCHes `merged_to_main=False` at task start (when git+auto); on successful auto-merge PATCHes back to `True`; loads `merged_to_main` into TaskNode |
| `tests/state/test_models.py` | Modify or create | Test the column default + ALTER migration |
| `tests/state/test_service_merge_gating.py` | Create | PATCH endpoint accepts and persists `merged_to_main`; WS payload includes it |
| `tests/state/test_scheduler.py` | Modify | New tests: gate prevents dep satisfaction; default-True path still works |
| `tests/test_cli_merge_gating.py` | Create | End-to-end: failed merge keeps child blocked; successful merge unblocks |

---

## Task 1: Add `merged_to_main` column to Task model

**Files:**
- Modify: `claw_forge/state/models.py`
- Test: `tests/state/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/state/test_models.py` (create the file with imports if missing):

```python
"""Tests for state ORM models."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from claw_forge.state.models import Base, Session, Task


@pytest.mark.asyncio
async def test_task_merged_to_main_defaults_true() -> None:
    """A freshly inserted Task has merged_to_main=True by default."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Maker() as db:
        sess = Session(project_path="/tmp/x")
        db.add(sess)
        await db.flush()
        t = Task(session_id=sess.id, plugin_name="coding", description="X")
        db.add(t)
        await db.commit()
        await db.refresh(t)
        assert t.merged_to_main is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/state/test_models.py::test_task_merged_to_main_defaults_true -v
```

Expected: FAIL with `AttributeError: 'Task' object has no attribute 'merged_to_main'`.

- [ ] **Step 3: Add the column**

In `claw_forge/state/models.py`, add to the `Task` class (place after `bugfix_retry_count`):

```python
    merged_to_main: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/state/test_models.py::test_task_merged_to_main_defaults_true -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/state/models.py tests/state/test_models.py
git commit -m "feat(state): add merged_to_main column to Task model"
```

---

## Task 2: Startup column-presence check (in-place upgrade for existing DBs)

**Files:**
- Modify: `claw_forge/state/service.py` (around the engine/lifespan setup)
- Test: `tests/state/test_models.py`

This task ensures existing SQLite DBs without the new column get it added on startup, since the project does not use SQL migrations. SQLite ≥ 3.35 supports `ALTER TABLE … ADD COLUMN`; we only run it if the column is absent.

- [ ] **Step 1: Write the failing test**

Append to `tests/state/test_models.py`:

```python
@pytest.mark.asyncio
async def test_ensure_task_columns_adds_missing_merged_to_main(tmp_path) -> None:
    """If an existing DB lacks merged_to_main, the helper adds it."""
    import sqlite3

    db_path = tmp_path / "old.db"
    # Build a "legacy" tasks table without merged_to_main.
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
    val = con.execute("SELECT merged_to_main FROM tasks WHERE id='t1'").fetchone()[0]
    con.close()
    assert "merged_to_main" in cols
    # Default is 1 (True) so legacy completed tasks aren't retroactively gated.
    assert val == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/state/test_models.py::test_ensure_task_columns_adds_missing_merged_to_main -v
```

Expected: FAIL with `ImportError: cannot import name '_ensure_task_columns'`.

- [ ] **Step 3: Implement `_ensure_task_columns`**

In `claw_forge/state/service.py`, add at module top level (above the `StateService` class — find the class with `grep -n 'class StateService' claw_forge/state/service.py`):

```python
async def _ensure_task_columns(database_url: str) -> None:
    """Add columns to ``tasks`` that may be missing on legacy SQLite DBs.

    The project does not use SQL migrations (CLAUDE.md, "No DB migrations").
    Instead, on every startup we introspect the live ``tasks`` table and
    issue ``ALTER TABLE … ADD COLUMN`` for any new columns the model expects
    but the DB lacks.  Idempotent — second call is a no-op.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            rows = await conn.execute(text("PRAGMA table_info(tasks)"))
            existing = {r[1] for r in rows.fetchall()}
            if "merged_to_main" not in existing:
                await conn.execute(
                    text(
                        "ALTER TABLE tasks ADD COLUMN merged_to_main "
                        "INTEGER NOT NULL DEFAULT 1"
                    )
                )
    finally:
        await engine.dispose()
```

- [ ] **Step 4: Wire into the service startup**

Find the lifespan/init code that calls `Base.metadata.create_all` (use `grep -n 'create_all' claw_forge/state/service.py`).  Immediately after that call, add:

```python
            await _ensure_task_columns(self._database_url)
```

(Use the actual attribute that holds the database URL — `grep -n '_database_url\|database_url' claw_forge/state/service.py` to locate.  If the URL is stored under a different name, adapt accordingly.)

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/state/test_models.py::test_ensure_task_columns_adds_missing_merged_to_main -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add claw_forge/state/service.py tests/state/test_models.py
git commit -m "feat(state): add merged_to_main column to legacy DBs on startup"
```

---

## Task 3: PATCH endpoint accepts `merged_to_main`

**Files:**
- Modify: `claw_forge/state/service.py` (`UpdateTaskRequest` + `update_task` handler + WS broadcast)
- Test: `tests/state/test_service_merge_gating.py`

- [ ] **Step 1: Write the failing test**

Create `tests/state/test_service_merge_gating.py`:

```python
"""Tests for the merged_to_main field on the PATCH /tasks/{id} endpoint."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from claw_forge.state.service import StateService


@pytest.mark.asyncio
async def test_patch_task_persists_merged_to_main(tmp_path) -> None:
    """PATCH /tasks/{id} with merged_to_main=False persists the field."""
    db_path = tmp_path / "state.db"
    svc = StateService(database_url=f"sqlite+aiosqlite:///{db_path}",
                       project_path=str(tmp_path))
    await svc.startup()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=svc.app), base_url="http://test"
        ) as cl:
            # Create a session + task
            r = await cl.post("/sessions", json={"project_path": str(tmp_path)})
            session_id = r.json()["id"]
            r = await cl.post(
                f"/sessions/{session_id}/tasks",
                json={"plugin_name": "coding", "description": "X"},
            )
            task_id = r.json()["id"]
            # Default should be True
            r = await cl.get(f"/tasks/{task_id}")
            assert r.json()["merged_to_main"] is True
            # PATCH to False
            r = await cl.patch(
                f"/tasks/{task_id}", json={"merged_to_main": False}
            )
            assert r.status_code == 200
            r = await cl.get(f"/tasks/{task_id}")
            assert r.json()["merged_to_main"] is False
            # PATCH back to True
            r = await cl.patch(
                f"/tasks/{task_id}", json={"merged_to_main": True}
            )
            r = await cl.get(f"/tasks/{task_id}")
            assert r.json()["merged_to_main"] is True
    finally:
        await svc.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/state/test_service_merge_gating.py -v
```

Expected: FAIL — the field is unknown to `UpdateTaskRequest` and the GET response.

- [ ] **Step 3: Add field to `UpdateTaskRequest`**

In `claw_forge/state/service.py`, locate `class UpdateTaskRequest(BaseModel):` (~line 201) and add:

```python
class UpdateTaskRequest(BaseModel):
    status: str | None = None
    result: dict[str, Any] | None = None
    error_message: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    active_subagents: int | None = None
    merged_to_main: bool | None = None  # NEW
```

- [ ] **Step 4: Persist the field in the PATCH handler**

In the same file, locate `async def update_task` (~line 783).  After the existing `if req.active_subagents is not None: ...` line and before `await db.commit()`, add:

```python
                if req.merged_to_main is not None:
                    task.merged_to_main = req.merged_to_main
```

Also add the field to the WebSocket broadcast payload — in the same handler, the `await self._emit_event(... "task.updated", { ... })` block.  Add `"merged_to_main": task.merged_to_main` to the dict.

- [ ] **Step 5: Include the field in GET responses**

Locate `async def get_task` (right after `update_task`, ~line 845) and any other place that serializes a `Task` (e.g., the per-session task list).  Search with:

```bash
/usr/bin/grep -n 'task\.status\|task\.description' claw_forge/state/service.py
```

For each Task-to-dict serializer, add `"merged_to_main": task.merged_to_main` to the returned dict.

- [ ] **Step 6: Run test to verify it passes**

```bash
uv run pytest tests/state/test_service_merge_gating.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add claw_forge/state/service.py tests/state/test_service_merge_gating.py
git commit -m "feat(state): PATCH /tasks/{id} accepts merged_to_main"
```

---

## Task 4: Scheduler gates on `merged_to_main`

**Files:**
- Modify: `claw_forge/state/scheduler.py`
- Test: `tests/state/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/state/test_scheduler.py` (or create the file):

```python
"""Tests for the dependency-aware scheduler."""
from __future__ import annotations

from claw_forge.state.scheduler import Scheduler, TaskNode


def test_completed_dep_not_merged_to_main_keeps_child_blocked() -> None:
    """A child whose parent is completed but merged_to_main=False stays blocked."""
    s = Scheduler()
    parent = TaskNode(
        id="parent", plugin_name="coding", priority=0, depends_on=[],
        status="completed", merged_to_main=False,
    )
    child = TaskNode(
        id="child", plugin_name="coding", priority=0, depends_on=["parent"],
        status="pending",
    )
    s.add_task(parent)
    s.add_task(child)
    assert s.get_ready_tasks() == []  # child stays blocked


def test_completed_dep_with_merged_to_main_unblocks_child() -> None:
    """A child whose parent is completed AND merged_to_main is unblocked."""
    s = Scheduler()
    parent = TaskNode(
        id="parent", plugin_name="coding", priority=0, depends_on=[],
        status="completed", merged_to_main=True,
    )
    child = TaskNode(
        id="child", plugin_name="coding", priority=0, depends_on=["parent"],
        status="pending",
    )
    s.add_task(parent)
    s.add_task(child)
    assert [t.id for t in s.get_ready_tasks()] == ["child"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/state/test_scheduler.py::test_completed_dep_not_merged_to_main_keeps_child_blocked -v
```

Expected: FAIL — `TaskNode` has no `merged_to_main` field.

- [ ] **Step 3: Add field to `TaskNode`**

In `claw_forge/state/scheduler.py`, modify the dataclass:

```python
@dataclass
class TaskNode:
    """Lightweight task representation for scheduling."""

    id: str
    plugin_name: str
    priority: int
    depends_on: list[str]
    status: str = "pending"
    category: str = ""
    steps: list[str] = field(default_factory=list)
    description: str = ""
    merged_to_main: bool = True  # NEW — backward compat default
```

- [ ] **Step 4: Update `get_ready_tasks` to gate on `merged_to_main`**

In the same file, modify `get_ready_tasks`:

```python
    def get_ready_tasks(self) -> list[TaskNode]:
        """Return tasks whose dependencies are all completed AND merged."""
        # A dep is satisfied when status == completed AND merged_to_main is True.
        satisfied: set[str] = {
            tid for tid, t in self._tasks.items()
            if t.status == "completed" and t.merged_to_main
        }
        failed = {tid for tid, t in self._tasks.items() if t.status == "failed"}

        ready: list[TaskNode] = []
        for task in self._tasks.values():
            if task.status != "pending":
                continue
            known_failed = {dep for dep in task.depends_on if dep in failed}
            if known_failed:
                task.status = "blocked"
                continue
            unsatisfied = {
                dep for dep in task.depends_on
                if dep in self._tasks and dep not in satisfied
            }
            if not unsatisfied:
                ready.append(task)

        return sorted(ready, key=lambda t: t.priority, reverse=True)
```

- [ ] **Step 5: Apply the same gate to `get_execution_order`**

Modify the `completed` set in `get_execution_order` to also require `merged_to_main`:

```python
    def get_execution_order(self) -> list[list[str]]:
        self.validate_no_cycles()
        waves: list[list[str]] = []
        # Tasks already-completed-and-merged before this dispatch cycle.
        completed: set[str] = {
            tid for tid, t in self._tasks.items()
            if t.status == "completed" and t.merged_to_main
        }
        remaining = {tid for tid, t in self._tasks.items() if t.status == "pending"}

        while remaining:
            wave: list[str] = []
            for tid in list(remaining):
                task = self._tasks[tid]
                unsatisfied = {
                    dep for dep in task.depends_on
                    if dep in self._tasks and dep not in completed
                }
                if not unsatisfied:
                    wave.append(tid)
            if not wave:
                break
            wave.sort(key=lambda t: self._tasks[t].priority, reverse=True)
            waves.append(wave)
            completed.update(wave)
            remaining -= set(wave)

        return waves
```

- [ ] **Step 6: Run scheduler tests**

```bash
uv run pytest tests/state/test_scheduler.py -v
```

Expected: all green (new gate tests pass, existing tests still pass because default `merged_to_main=True` preserves prior behavior).

- [ ] **Step 7: Commit**

```bash
git add claw_forge/state/scheduler.py tests/state/test_scheduler.py
git commit -m "feat(scheduler): gate dep satisfaction on merged_to_main"
```

---

## Task 5: Dispatcher PATCHes `merged_to_main=False` at start, `True` after merge

**Files:**
- Modify: `claw_forge/cli.py` (the task_handler around lines 970-1385)
- Test: `tests/test_cli_merge_gating.py`

This task wires the gate into runtime: when a task starts on a feature branch with `merge_strategy: auto`, the dispatcher PATCHes `merged_to_main=False`.  After `apply_on_completion` returns a successful merge, it PATCHes back to `True`.

- [ ] **Step 1: Locate the existing PATCHes**

Run:

```bash
/usr/bin/grep -n '_patch_task' claw_forge/cli.py
/usr/bin/grep -n 'apply_on_completion' claw_forge/cli.py
```

Note the line numbers of:
- The `status="running"` PATCH (~line 975)
- The `status="completed" if success else "failed"` PATCH (~line 1361)
- The `apply_on_completion` call (~line 1370)

- [ ] **Step 2: Write the failing test**

Create `tests/test_cli_merge_gating.py`:

```python
"""Test that the dispatcher gates dependents on merge success.

These tests exercise the merge_to_main lifecycle directly via the helper
that wraps PATCH calls — exhaustive end-to-end runs are out of scope
because they require provider keys.  We verify the call sequence.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from claw_forge.cli import _set_merged_to_main_after_merge


@pytest.mark.asyncio
async def test_set_merged_to_main_after_merge_calls_patch_true_on_success() -> None:
    http = AsyncMock()
    merge_result = {"merged": True, "commit_hash": "abc1234"}
    base = "http://localhost:8420"
    await _set_merged_to_main_after_merge(http, base, "task-1", merge_result)
    http.patch.assert_called_once()
    args, kwargs = http.patch.call_args
    assert args[0] == f"{base}/tasks/task-1"
    assert kwargs["json"] == {"merged_to_main": True}


@pytest.mark.asyncio
async def test_set_merged_to_main_after_merge_no_patch_on_failure() -> None:
    http = AsyncMock()
    merge_result = {"merged": False, "error": "conflict"}
    await _set_merged_to_main_after_merge(http, "http://x", "task-1", merge_result)
    http.patch.assert_not_called()


@pytest.mark.asyncio
async def test_set_merged_to_main_after_merge_no_patch_when_none() -> None:
    """When merge isn't attempted (manual strategy / git disabled), no PATCH."""
    http = AsyncMock()
    await _set_merged_to_main_after_merge(http, "http://x", "task-1", None)
    http.patch.assert_not_called()
```

- [ ] **Step 3: Run test to verify it fails**

```bash
uv run pytest tests/test_cli_merge_gating.py -v
```

Expected: FAIL with `ImportError: cannot import name '_set_merged_to_main_after_merge'`.

- [ ] **Step 4: Add the helper to `cli.py`**

In `claw_forge/cli.py`, add at module level (near other private helpers — search with `grep -n '^async def _' claw_forge/cli.py`):

```python
async def _set_merged_to_main_after_merge(
    http: Any, state_base: str, task_id: str, merge_result: dict | None,
) -> None:
    """PATCH merged_to_main=True after a successful auto-merge.

    Called by the task_handler after apply_on_completion returns.  Does
    nothing when:
      * ``merge_result is None`` — no merge was attempted (git disabled,
        manual strategy, or task failed).
      * ``merge_result['merged'] is False`` — squash hit a conflict.  The
        task stays "completed but not merged"; dependents stay blocked
        until a manual merge or a retry resolves it.
    """
    import httpx
    if merge_result is None or not merge_result.get("merged"):
        return
    with suppress(httpx.HTTPError):
        await http.patch(
            f"{state_base}/tasks/{task_id}", json={"merged_to_main": True},
        )
```

(`suppress` is already imported in `cli.py`; verify with `grep -n 'from contextlib' claw_forge/cli.py`.)

- [ ] **Step 5: Run helper tests to verify pass**

```bash
uv run pytest tests/test_cli_merge_gating.py -v
```

Expected: PASS.

- [ ] **Step 6: PATCH `merged_to_main=False` when starting an auto-merged task**

In the task_handler, find the line that PATCHes `status="running"`.  Replace it (and the immediately preceding context) so that when `git_enabled and git_merge_strategy == "auto"`, the same call also sets `merged_to_main=False`:

```python
                # ── Mark task running; flip merged_to_main=False so children
                #    stay blocked until our squash-merge succeeds.
                if git_enabled and git_merge_strategy == "auto":
                    await _patch_task(
                        http, task_node.id,
                        status="running", merged_to_main=False,
                    )
                else:
                    await _patch_task(http, task_node.id, status="running")
```

(The `merged_to_main` keyword passes through `**fields` to `_patch_task` and into the JSON body; no helper change needed.)

- [ ] **Step 7: Capture `apply_on_completion` result and call the helper**

Find the `await git_ops.apply_on_completion(...)` call.  Capture its return value and pass it to the helper:

```python
                    if git_enabled:
                        merge_result = await git_ops.apply_on_completion(
                            task_id=task_node.id,
                            slug=_slug,
                            description=task_node.description or None,
                            plugin_name=task_node.plugin_name,
                            steps=task_node.steps or None,
                            worktree_path=_worktree_path,
                            success=success,
                            commit_on_boundary=git_commit_on_boundary,
                            merge_strategy=git_merge_strategy,
                            branch_prefix=git_branch_prefix,
                            target_branch=_default_branch,
                            session_id=session_id,
                        )
                        await _set_merged_to_main_after_merge(
                            http, _state_base, task_node.id, merge_result,
                        )
```

- [ ] **Step 8: Run the cli_merge_gating tests + cli regression**

```bash
uv run pytest tests/test_cli_merge_gating.py tests/test_cli_commands.py -v
```

Expected: all green; no regressions.

- [ ] **Step 9: Commit**

```bash
git add claw_forge/cli.py tests/test_cli_merge_gating.py
git commit -m "feat(cli): gate dependents on merge success via merged_to_main"
```

---

## Task 6: Load `merged_to_main` from DB into TaskNode

**Files:**
- Modify: `claw_forge/cli.py` (the place where DB tasks are converted into `TaskNode` for the scheduler)
- Test: covered by Task 4's scheduler tests + Task 5's helper tests; one integration check is added below.

The scheduler is fed `TaskNode` instances built from DB rows.  We need to populate `merged_to_main` from the DB.

- [ ] **Step 1: Locate the conversion site**

```bash
/usr/bin/grep -n 'TaskNode(' claw_forge/cli.py
```

Find every place where `TaskNode(...)` is constructed from a HTTP response or DB row.  Most likely there's a single helper that maps the JSON to TaskNode.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_cli_merge_gating.py`:

```python
def test_task_dict_to_node_reads_merged_to_main() -> None:
    """The DB→TaskNode mapper preserves merged_to_main."""
    from claw_forge.cli import _task_dict_to_node  # adapt to actual helper name

    payload = {
        "id": "t1", "plugin_name": "coding", "priority": 0,
        "depends_on": [], "status": "completed",
        "merged_to_main": False, "description": "X", "category": "c",
        "steps": [],
    }
    node = _task_dict_to_node(payload)
    assert node.merged_to_main is False
    # Backward-compat: missing key defaults to True.
    payload2 = dict(payload)
    payload2.pop("merged_to_main")
    node2 = _task_dict_to_node(payload2)
    assert node2.merged_to_main is True
```

- [ ] **Step 3: Run test (likely fails on import)**

```bash
uv run pytest tests/test_cli_merge_gating.py::test_task_dict_to_node_reads_merged_to_main -v
```

If `_task_dict_to_node` doesn't exist, you have two options:
1. Add a small helper at module level that builds a `TaskNode` from the JSON dict.
2. Find the existing inline construction and extract it into the helper.

Either way, the helper must read `merged_to_main` with `.get("merged_to_main", True)` (default `True` for backward compat).

- [ ] **Step 4: Implement / extract the helper**

Add to `claw_forge/cli.py`:

```python
def _task_dict_to_node(payload: dict[str, Any]) -> "TaskNode":
    """Build a scheduler TaskNode from a state-service task JSON payload."""
    from claw_forge.state.scheduler import TaskNode
    return TaskNode(
        id=payload["id"],
        plugin_name=payload.get("plugin_name", ""),
        priority=int(payload.get("priority", 0) or 0),
        depends_on=list(payload.get("depends_on", []) or []),
        status=payload.get("status", "pending"),
        category=payload.get("category", "") or "",
        steps=list(payload.get("steps", []) or []),
        description=payload.get("description", "") or "",
        merged_to_main=bool(payload.get("merged_to_main", True)),
    )
```

Then replace inline `TaskNode(...)` constructions with `_task_dict_to_node(payload)`.

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_cli_merge_gating.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add claw_forge/cli.py tests/test_cli_merge_gating.py
git commit -m "feat(cli): propagate merged_to_main from DB into scheduler TaskNode"
```

---

## Task 7: Documentation

The merge-gating change adds a public-surface field on `PATCH /tasks/{id}` (the `merged_to_main` JSON key) and a new behaviour visible to integrators (downstream tasks stay blocked when the parent's auto-merge fails). Per project convention, schema/API changes update CLAUDE.md before landing.

**Files:**
- Modify: `CLAUDE.md` (root) — the State Service API section + a short architectural note

- [ ] **Step 1: Update CLAUDE.md "State Service API" section**

Find the `### State Service API` heading. The endpoint list currently says:
```
- `POST /sessions/{id}/tasks`, `PATCH /sessions/{id}/tasks/{id}` (status, cost, tokens)
```

Update the PATCH parenthetical to:
```
- `POST /sessions/{id}/tasks`, `PATCH /sessions/{id}/tasks/{id}` (status, cost, tokens, merged_to_main)
```

- [ ] **Step 2: Add an architectural note under "Key Conventions"**

Append to the bottom of the `## Key Conventions` section:

```markdown
- **Merge-gating** (`merged_to_main` flag on tasks): a dependent task is unblocked only when its parent is `status=completed AND merged_to_main=True`. The dispatcher PATCHes `merged_to_main=False` when starting a task on a feature branch with `merge_strategy: auto`, and back to `True` after a successful squash. If the squash fails, the task stays "completed but not merged" and its descendants stay blocked until a manual merge or retry resolves the conflict — preventing dependents from running on a stale main.
```

- [ ] **Step 3: Verify with a quick read**

```bash
/usr/bin/grep -A2 "State Service API" /Users/bowenli/development/claw-forge/.worktrees/merge-gating-and-file-locks/CLAUDE.md | head -20
/usr/bin/grep -A3 "Merge-gating" /Users/bowenli/development/claw-forge/.worktrees/merge-gating-and-file-locks/CLAUDE.md
```

Both greps should match.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): document merged_to_main gating + PATCH field"
```

---

## Task 8: Lint, type-check, full suite, coverage

- [ ] **Step 1: Lint**

```bash
uv run ruff check claw_forge/ tests/
```

Expected: All checks passed!

- [ ] **Step 2: Type check**

```bash
uv run mypy claw_forge/ --ignore-missing-imports
```

Expected: Success: no issues found.

- [ ] **Step 3: Full test suite with coverage**

```bash
uv run pytest tests/ -q --cov=claw_forge --cov-report=term
```

Expected: all tests pass, coverage ≥ 90%.

- [ ] **Step 4: Spot-check the new behavior on a synthetic DAG**

```bash
uv run python - <<'PY'
from claw_forge.state.scheduler import Scheduler, TaskNode
s = Scheduler()
s.add_task(TaskNode("a", "coding", 0, [], status="completed", merged_to_main=False))
s.add_task(TaskNode("b", "coding", 0, ["a"], status="pending"))
print("ready (parent unmerged):", [t.id for t in s.get_ready_tasks()])
s._tasks["a"].merged_to_main = True
print("ready (parent merged):", [t.id for t in s.get_ready_tasks()])
PY
```

Expected output:
```
ready (parent unmerged): []
ready (parent merged): ['b']
```

- [ ] **Step 5: No commit needed if all clean**

Otherwise commit any final fixes.

---

## Self-Review

**Spec coverage:**
- ✅ `merged_to_main` column on Task with default True (Task 1)
- ✅ Backward-compat ALTER TABLE for legacy DBs (Task 2)
- ✅ PATCH endpoint accepts the field; WS broadcasts it (Task 3)
- ✅ Scheduler gates dep satisfaction on the field (Task 4)
- ✅ Dispatcher flips False at start, True after successful merge (Task 5)
- ✅ DB→TaskNode propagation (Task 6)
- ✅ Lint / types / coverage (Task 7)

**Placeholder scan:** none — every step has the actual code or command.

**Type consistency:** `merged_to_main: bool` consistent across `Task` (SQLAlchemy `Boolean`), `UpdateTaskRequest` (Pydantic `bool | None`), `TaskNode` (dataclass `bool`). PATCH JSON value is `bool`.

**Notes for the implementer:**
- Task 5 step 6 modifies the `_patch_task` *call* (passing `merged_to_main` via kwargs); `_patch_task` already accepts `**fields`, so no signature change needed.
- Task 6 step 1 is light code archaeology — depending on the current cli.py structure there may be one or two `TaskNode(` constructions; refactor each to use the helper.
- The test in Task 5 mocks the HTTP client; we deliberately do not start the full state service for this layer because the wire-level behavior is already covered by Task 3.
