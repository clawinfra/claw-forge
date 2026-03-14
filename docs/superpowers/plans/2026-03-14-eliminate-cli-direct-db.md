# Eliminate CLI Direct DB Access — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the CLI's direct SQLite access so only the state service writes to the database, eliminating the dual-writer contention that causes `disk I/O error` and `database disk image is malformed`.

**Architecture:** The CLI currently creates its own SQLAlchemy engine (`cli.py:533`) that competes with the state service subprocess for SQLite writes. We add two missing HTTP endpoints to the state service, then replace all 5 `async_session_maker` call sites in the CLI with HTTP calls via the existing `_patch_task` pattern. After this, the CLI is a pure HTTP client — single writer, no contention.

**Tech Stack:** FastAPI (state service), httpx (CLI HTTP client), SQLAlchemy+aiosqlite (state service only)

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `claw_forge/state/service.py` | Modify | Add `GET /tasks/{task_id}` and `POST /sessions/init` endpoints |
| `claw_forge/cli.py` | Modify | Replace all direct DB access with HTTP calls; remove SQLAlchemy engine/imports |
| `tests/test_session_init_endpoint.py` | Create | Tests for the new `/sessions/init` endpoint |
| `tests/test_get_task_endpoint.py` | Create | Tests for the new `GET /tasks/{task_id}` endpoint |

---

## Chunk 1: Add Missing HTTP Endpoints

### Task 1: Add `GET /tasks/{task_id}` endpoint

**Files:**
- Modify: `claw_forge/state/service.py:466-508` (after existing `PATCH /tasks/{task_id}`)
- Create: `tests/test_get_task_endpoint.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_get_task_endpoint.py
"""Tests for GET /tasks/{task_id} endpoint."""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from claw_forge.state.service import AgentStateService


@pytest.fixture()
async def app_client(tmp_path: Path):
    db_path = tmp_path / "test.db"
    svc = AgentStateService(f"sqlite+aiosqlite:///{db_path}")
    try:
        await svc.init_db()
        app = svc.create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c
    finally:
        await svc.dispose()


@pytest.mark.asyncio
class TestGetTask:
    async def test_get_existing_task(self, app_client: AsyncClient) -> None:
        sess = await app_client.post("/sessions", json={"project_path": "/p"})
        sid = sess.json()["id"]
        created = await app_client.post(
            f"/sessions/{sid}/tasks",
            json={
                "plugin_name": "coding",
                "description": "Implement auth",
                "steps": ["Create endpoint", "Add tests"],
                "category": "backend",
            },
        )
        task_id = created.json()["id"]

        resp = await app_client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == task_id
        assert data["description"] == "Implement auth"
        assert data["steps"] == ["Create endpoint", "Add tests"]
        assert data["plugin_name"] == "coding"
        assert data["status"] == "pending"

    async def test_get_nonexistent_task(self, app_client: AsyncClient) -> None:
        resp = await app_client.get("/tasks/nonexistent-id")
        assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_get_task_endpoint.py -v`
Expected: FAIL — 404 because `GET /tasks/{task_id}` route doesn't exist yet

- [ ] **Step 3: Implement the endpoint**

In `claw_forge/state/service.py`, add after the existing `PATCH /tasks/{task_id}` block (after line 508):

```python
@app.get("/tasks/{task_id}")
async def get_task(task_id: str) -> dict[str, Any]:
    async with self._session_factory() as db:
        task = await db.get(Task, task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        return {
            "id": task.id,
            "session_id": task.session_id,
            "plugin_name": task.plugin_name,
            "description": task.description,
            "category": task.category,
            "status": task.status,
            "priority": task.priority,
            "depends_on": task.depends_on,
            "steps": task.steps or [],
            "result_json": task.result_json,
            "error_message": task.error_message,
            "input_tokens": task.input_tokens,
            "output_tokens": task.output_tokens,
            "cost_usd": task.cost_usd,
            "created_at": str(task.created_at) if task.created_at else None,
            "started_at": str(task.started_at) if task.started_at else None,
            "completed_at": str(task.completed_at) if task.completed_at else None,
        }
```

**Important:** This must be placed BEFORE the `PATCH /tasks/{task_id}` route, or at least registered so FastAPI matches GET before PATCH. FastAPI handles method dispatch correctly regardless of order for different HTTP methods on the same path, so placing it right after `PATCH /tasks/{task_id}` is fine.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_get_task_endpoint.py -v`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check claw_forge/state/service.py tests/test_get_task_endpoint.py
git add claw_forge/state/service.py tests/test_get_task_endpoint.py
git commit -m "feat: add GET /tasks/{task_id} endpoint"
```

---

### Task 2: Add `POST /sessions/init` endpoint

This endpoint atomically: finds or creates a session by project path, resets orphaned running tasks, and returns the session + its actionable tasks.

**Files:**
- Modify: `claw_forge/state/service.py` (add after session endpoints, ~line 422)
- Create: `tests/test_session_init_endpoint.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session_init_endpoint.py
"""Tests for POST /sessions/init endpoint."""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from claw_forge.state.service import AgentStateService


@pytest.fixture()
async def app_client(tmp_path: Path):
    db_path = tmp_path / "test.db"
    svc = AgentStateService(f"sqlite+aiosqlite:///{db_path}")
    try:
        await svc.init_db()
        app = svc.create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c
    finally:
        await svc.dispose()


@pytest.mark.asyncio
class TestSessionInit:
    async def test_creates_new_session_when_none_exists(
        self, app_client: AsyncClient,
    ) -> None:
        resp = await app_client.post(
            "/sessions/init", json={"project_path": "/my/project"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"]
        assert data["tasks"] == []

    async def test_reuses_existing_session(
        self, app_client: AsyncClient,
    ) -> None:
        # Create a session with tasks
        sess = await app_client.post(
            "/sessions", json={"project_path": "/my/project"}
        )
        sid = sess.json()["id"]
        await app_client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "coding", "description": "Task A"},
        )

        # Init should find the existing session
        resp = await app_client.post(
            "/sessions/init", json={"project_path": "/my/project"}
        )
        data = resp.json()
        assert data["session_id"] == sid
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["description"] == "Task A"

    async def test_resets_orphaned_running_tasks(
        self, app_client: AsyncClient,
    ) -> None:
        sess = await app_client.post(
            "/sessions", json={"project_path": "/my/project"}
        )
        sid = sess.json()["id"]
        t = await app_client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "coding", "description": "Orphan"},
        )
        tid = t.json()["id"]
        # Simulate orphaned running task
        await app_client.patch(f"/tasks/{tid}", json={"status": "running"})

        resp = await app_client.post(
            "/sessions/init", json={"project_path": "/my/project"}
        )
        data = resp.json()
        orphan = [t for t in data["tasks"] if t["id"] == tid][0]
        assert orphan["status"] == "pending"
        assert data.get("orphans_reset", 0) == 1

    async def test_excludes_completed_tasks(
        self, app_client: AsyncClient,
    ) -> None:
        sess = await app_client.post(
            "/sessions", json={"project_path": "/my/project"}
        )
        sid = sess.json()["id"]
        t1 = await app_client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "coding", "description": "Done"},
        )
        await app_client.patch(
            f"/tasks/{t1.json()['id']}", json={"status": "completed"}
        )
        await app_client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "coding", "description": "Pending"},
        )

        resp = await app_client.post(
            "/sessions/init", json={"project_path": "/my/project"}
        )
        data = resp.json()
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["description"] == "Pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_session_init_endpoint.py -v`
Expected: FAIL — 404/405 because route doesn't exist

- [ ] **Step 3: Implement the endpoint**

Add a new Pydantic model and route in `claw_forge/state/service.py`:

Model (add near line 173, after `UpdateTaskRequest`):

```python
class SessionInitRequest(BaseModel):
    project_path: str
```

Route (add after `GET /sessions/{session_id}`, ~line 464):

```python
@app.post("/sessions/init")
async def init_session(req: SessionInitRequest) -> dict[str, Any]:
    """Find or create a session, reset orphans, return actionable tasks."""
    async with self._session_factory() as db:
        # Find existing running/pending session for this project
        result = await db.execute(
            select(Session)
            .where(Session.project_path == req.project_path)
            .where(Session.status.in_(["running", "pending"]))
            .order_by(Session.created_at.desc())
            .limit(1)
        )
        session = result.scalar_one_or_none()

        if session is None:
            session = Session(project_path=req.project_path)
            db.add(session)
            await db.commit()
            await db.refresh(session)

        # Fetch actionable tasks (pending, failed, running/orphaned)
        result = await db.execute(
            select(Task)
            .where(Task.session_id == session.id)
            .where(Task.status.in_(["pending", "failed", "running"]))
        )
        tasks = result.scalars().all()

        # Reset orphaned running tasks
        orphans_reset = 0
        for t in tasks:
            if t.status == "running":
                t.status = "pending"
                t.started_at = None
                orphans_reset += 1
        if orphans_reset:
            await db.commit()

        return {
            "session_id": session.id,
            "orphans_reset": orphans_reset,
            "tasks": [
                {
                    "id": t.id,
                    "plugin_name": t.plugin_name,
                    "description": t.description,
                    "category": t.category,
                    "status": t.status,
                    "priority": t.priority,
                    "depends_on": t.depends_on,
                    "steps": t.steps or [],
                }
                for t in tasks
            ],
        }
```

**Important:** This route must be registered BEFORE `GET /sessions/{session_id}` to avoid FastAPI matching `"init"` as a `session_id` path parameter. Place it right after `GET /sessions`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_session_init_endpoint.py -v`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check claw_forge/state/service.py tests/test_session_init_endpoint.py
git add claw_forge/state/service.py tests/test_session_init_endpoint.py
git commit -m "feat: add POST /sessions/init endpoint for atomic session bootstrap"
```

---

## Chunk 2: Replace CLI Direct DB Access with HTTP Calls

### Task 3: Replace session init (lines 532-617)

Replace the SQLAlchemy engine setup, `Base.metadata.create_all`, `_migrate_schema`, and the session find-or-create + task fetch logic with a single `POST /sessions/init` HTTP call.

**Files:**
- Modify: `claw_forge/cli.py:413-617`

- [ ] **Step 1: Remove the engine/session_maker setup (lines 532-536)**

Delete these lines:
```python
engine = create_async_engine(db_url, echo=False)
async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)
```

- [ ] **Step 2: Remove `Base.metadata.create_all` and `_migrate_schema` (lines 538-541)**

Delete from `async def main()`:
```python
async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)
await _migrate_schema(engine)
```

The state service already handles table creation and migrations in `init_db()`.

- [ ] **Step 3: Replace the session/task fetch block (lines 543-617)**

Replace the entire `async with async_session_maker() as session:` block with:

```python
async with httpx.AsyncClient() as init_client:
    resp = await init_client.post(
        f"{_state_base}/sessions/init",
        json={"project_path": str(project_path)},
        timeout=10,
    )
    resp.raise_for_status()
    init_data = resp.json()

session_id = init_data["session_id"]
raw_tasks = init_data["tasks"]

if init_data.get("orphans_reset", 0):
    console.print(
        f"[yellow]Reset {init_data['orphans_reset']} orphaned task(s) "
        "from previous interrupted run[/yellow]"
    )

if not raw_tasks:
    console.print(
        "[yellow]No pending tasks found — run 'claw-forge plan <spec>' first[/yellow]"
    )
    return

task_nodes: list[TaskNode] = []
for t in raw_tasks:
    node = TaskNode(
        id=t["id"],
        plugin_name=t["plugin_name"],
        priority=t.get("priority", 0),
        depends_on=t.get("depends_on") or [],
        status="pending",
        category=t.get("category") or "",
        steps=t.get("steps") or [],
        description=t.get("description") or "",
    )
    task_nodes.append(node)
```

- [ ] **Step 4: Update all references from `db_session.id` to `session_id`**

Throughout the rest of `main()`, replace `db_session.id` with `session_id`. This variable is used for:
- Git checkpoint `session_id` parameter
- Git merge `session_id` parameter
- Pause polling `?session_id=`
- Resume-all URL
- Stop-all URL

- [ ] **Step 5: Remove unused imports**

From `cli.py:413-417`, remove:
```python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from claw_forge.state.models import Base, Task
from claw_forge.state.models import Session as DbSession
```

Also remove `from sqlalchemy import select` (line 545).

Keep only what's still needed (check for other usages of `Task`, `DbSession`, `select` in the rest of the file — there are usages in `_write_plan_to_db` at line 1415+ but those have their own local imports).

- [ ] **Step 6: Run tests and lint**

```bash
uv run ruff check claw_forge/cli.py
uv run pytest tests/ -q
```

- [ ] **Step 7: Commit**

```bash
git add claw_forge/cli.py
git commit -m "refactor: replace CLI session init with POST /sessions/init HTTP call"
```

---

### Task 4: Replace task_handler direct DB reads/writes (lines 753-766, 1032-1055)

The `task_handler` function currently hits the DB directly in three places:
1. **Line 753-766:** Fetch task details + mark running
2. **Line 1032-1042:** Reset cancelled task to pending
3. **Line 1047-1055:** Persist final task result

All three can be replaced with HTTP calls.

**Files:**
- Modify: `claw_forge/cli.py:750-1055`

- [ ] **Step 1: Replace task detail fetch + mark running (lines 753-766)**

Replace:
```python
async with async_session_maker() as task_session:
    stmt_update = select(Task).where(Task.id == task_node.id)
    result = await task_session.execute(stmt_update)
    db_task = result.scalar_one()
    task_name = db_task.description or db_task.plugin_name
    prompt = db_task.description or f"Execute task: {db_task.plugin_name}"
    if db_task.steps:
        numbered = "\n".join(
            f"{i + 1}. {s}" for i, s in enumerate(db_task.steps)
        )
        prompt = f"{prompt}\n\n## Verification Steps\n{numbered}"
    db_task.status = "running"
    db_task.started_at = datetime.now(UTC)
    await task_session.commit()
```

With:
```python
# Fetch task details via HTTP
task_resp = await http.get(
    f"{_state_base}/tasks/{task_node.id}", timeout=10,
)
task_resp.raise_for_status()
task_data = task_resp.json()
task_name = task_data.get("description") or task_data["plugin_name"]
prompt = task_data.get("description") or f"Execute task: {task_data['plugin_name']}"
steps = task_data.get("steps") or []
if steps:
    numbered = "\n".join(
        f"{i + 1}. {s}" for i, s in enumerate(steps)
    )
    prompt = f"{prompt}\n\n## Verification Steps\n{numbered}"

# Mark running via HTTP (triggers WS broadcast)
await _patch_task(http, task_node.id, status="running")
```

Note: `_patch_task` already calls `PATCH /tasks/{task_id}` which auto-sets `started_at` when status transitions to "running" (service.py:474-475).

- [ ] **Step 2: Replace cancel cleanup (lines 1032-1042)**

Replace:
```python
async with async_session_maker() as cancel_session:
    stmt_c = select(Task).where(Task.id == task_node.id)
    res_c = await cancel_session.execute(stmt_c)
    c_task = res_c.scalar_one()
    if c_task.status == "running":
        c_task.status = "pending"
        c_task.started_at = None
        await cancel_session.commit()
        await _patch_task(
            http, task_node.id, status="pending",
        )
```

With:
```python
await _patch_task(http, task_node.id, status="pending")
```

Note: The existing `_patch_task` call at the end was already there — the direct DB write was redundant. Now a single HTTP PATCH handles it. We need to ensure the `PATCH /tasks/{task_id}` endpoint clears `started_at` when status goes back to "pending". Check if this is needed — if not, add it.

- [ ] **Step 3: Replace final result persistence (lines 1047-1055)**

Replace:
```python
async with async_session_maker() as fin_session:
    stmt_fin = select(Task).where(Task.id == task_node.id)
    res_fin = await fin_session.execute(stmt_fin)
    fin_task = res_fin.scalar_one()
    fin_task.status = "completed" if success else "failed"
    fin_task.completed_at = datetime.now(UTC)
    fin_task.error_message = None if success else output
    fin_task.result_json = {"output": output} if success else None
    await fin_session.commit()
```

With:
```python
await _patch_task(
    http, task_node.id,
    status="completed" if success else "failed",
    **({"result": {"output": output}} if success else {}),
    **({"error_message": output} if not success else {}),
)
```

The `PATCH /tasks/{task_id}` endpoint already auto-sets `completed_at` for "completed"/"failed" statuses (service.py:476-477).

- [ ] **Step 4: Verify `PATCH /tasks/{task_id}` clears `started_at` on "pending" transition**

Check `service.py:472-477`. If transitioning to "pending" doesn't clear `started_at`, add:

```python
elif req.status == "pending":
    task.started_at = None
```

- [ ] **Step 5: Remove the now-unnecessary second `_patch_task` call at line 1080**

After the final result persistence block, line 1080-1084 had a separate `_patch_task` call for the UI notification. Since the persistence is now done via `_patch_task` (which goes through the same HTTP endpoint that triggers WS broadcast), this duplicate call should be removed.

- [ ] **Step 6: Run tests and lint**

```bash
uv run ruff check claw_forge/cli.py claw_forge/state/service.py
uv run pytest tests/ -q
```

- [ ] **Step 7: Commit**

```bash
git add claw_forge/cli.py claw_forge/state/service.py
git commit -m "refactor: replace task_handler direct DB access with HTTP calls"
```

---

### Task 5: Replace resume loop DB access (lines 1136-1162)

**Files:**
- Modify: `claw_forge/cli.py:1136-1162`

- [ ] **Step 1: Replace direct DB query with HTTP calls**

The existing `POST /sessions/{session_id}/tasks/resume-all` endpoint already resets paused→pending. And `GET /sessions/{session_id}/tasks` returns all tasks with full details.

Replace:
```python
async with async_session_maker() as resume_session:
    stmt_resume = select(Task).where(
        Task.session_id == db_session.id,
        Task.status.in_(["pending", "paused"]),
    )
    res_resume = await resume_session.execute(stmt_resume)
    remaining = res_resume.scalars().all()
    for t in remaining:
        if t.status == "paused":
            t.status = "pending"
            t.started_at = None
    await resume_session.commit()

current_nodes = [
    TaskNode(
        id=t.id,
        plugin_name=t.plugin_name,
        priority=t.priority,
        depends_on=t.depends_on or [],
        status="pending",
        category=t.category or "",
        steps=t.steps or [],
        description=t.description or "",
    )
    for t in remaining
]
```

With:
```python
# resume-all already resets paused→pending in the state service
# (called by the UI or poll loop), so just fetch current tasks
async with httpx.AsyncClient() as resume_client:
    tasks_resp = await resume_client.get(
        f"{_state_base}/sessions/{session_id}/tasks",
        timeout=10,
    )
    tasks_resp.raise_for_status()
    all_tasks = tasks_resp.json()

current_nodes = [
    TaskNode(
        id=t["id"],
        plugin_name=t["plugin_name"],
        priority=t.get("priority", 0),
        depends_on=t.get("depends_on") or [],
        status="pending",
        category=t.get("category") or "",
        steps=t.get("steps") or [],
        description=t.get("description") or "",
    )
    for t in all_tasks
    if t["status"] in ("pending", "failed")
]
```

- [ ] **Step 2: Run tests and lint**

```bash
uv run ruff check claw_forge/cli.py
uv run pytest tests/ -q
```

- [ ] **Step 3: Commit**

```bash
git add claw_forge/cli.py
git commit -m "refactor: replace resume loop direct DB access with HTTP calls"
```

---

### Task 6: Remove dead code and clean up

**Files:**
- Modify: `claw_forge/cli.py`

- [ ] **Step 1: Remove `db_url` and `db_path` from the `run` command**

Lines 513-514 create `db_path` and `db_url` — these are no longer needed since the CLI doesn't connect to the DB. Remove:
```python
db_path = claw_forge_dir / "state.db"
db_url = f"sqlite+aiosqlite:///{db_path}"
console.print(f"[dim]DB: {db_path}[/dim]")
```

Keep `claw_forge_dir.mkdir(parents=True, exist_ok=True)` — the state service may still need this directory.

- [ ] **Step 2: Verify no remaining `async_session_maker` references in `run` command scope**

Search for any remaining direct DB access. The `_write_plan_to_db` function (line 1415+) and the `add` command also use direct DB — those are separate commands, not part of the `run` dispatcher loop. They have their own local imports and engine setup, so they're out of scope for this refactor (they run before the state service starts).

- [ ] **Step 3: Run full test suite + lint + type check**

```bash
uv run ruff check claw_forge/ tests/
uv run mypy claw_forge/ --ignore-missing-imports
uv run pytest tests/ -q
```

- [ ] **Step 4: Commit**

```bash
git add claw_forge/cli.py
git commit -m "refactor: remove dead SQLAlchemy engine/imports from CLI run command"
```

---

## Verification

After all tasks are complete:

```bash
# Full test suite (must pass with ≥90% coverage)
uv run pytest tests/ -q --cov=claw_forge --cov-report=term-missing

# Lint
uv run ruff check claw_forge/ tests/

# Type check
uv run mypy claw_forge/ --ignore-missing-imports

# Manual smoke test: run claw-forge against a test project
# Verify no "disk I/O error" or "database disk image is malformed" errors
# Verify the state service is the sole DB writer (check with lsof or fuser)
```
