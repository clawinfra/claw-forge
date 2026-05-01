# File-Claim Locks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent two concurrent agents from editing the same file by adding a runtime per-file claim system to the state service. A task may declare a list of files it intends to edit; the dispatcher claims those files atomically before starting the agent and releases them on task completion. If any file is already claimed by another running task, the dependent task stays pending and is retried in the next dispatch cycle. This is the runtime backstop to spec-time overlap analysis (Plan B): it catches conflicts that the spec author or LLM detector missed.

**Architecture:** New `file_claims` table on the state service (`session_id`, `task_id`, `file_path`, `claimed_at`) with a `UNIQUE(session_id, file_path)` constraint that gives us atomic all-or-nothing claim semantics in a single transaction. Two new endpoints (`POST /sessions/{id}/file-claims` and `DELETE /sessions/{id}/file-claims/{task_id}`) plus optional `touches_files: list[str]` on the task creation payload. Dispatcher integration is opt-in: tasks without `touches_files` behave exactly as today. Auto-release fires on task status flip to `completed`, `failed`, or `paused` so a forgotten release can't deadlock other tasks. The new table uses `CREATE TABLE IF NOT EXISTS`, so no DB migration is required for existing installations.

**Tech Stack:** Python 3.12, SQLAlchemy 2 (async), Pydantic, FastAPI, pytest, ruff, mypy.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `claw_forge/state/models.py` | Modify | Add `FileClaim` ORM model; add `touches_files: list[str]` JSON column on `Task` |
| `claw_forge/state/service.py` | Modify | Add request models, three endpoints, atomic claim helper, status-transition auto-release |
| `claw_forge/state/file_claims.py` | Create | Pure helpers: `try_claim`, `release_for_task`, `claims_for_session` (so service.py stays thin and helpers are unit-testable) |
| `claw_forge/cli.py` | Modify | Dispatcher: claim before starting (skip task if conflict), release on completion |
| `tests/state/test_file_claims.py` | Create | Helper unit tests (atomic claim, release, idempotence) |
| `tests/state/test_service_file_claims.py` | Create | Endpoint tests (POST claim, DELETE release, GET list) |
| `tests/test_cli_file_claims.py` | Create | Dispatcher integration: a task with conflicting touches_files is deferred |

---

## Task 1: ORM model + Task.touches_files column

**Files:**
- Modify: `claw_forge/state/models.py`
- Test: `tests/state/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/state/test_models.py`:

```python
@pytest.mark.asyncio
async def test_file_claim_unique_per_session() -> None:
    """The same (session_id, file_path) cannot be claimed twice."""
    from sqlalchemy.exc import IntegrityError
    from claw_forge.state.models import FileClaim

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Maker() as db:
        sess = Session(project_path="/tmp/x")
        db.add(sess); await db.flush()
        t1 = Task(session_id=sess.id, plugin_name="coding")
        t2 = Task(session_id=sess.id, plugin_name="coding")
        db.add_all([t1, t2]); await db.flush()
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
    Maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Maker() as db:
        sess = Session(project_path="/tmp/x")
        db.add(sess); await db.flush()
        t = Task(session_id=sess.id, plugin_name="coding")
        db.add(t); await db.commit(); await db.refresh(t)
        assert t.touches_files == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/state/test_models.py -v -k file_claim
```

Expected: FAIL — `FileClaim` and `Task.touches_files` are not defined.

- [ ] **Step 3: Add `FileClaim` model + `touches_files` column**

In `claw_forge/state/models.py`, after the existing `Event` class (and after the imports already include `UniqueConstraint`; if not, add it from `sqlalchemy`):

```python
from sqlalchemy import UniqueConstraint  # already imported above? if not, add it
```

Add `touches_files` to the `Task` class (place after `bugfix_retry_count`):

```python
    touches_files: Mapped[list[str]] = mapped_column(
        SafeJSON(fallback=[]), default=list, nullable=False,
    )
```

Append the `FileClaim` model at the bottom of the file:

```python
class FileClaim(Base):
    """A live claim by a running task on a single file path.

    The ``UNIQUE(session_id, file_path)`` constraint provides atomic
    claim semantics: an INSERT inside a transaction either succeeds for
    all rows or rolls back, so two tasks racing for the same file see a
    deterministic winner.
    """

    __tablename__ = "file_claims"
    __table_args__ = (
        UniqueConstraint("session_id", "file_path", name="uq_file_claim_session_path"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=False,
    )
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=False,
    )
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC),
    )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/state/test_models.py -v -k 'file_claim or touches_files'
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/state/models.py tests/state/test_models.py
git commit -m "feat(state): add FileClaim model + Task.touches_files"
```

---

## Task 2: Pure helpers (`try_claim`, `release_for_task`, `claims_for_session`)

**Files:**
- Create: `claw_forge/state/file_claims.py`
- Test: `tests/state/test_file_claims.py`

These helpers contain the SQL logic.  Keeping them out of `service.py` lets us unit-test the atomic claim semantics without spinning up FastAPI.

- [ ] **Step 1: Write the failing test**

Create `tests/state/test_file_claims.py`:

```python
"""Tests for the file-claim helpers."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from claw_forge.state.file_claims import (
    claims_for_session, release_for_task, try_claim,
)
from claw_forge.state.models import Base, Session, Task


@pytest.fixture()
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Maker() as session:
        yield session
    await engine.dispose()


@pytest.fixture()
async def session_with_two_tasks(db: AsyncSession) -> tuple[str, str, str]:
    sess = Session(project_path="/tmp/x")
    db.add(sess); await db.flush()
    t1 = Task(session_id=sess.id, plugin_name="coding")
    t2 = Task(session_id=sess.id, plugin_name="coding")
    db.add_all([t1, t2]); await db.commit()
    return sess.id, t1.id, t2.id


@pytest.mark.asyncio
async def test_try_claim_succeeds_when_no_conflict(
    db, session_with_two_tasks
) -> None:
    sess_id, t1, _ = session_with_two_tasks
    result = await try_claim(db, sess_id, t1, ["a.py", "b.py"])
    assert result["claimed"] is True
    assert result["conflicts"] == []
    rows = await claims_for_session(db, sess_id)
    assert sorted(r.file_path for r in rows) == ["a.py", "b.py"]


@pytest.mark.asyncio
async def test_try_claim_fails_atomically_on_conflict(
    db, session_with_two_tasks
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
    db, session_with_two_tasks
) -> None:
    sess_id, t1, _ = session_with_two_tasks
    await try_claim(db, sess_id, t1, ["a.py", "b.py", "c.py"])
    n = await release_for_task(db, t1)
    assert n == 3
    rows = await claims_for_session(db, sess_id)
    assert rows == []


@pytest.mark.asyncio
async def test_release_for_task_idempotent(db, session_with_two_tasks) -> None:
    sess_id, t1, _ = session_with_two_tasks
    await try_claim(db, sess_id, t1, ["a.py"])
    assert await release_for_task(db, t1) == 1
    assert await release_for_task(db, t1) == 0  # second call is a no-op


@pytest.mark.asyncio
async def test_try_claim_idempotent_for_same_task(
    db, session_with_two_tasks
) -> None:
    """A task re-claiming files it already holds is a no-op success."""
    sess_id, t1, _ = session_with_two_tasks
    await try_claim(db, sess_id, t1, ["a.py"])
    result = await try_claim(db, sess_id, t1, ["a.py", "b.py"])
    assert result["claimed"] is True
    assert result["conflicts"] == []
    rows = await claims_for_session(db, sess_id)
    assert sorted(r.file_path for r in rows) == ["a.py", "b.py"]
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest tests/state/test_file_claims.py -v
```

Expected: ImportError — `claw_forge.state.file_claims` does not exist.

- [ ] **Step 3: Implement the helpers**

Create `claw_forge/state/file_claims.py`:

```python
"""Pure helpers for file-claim CRUD.

Kept out of ``service.py`` so the atomic-claim semantics can be unit-tested
without spinning up FastAPI.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from claw_forge.state.models import FileClaim


async def try_claim(
    db: AsyncSession, session_id: str, task_id: str, file_paths: list[str],
) -> dict[str, Any]:
    """Claim *file_paths* for *task_id* in *session_id*, atomically.

    Returns ``{"claimed": True, "conflicts": []}`` on success.  Returns
    ``{"claimed": False, "conflicts": [<paths held by other tasks>]}`` on
    conflict; no partial claims are committed in that case.

    Idempotent for the same task: re-claiming a path the same task already
    holds is a no-op success.
    """
    # Find which of the requested paths are held by another task in this session.
    existing_q = await db.execute(
        select(FileClaim.file_path, FileClaim.task_id).where(
            FileClaim.session_id == session_id,
            FileClaim.file_path.in_(file_paths),
        )
    )
    existing = {row.file_path: row.task_id for row in existing_q}
    conflicts = [p for p, holder in existing.items() if holder != task_id]
    if conflicts:
        return {"claimed": False, "conflicts": sorted(conflicts)}
    # Build only the new claims (skip ones already held by *this* task).
    new_paths = [p for p in file_paths if p not in existing]
    db.add_all([
        FileClaim(session_id=session_id, task_id=task_id, file_path=p)
        for p in new_paths
    ])
    await db.commit()
    return {"claimed": True, "conflicts": []}


async def release_for_task(db: AsyncSession, task_id: str) -> int:
    """Drop all claims held by *task_id*.  Returns the number of rows deleted."""
    result = await db.execute(
        delete(FileClaim).where(FileClaim.task_id == task_id)
    )
    await db.commit()
    return result.rowcount or 0


async def claims_for_session(
    db: AsyncSession, session_id: str,
) -> list[FileClaim]:
    """Return all live claims for *session_id*, ordered by claimed_at."""
    q = await db.execute(
        select(FileClaim)
        .where(FileClaim.session_id == session_id)
        .order_by(FileClaim.claimed_at)
    )
    return list(q.scalars().all())
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/state/test_file_claims.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/state/file_claims.py tests/state/test_file_claims.py
git commit -m "feat(state): add try_claim/release/list helpers for file claims"
```

---

## Task 3: Service endpoints — POST claim / DELETE release / GET list

**Files:**
- Modify: `claw_forge/state/service.py`
- Test: `tests/state/test_service_file_claims.py`

- [ ] **Step 1: Write the failing test**

Create `tests/state/test_service_file_claims.py`:

```python
"""Tests for the file-claims HTTP API."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from claw_forge.state.service import StateService


@pytest.fixture()
async def svc(tmp_path):
    s = StateService(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/state.db",
        project_path=str(tmp_path),
    )
    await s.startup()
    yield s
    await s.shutdown()


async def _create_session_and_tasks(cl: AsyncClient, project: str) -> tuple[str, str, str]:
    r = await cl.post("/sessions", json={"project_path": project})
    sid = r.json()["id"]
    r = await cl.post(f"/sessions/{sid}/tasks", json={"plugin_name": "coding"})
    t1 = r.json()["id"]
    r = await cl.post(f"/sessions/{sid}/tasks", json={"plugin_name": "coding"})
    t2 = r.json()["id"]
    return sid, t1, t2


@pytest.mark.asyncio
async def test_post_file_claim_succeeds_and_returns_claimed_paths(svc, tmp_path) -> None:
    async with AsyncClient(transport=ASGITransport(app=svc.app),
                           base_url="http://test") as cl:
        sid, t1, _ = await _create_session_and_tasks(cl, str(tmp_path))
        r = await cl.post(
            f"/sessions/{sid}/file-claims",
            json={"task_id": t1, "file_paths": ["a.py", "b.py"]},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["claimed"] is True
        assert body["conflicts"] == []


@pytest.mark.asyncio
async def test_post_file_claim_returns_409_on_conflict(svc, tmp_path) -> None:
    async with AsyncClient(transport=ASGITransport(app=svc.app),
                           base_url="http://test") as cl:
        sid, t1, t2 = await _create_session_and_tasks(cl, str(tmp_path))
        await cl.post(
            f"/sessions/{sid}/file-claims",
            json={"task_id": t1, "file_paths": ["a.py"]},
        )
        r = await cl.post(
            f"/sessions/{sid}/file-claims",
            json={"task_id": t2, "file_paths": ["a.py", "b.py"]},
        )
        assert r.status_code == 409
        body = r.json()
        assert body["claimed"] is False
        assert body["conflicts"] == ["a.py"]


@pytest.mark.asyncio
async def test_delete_file_claims_releases_task(svc, tmp_path) -> None:
    async with AsyncClient(transport=ASGITransport(app=svc.app),
                           base_url="http://test") as cl:
        sid, t1, _ = await _create_session_and_tasks(cl, str(tmp_path))
        await cl.post(
            f"/sessions/{sid}/file-claims",
            json={"task_id": t1, "file_paths": ["a.py", "b.py"]},
        )
        r = await cl.delete(f"/sessions/{sid}/file-claims/{t1}")
        assert r.status_code == 200
        assert r.json()["released"] == 2
        r = await cl.get(f"/sessions/{sid}/file-claims")
        assert r.json()["claims"] == []


@pytest.mark.asyncio
async def test_get_file_claims_lists_current(svc, tmp_path) -> None:
    async with AsyncClient(transport=ASGITransport(app=svc.app),
                           base_url="http://test") as cl:
        sid, t1, t2 = await _create_session_and_tasks(cl, str(tmp_path))
        await cl.post(
            f"/sessions/{sid}/file-claims",
            json={"task_id": t1, "file_paths": ["a.py"]},
        )
        await cl.post(
            f"/sessions/{sid}/file-claims",
            json={"task_id": t2, "file_paths": ["b.py"]},
        )
        r = await cl.get(f"/sessions/{sid}/file-claims")
        assert r.status_code == 200
        rows = r.json()["claims"]
        assert sorted((c["task_id"], c["file_path"]) for c in rows) == [
            (t1, "a.py"), (t2, "b.py"),
        ]
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest tests/state/test_service_file_claims.py -v
```

Expected: 404s — endpoints don't exist.

- [ ] **Step 3: Add request models in `service.py`**

Near the existing pydantic request models (search `class UpdateTaskRequest` to find the cluster):

```python
class FileClaimRequest(BaseModel):
    task_id: str
    file_paths: list[str]
```

- [ ] **Step 4: Add three endpoints**

Find a good insertion point — e.g. after the existing `update_task` endpoint.  Add:

```python
        @app.post("/sessions/{session_id}/file-claims")
        async def post_file_claim(
            session_id: str, req: FileClaimRequest,
        ) -> dict[str, Any]:
            from claw_forge.state.file_claims import try_claim
            async with self._session_factory() as db:
                result = await try_claim(
                    db, session_id, req.task_id, req.file_paths,
                )
            if not result["claimed"]:
                # 409 Conflict so callers can branch on status code.
                from fastapi.responses import JSONResponse
                return JSONResponse(status_code=409, content=result)
            return result

        @app.delete("/sessions/{session_id}/file-claims/{task_id}")
        async def delete_file_claims(
            session_id: str, task_id: str,
        ) -> dict[str, Any]:
            from claw_forge.state.file_claims import release_for_task
            async with self._session_factory() as db:
                n = await release_for_task(db, task_id)
            return {"released": n}

        @app.get("/sessions/{session_id}/file-claims")
        async def get_file_claims(session_id: str) -> dict[str, Any]:
            from claw_forge.state.file_claims import claims_for_session
            async with self._session_factory() as db:
                rows = await claims_for_session(db, session_id)
            return {
                "claims": [
                    {
                        "task_id": r.task_id,
                        "file_path": r.file_path,
                        "claimed_at": r.claimed_at.isoformat(),
                    }
                    for r in rows
                ]
            }
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/state/test_service_file_claims.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add claw_forge/state/service.py tests/state/test_service_file_claims.py
git commit -m "feat(state): add file-claims POST/DELETE/GET endpoints"
```

---

## Task 4: Auto-release on task status transitions

**Files:**
- Modify: `claw_forge/state/service.py` (the existing `update_task` PATCH handler)
- Test: `tests/state/test_service_file_claims.py`

When a task transitions to `completed`, `failed`, or `paused`, any claims it holds become stale.  Auto-release them so a forgotten release can't deadlock the next dispatch wave.

- [ ] **Step 1: Write the failing test**

Append to `tests/state/test_service_file_claims.py`:

```python
@pytest.mark.asyncio
async def test_patch_task_status_completed_releases_claims(svc, tmp_path) -> None:
    async with AsyncClient(transport=ASGITransport(app=svc.app),
                           base_url="http://test") as cl:
        sid, t1, _ = await _create_session_and_tasks(cl, str(tmp_path))
        await cl.post(
            f"/sessions/{sid}/file-claims",
            json={"task_id": t1, "file_paths": ["a.py"]},
        )
        await cl.patch(f"/tasks/{t1}", json={"status": "completed"})
        r = await cl.get(f"/sessions/{sid}/file-claims")
        assert r.json()["claims"] == []


@pytest.mark.asyncio
async def test_patch_task_status_failed_releases_claims(svc, tmp_path) -> None:
    async with AsyncClient(transport=ASGITransport(app=svc.app),
                           base_url="http://test") as cl:
        sid, t1, _ = await _create_session_and_tasks(cl, str(tmp_path))
        await cl.post(
            f"/sessions/{sid}/file-claims",
            json={"task_id": t1, "file_paths": ["a.py"]},
        )
        await cl.patch(f"/tasks/{t1}", json={"status": "failed"})
        r = await cl.get(f"/sessions/{sid}/file-claims")
        assert r.json()["claims"] == []


@pytest.mark.asyncio
async def test_patch_task_status_running_does_not_release_claims(svc, tmp_path) -> None:
    """Status flip to running keeps claims held."""
    async with AsyncClient(transport=ASGITransport(app=svc.app),
                           base_url="http://test") as cl:
        sid, t1, _ = await _create_session_and_tasks(cl, str(tmp_path))
        await cl.post(
            f"/sessions/{sid}/file-claims",
            json={"task_id": t1, "file_paths": ["a.py"]},
        )
        await cl.patch(f"/tasks/{t1}", json={"status": "running"})
        r = await cl.get(f"/sessions/{sid}/file-claims")
        assert len(r.json()["claims"]) == 1
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest tests/state/test_service_file_claims.py -v -k 'releases_claims or does_not_release'
```

Expected: at least the auto-release tests fail; the running-keeps-claims test passes (already the case today).

- [ ] **Step 3: Hook auto-release into the PATCH handler**

In `claw_forge/state/service.py`, in `async def update_task`, immediately after the existing block that sets `task.completed_at = datetime.now(UTC)` (search for `task.completed_at`):

```python
                    elif _normalized in ("completed", "failed"):
                        task.completed_at = datetime.now(UTC)
                        # NEW: auto-release file claims when task transitions
                        # to a terminal state.  Pause is also terminal-ish for
                        # claim purposes — paused tasks aren't running.
                        from claw_forge.state.file_claims import release_for_task
                        await release_for_task(db, task_id)
                        if _normalized == "completed" and self._reviewer is not None:
                            self._reviewer.notify_feature_completed(...)
                    elif _normalized == "paused":
                        from claw_forge.state.file_claims import release_for_task
                        await release_for_task(db, task_id)
```

(The exact placement: read the current branch tree carefully and add the `paused` `elif` if it doesn't exist; otherwise add the `release_for_task` call inside the existing branch.)

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/state/test_service_file_claims.py -v
```

Expected: PASS for all three.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/state/service.py tests/state/test_service_file_claims.py
git commit -m "feat(state): auto-release file claims on task terminal status"
```

---

## Task 5: Task creation accepts `touches_files`

**Files:**
- Modify: `claw_forge/state/service.py` (`CreateTaskRequest` + the task-creation handler)
- Test: `tests/state/test_service_file_claims.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/state/test_service_file_claims.py`:

```python
@pytest.mark.asyncio
async def test_create_task_with_touches_files_persists_field(svc, tmp_path) -> None:
    async with AsyncClient(transport=ASGITransport(app=svc.app),
                           base_url="http://test") as cl:
        r = await cl.post("/sessions", json={"project_path": str(tmp_path)})
        sid = r.json()["id"]
        r = await cl.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "coding", "touches_files": ["x.py", "y.py"]},
        )
        tid = r.json()["id"]
        r = await cl.get(f"/tasks/{tid}")
        assert r.json()["touches_files"] == ["x.py", "y.py"]


@pytest.mark.asyncio
async def test_create_task_without_touches_files_defaults_empty(svc, tmp_path) -> None:
    async with AsyncClient(transport=ASGITransport(app=svc.app),
                           base_url="http://test") as cl:
        r = await cl.post("/sessions", json={"project_path": str(tmp_path)})
        sid = r.json()["id"]
        r = await cl.post(f"/sessions/{sid}/tasks", json={"plugin_name": "coding"})
        tid = r.json()["id"]
        r = await cl.get(f"/tasks/{tid}")
        assert r.json()["touches_files"] == []
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest tests/state/test_service_file_claims.py -v -k touches_files
```

Expected: FAIL — the field is unknown to `CreateTaskRequest` and the GET response doesn't include it.

- [ ] **Step 3: Add the field**

In `claw_forge/state/service.py`, find `class CreateTaskRequest(BaseModel):` and add:

```python
class CreateTaskRequest(BaseModel):
    plugin_name: str
    description: str | None = None
    priority: int = 0
    depends_on: list[str] = []
    category: str | None = None
    steps: list[str] = []
    parent_task_id: str | None = None
    touches_files: list[str] = []  # NEW
```

In the create-task handler, persist the field:

```python
                task = Task(
                    session_id=session_id,
                    plugin_name=req.plugin_name,
                    description=req.description,
                    priority=req.priority,
                    depends_on=req.depends_on,
                    category=req.category,
                    steps=req.steps,
                    parent_task_id=req.parent_task_id,
                    touches_files=req.touches_files,  # NEW
                )
```

In every Task→dict serializer (search `task.description` for the locations), add `"touches_files": task.touches_files or []`.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/state/test_service_file_claims.py -v -k touches_files
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/state/service.py tests/state/test_service_file_claims.py
git commit -m "feat(state): CreateTaskRequest accepts touches_files"
```

---

## Task 6: Dispatcher claims files before starting an agent

**Files:**
- Modify: `claw_forge/cli.py` (the task_handler around lines 970-1385)
- Test: `tests/test_cli_file_claims.py`

The dispatcher must:
1. Before calling `_patch_task(status="running")`, attempt `POST /file-claims`.
2. If 409 — log, leave the task as `pending`, and return so the next dispatch cycle can retry.
3. If 200 — proceed to run the agent normally.
4. On task completion (success or failure), the auto-release in Task 4 already covers cleanup; we don't need explicit DELETE here.  However we should issue an explicit DELETE in the cancellation/finally path as a belt-and-braces safety net.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_file_claims.py`:

```python
"""Test the dispatcher's file-claim logic via the helper functions."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from claw_forge.cli import _try_claim_files


@pytest.mark.asyncio
async def test_try_claim_files_returns_true_on_200() -> None:
    http = MagicMock()
    response = MagicMock(status_code=200)
    response.json.return_value = {"claimed": True, "conflicts": []}
    http.post = AsyncMock(return_value=response)
    ok, conflicts = await _try_claim_files(
        http, "http://localhost:8420", "sess-1", "task-1", ["a.py"],
    )
    assert ok is True
    assert conflicts == []
    http.post.assert_called_once()


@pytest.mark.asyncio
async def test_try_claim_files_returns_false_on_409() -> None:
    http = MagicMock()
    response = MagicMock(status_code=409)
    response.json.return_value = {"claimed": False, "conflicts": ["a.py"]}
    http.post = AsyncMock(return_value=response)
    ok, conflicts = await _try_claim_files(
        http, "http://localhost:8420", "sess-1", "task-1", ["a.py"],
    )
    assert ok is False
    assert conflicts == ["a.py"]


@pytest.mark.asyncio
async def test_try_claim_files_short_circuits_when_empty_list() -> None:
    """No POST is issued when the task declares no files."""
    http = MagicMock()
    http.post = AsyncMock()
    ok, conflicts = await _try_claim_files(
        http, "http://x", "sess-1", "task-1", [],
    )
    assert ok is True
    assert conflicts == []
    http.post.assert_not_called()
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest tests/test_cli_file_claims.py -v
```

Expected: ImportError — `_try_claim_files` doesn't exist.

- [ ] **Step 3: Add `_try_claim_files` helper to `cli.py`**

In `claw_forge/cli.py`, near other private helpers:

```python
async def _try_claim_files(
    http: Any, state_base: str, session_id: str, task_id: str,
    file_paths: list[str],
) -> tuple[bool, list[str]]:
    """POST /file-claims for *task_id*; return (ok, conflicts).

    Empty *file_paths* short-circuits to (True, []) — tasks that don't
    declare files participate in no locking.
    """
    if not file_paths:
        return True, []
    import httpx
    try:
        r = await http.post(
            f"{state_base}/sessions/{session_id}/file-claims",
            json={"task_id": task_id, "file_paths": list(file_paths)},
        )
    except httpx.HTTPError:
        # State service unavailable — treat as success (don't block dispatch
        # on transient state-service errors).
        return True, []
    if r.status_code == 200:
        return True, []
    if r.status_code == 409:
        return False, list(r.json().get("conflicts", []))
    # Any other status — log-then-allow; don't block on unexpected codes.
    return True, []
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_cli_file_claims.py -v
```

Expected: PASS.

- [ ] **Step 5: Wire into the dispatcher**

In `claw_forge/cli.py`, in the task_handler, immediately before the existing `await _patch_task(http, task_node.id, status="running")` call, insert:

```python
                # File-claim guard: defer this task if any file it declares
                # is already held by another running task.  Tasks without
                # touches_files declared participate in no locking.
                touches = list(getattr(task_node, "touches_files", []) or [])
                ok, conflicts = await _try_claim_files(
                    http, _state_base, session_id, task_node.id, touches,
                )
                if not ok:
                    import logging as _logging
                    _logging.getLogger(__name__).info(
                        "Task %s deferred — files claimed by another task: %s",
                        task_node.id, conflicts,
                    )
                    return {"success": False, "output": "deferred"}
```

- [ ] **Step 6: Add `touches_files` to TaskNode**

In `claw_forge/state/scheduler.py`:

```python
@dataclass
class TaskNode:
    ...
    touches_files: list[str] = field(default_factory=list)
```

And update `_task_dict_to_node` (added in the merge-gating plan; if that helper doesn't exist yet because plans are executed in a different order, add `touches_files` to whatever DB→TaskNode mapping currently lives in `cli.py`):

```python
        touches_files=list(payload.get("touches_files", []) or []),
```

- [ ] **Step 7: Full regression sweep**

```bash
uv run pytest tests/ -q -x
```

Expected: all green.  If anything in `test_cli_commands.py` regresses, the most likely cause is the new "return early when conflicts" branch — verify the test fixtures don't pre-create conflicting claims.

- [ ] **Step 8: Commit**

```bash
git add claw_forge/cli.py claw_forge/state/scheduler.py tests/test_cli_file_claims.py
git commit -m "feat(cli): dispatcher claims files before starting agents"
```

---

## Task 7: Documentation

This plan adds three new state-service endpoints (`POST/DELETE/GET /sessions/{id}/file-claims`) and a new `touches_files` JSON field on the task creation payload. Per project convention, public-surface additions update CLAUDE.md before landing.

**Files:**
- Modify: `CLAUDE.md` (root) — the State Service API section + a short architectural note

- [ ] **Step 1: Update CLAUDE.md "State Service API" section**

Find the `### State Service API` heading. Add three new bullets to the endpoint list (placement: right before `WebSocket /ws`):

```markdown
- `POST /sessions/{id}/file-claims` — atomic file-lock claim for a task; returns 200 on success or 409 with conflict list
- `DELETE /sessions/{id}/file-claims/{task_id}` — release all claims held by a task
- `GET /sessions/{id}/file-claims` — list current claims (for debugging)
```

Also update the existing `POST /sessions/{id}/tasks` bullet to mention the new optional field:

```
- `POST /sessions/{id}/tasks` (accepts optional `touches_files: list[str]` for file-lock declaration), `PATCH /sessions/{id}/tasks/{id}` (status, cost, tokens, merged_to_main)
```

- [ ] **Step 2: Add an architectural note under "Key Conventions"**

Append to the bottom of the `## Key Conventions` section:

```markdown
- **File-claim locks** (`touches_files` on tasks): a task may declare a list of files it intends to edit. Before starting an agent, the dispatcher POSTs a claim to `/file-claims`; if any file is held by another running task, the dispatcher defers this task to the next dispatch cycle. Claims auto-release on task transition to `completed`/`failed`/`paused`. Tasks that don't declare `touches_files` participate in no locking — full backward compatibility.
```

- [ ] **Step 3: Verify with a quick read**

```bash
/usr/bin/grep -B1 -A1 "file-claims" /Users/bowenli/development/claw-forge/.worktrees/merge-gating-and-file-locks/CLAUDE.md
/usr/bin/grep -A3 "File-claim locks" /Users/bowenli/development/claw-forge/.worktrees/merge-gating-and-file-locks/CLAUDE.md
```

Both should match the inserted content.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): document file-claim locks + endpoints + touches_files"
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

- [ ] **Step 4: Smoke-test the API end-to-end**

```bash
uv run python - <<'PY'
import asyncio
from httpx import AsyncClient, ASGITransport
from claw_forge.state.service import StateService

async def main():
    s = StateService(database_url="sqlite+aiosqlite:///:memory:",
                     project_path="/tmp")
    await s.startup()
    try:
        async with AsyncClient(transport=ASGITransport(app=s.app),
                               base_url="http://t") as cl:
            r = await cl.post("/sessions", json={"project_path": "/tmp"})
            sid = r.json()["id"]
            r = await cl.post(f"/sessions/{sid}/tasks",
                              json={"plugin_name": "coding"})
            t1 = r.json()["id"]
            r = await cl.post(f"/sessions/{sid}/tasks",
                              json={"plugin_name": "coding"})
            t2 = r.json()["id"]
            print("claim1:", (await cl.post(
                f"/sessions/{sid}/file-claims",
                json={"task_id": t1, "file_paths": ["x.py"]})).json())
            print("claim2 (conflict):", (await cl.post(
                f"/sessions/{sid}/file-claims",
                json={"task_id": t2, "file_paths": ["x.py"]})).status_code)
            await cl.patch(f"/tasks/{t1}", json={"status": "completed"})
            print("after release:", (await cl.post(
                f"/sessions/{sid}/file-claims",
                json={"task_id": t2, "file_paths": ["x.py"]})).json())
    finally:
        await s.shutdown()

asyncio.run(main())
PY
```

Expected output (approximately):
```
claim1: {'claimed': True, 'conflicts': []}
claim2 (conflict): 409
after release: {'claimed': True, 'conflicts': []}
```

- [ ] **Step 5: No commit needed if all clean**

Otherwise commit any final fixes.

---

## Self-Review

**Spec coverage:**
- ✅ `FileClaim` ORM table + `Task.touches_files` (Task 1)
- ✅ Pure helpers with atomic-claim semantics (Task 2)
- ✅ HTTP endpoints for claim/release/list (Task 3)
- ✅ Auto-release on terminal status transitions (Task 4)
- ✅ Task creation accepts `touches_files` (Task 5)
- ✅ Dispatcher gates start on successful claim (Task 6)
- ✅ Lint / types / coverage / smoke (Task 7)

**Placeholder scan:** none — every step has the actual code or command.

**Type consistency:** `touches_files: list[str]` consistent across `Task` (SafeJSON column), `CreateTaskRequest` (Pydantic), `TaskNode` (dataclass), and the JSON wire format.  `FileClaim.file_path: str` is a single literal path; we deliberately do NOT support glob patterns in v1 to keep semantics simple.

**Notes for the implementer:**
- Task 2's `try_claim` is intentionally `O(n)` per call.  At expected scale (≤ 10 concurrent tasks × ≤ 50 files each) this is fine.  If contention proves a bottleneck later, add an INDEX on `(session_id, file_path)`.
- Task 6's "deferred" return value (`{"success": False, "output": "deferred"}`) does NOT mark the task as failed — the calling code in the dispatcher already treats `success=False` as "retry next cycle" via the surrounding retry loop.  Verify by reading the dispatcher's outer loop: a `deferred` task should remain `status="pending"` in the DB so the next `get_ready_tasks()` call picks it up.  If the existing dispatcher PATCHes `status="failed"` on `success=False`, add a guard around that PATCH that skips it when `output == "deferred"`.
- This plan is independent of the merge-gating plan — they share no code.  Either can ship first.
