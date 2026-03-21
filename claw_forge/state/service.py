"""FastAPI AgentStateService with SSE and WebSocket support."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from claw_forge.orchestrator.reviewer import ParallelReviewer

import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import event, select, text
from sqlalchemy.exc import DatabaseError as SADatabaseError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from claw_forge.commands.registry import COMMAND_IDS, COMMAND_SHELLS, COMMANDS
from claw_forge.pool.manager import ProviderPoolManager
from claw_forge.state.models import Base, Event, Session, Task


def _task_summary(task: Task) -> dict[str, Any]:
    """Serialise core Task fields shared by multiple endpoints."""
    return {
        "id": task.id,
        "plugin_name": task.plugin_name,
        "description": task.description,
        "category": task.category,
        "status": task.status,
        "priority": task.priority,
        "depends_on": task.depends_on,
        "steps": task.steps or [],
        "active_subagents": task.active_subagents,
    }

logger = logging.getLogger(__name__)


def create_app_from_env() -> FastAPI:
    """App factory for ``uvicorn --reload``.

    Reads configuration from environment variables so uvicorn can re-import
    and reconstruct the app on every file change::

        CLAW_FORGE_DB_URL   – SQLAlchemy async database URL
                              (default: sqlite+aiosqlite:///./state.db)
    """
    import os

    db_url = os.environ.get(
        "CLAW_FORGE_DB_URL", "sqlite+aiosqlite:///./state.db"
    )
    project_path_str = os.environ.get("CLAW_FORGE_PROJECT_PATH")
    project_path = Path(project_path_str) if project_path_str else None
    svc = AgentStateService(
        database_url=db_url, project_path=project_path,
    )
    return svc.create_app()


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts structured events.

    All broadcast methods are fire-and-forget with graceful handling of
    disconnected clients — stale connections are pruned automatically.

    Event types emitted::

        {"type": "feature_update",  "feature": {...}}
        {"type": "pool_update",     "providers": [...]}
        {"type": "agent_started",   "session_id": "...", "feature_id": 42}
        {"type": "agent_completed", "session_id": "...", "feature_id": 42, "passed": True}
        {"type": "cost_update",     "total_cost": 1.23, "session_cost": 0.05}
    """

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    @property
    def active_count(self) -> int:
        """Number of currently connected WebSocket clients."""
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        self._connections.append(websocket)
        logger.debug("WS client connected; total=%d", self.active_count)

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection (safe to call even if not present)."""
        with suppress(ValueError):
            self._connections.remove(websocket)
        logger.debug("WS client disconnected; total=%d", self.active_count)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        """Send *payload* as JSON to all connected clients.

        Connections that raise any error are removed from the pool.
        """
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    # ── Typed broadcast helpers ──────────────────────────────────────────────

    async def broadcast_feature_update(self, feature: dict[str, Any]) -> None:
        """Broadcast a feature state change to all connected Kanban UIs."""
        await self.broadcast({"type": "feature_update", "feature": feature})

    async def broadcast_pool_update(self, providers: list[dict[str, Any]]) -> None:
        """Broadcast provider pool health to all connected Kanban UIs."""
        await self.broadcast({"type": "pool_update", "providers": providers})

    async def broadcast_agent_started(self, session_id: str, feature_id: int | str) -> None:
        """Broadcast that an agent session has started working on a feature."""
        await self.broadcast(
            {"type": "agent_started", "session_id": session_id, "feature_id": feature_id}
        )

    async def broadcast_agent_completed(
        self, session_id: str, feature_id: int | str, *, passed: bool
    ) -> None:
        """Broadcast that an agent session has finished a feature."""
        await self.broadcast(
            {
                "type": "agent_completed",
                "session_id": session_id,
                "feature_id": feature_id,
                "passed": passed,
            }
        )

    async def broadcast_agent_log(
        self,
        task_id: str,
        task_name: str,
        role: str,
        content: str,
        level: str = "info",
        model: str | None = None,
    ) -> None:
        """Broadcast an agent streaming log entry to all connected Kanban UIs."""
        await self.broadcast(
            {
                "type": "agent_log",
                "task_id": task_id,
                "task_name": task_name,
                "role": role,
                "content": content,
                "level": level,
                "model": model,
            }
        )

    async def broadcast_cost_update(
        self, total_cost: float, session_cost: float
    ) -> None:
        """Broadcast an updated cost snapshot."""
        await self.broadcast(
            {"type": "cost_update", "total_cost": total_cost, "session_cost": session_cost}
        )


class CreateSessionRequest(BaseModel):
    project_path: str
    manifest: dict[str, Any] | None = None


class CreateTaskRequest(BaseModel):
    plugin_name: str
    description: str | None = None
    priority: int = 0
    depends_on: list[str] = []
    category: str | None = None
    steps: list[str] = []


class SessionInitRequest(BaseModel):
    project_path: str


class UpdateTaskRequest(BaseModel):
    status: str | None = None
    result: dict[str, Any] | None = None
    error_message: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    active_subagents: int | None = None


class HumanInputRequest(BaseModel):
    """Request for human input — moves the feature to 'needs_human' status."""

    question: str


class HumanAnswerRequest(BaseModel):
    """Answer to a pending human input request — moves feature back to 'pending'."""

    answer: str


class ExecuteCommandRequest(BaseModel):
    """Request to execute a command from the command palette."""

    command: str
    args: dict[str, Any] = {}
    project_dir: str = "."


class AgentLogRequest(BaseModel):
    """Agent streaming log entry — tool use, assistant text, or result."""

    role: str  # "assistant" | "tool_use" | "tool_result" | "result" | "error"
    content: str
    task_name: str | None = None
    level: str = "info"  # "info" | "warning" | "error"
    model: str | None = None  # LLM model identifier used for this task


class ToggleProviderRequest(BaseModel):
    """Request to enable or disable a provider at runtime."""

    enabled: bool


class SetProviderModelsRequest(BaseModel):
    """Request to update the active tier list for a provider."""

    active_tiers: list[str]


class AgentStateService:
    """REST + SSE + WebSocket state service for orchestrating agents."""

    def __init__(
        self,
        database_url: str = "sqlite+aiosqlite:///claw_forge.db",
        pool_manager: ProviderPoolManager | None = None,
        project_path: Path | None = None,
    ) -> None:
        from claw_forge.state.backend import is_sqlite

        self._is_sqlite = is_sqlite(database_url)
        self._database_url = database_url
        self._explicit_project_path = project_path

        # PostgreSQL benefits from connection pooling; SQLite does not.
        engine_kwargs: dict[str, Any] = {}
        if not self._is_sqlite:
            engine_kwargs = {
                "pool_size": 10,
                "max_overflow": 20,
                "pool_pre_ping": True,
            }
        self._engine = create_async_engine(
            database_url, echo=False, **engine_kwargs,
        )

        # ── SQLite-specific: file path extraction + pragmas + atexit ──
        self._db_file_path: str | None = None
        if self._is_sqlite:
            try:
                url_str = str(self._engine.url)
                if "///" in url_str:
                    raw = url_str.split("///", 1)[-1]
                    if raw and raw.startswith("/") and not raw.startswith(":"):
                        self._db_file_path = raw
            except Exception:  # noqa: BLE001
                pass

            @event.listens_for(self._engine.sync_engine, "connect")
            def _set_sqlite_pragmas(dbapi_conn: Any, _rec: Any) -> None:
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=FULL")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.close()

            # Last-resort WAL checkpoint: runs on normal interpreter exit
            # (KeyboardInterrupt, SIGTERM) even if the async lifespan
            # teardown is skipped by uvicorn's --reload supervisor.
            import atexit
            import sqlite3

            db_file = self._db_file_path

            def _sync_wal_checkpoint() -> None:
                if not db_file:
                    return
                try:
                    conn = sqlite3.connect(db_file)
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass

            atexit.register(_sync_wal_checkpoint)

        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        self._event_queues: list[asyncio.Queue[dict[str, Any]]] = []
        self._ws_clients: list[WebSocket] = []
        # Kanban UI real-time broadcast manager
        self.ws_manager: ConnectionManager = ConnectionManager()
        # Regression reviewer reference (set by dispatcher)
        self._reviewer: ParallelReviewer | None = None
        # Command execution store: {execution_id: {...}}
        self._executions: dict[str, dict[str, Any]] = {}
        # Provider pool manager (optional, used by toggle endpoints)
        self._pool_manager: ProviderPoolManager | None = pool_manager
        # In-memory set of task IDs requested to stop; polled and cleared by dispatcher
        self._stop_requested: set[str] = set()
        # Pause/resume signals for the dispatcher (cleared atomically on each poll)
        self._pause_requested: bool = False
        self._resume_requested: bool = False
        # Per-task resume requests; polled and cleared by dispatcher
        self._resume_task_requested: set[str] = set()
        # Task IDs currently paused via stop-all; agent logs for these are suppressed
        self._paused_task_ids: set[str] = set()
        # Derive project root: use explicit path if given (required for
        # PostgreSQL where the DB URL doesn't encode the project directory),
        # otherwise infer from the SQLite file path.
        if self._explicit_project_path is not None:
            self._project_path: Path | None = self._explicit_project_path
        else:
            _db = self._db_path()
            self._project_path = (
                _db.resolve().parent.parent if _db is not None else None
            )

    def _db_path(self) -> Path | None:
        """Extract the filesystem path from the engine's SQLite URL."""
        url_str = str(self._engine.url)
        if "sqlite" not in url_str:
            return None
        # URL form: sqlite+aiosqlite:////abs/path or sqlite+aiosqlite:///rel
        raw = url_str.split("///")[-1]
        if not raw or raw.startswith(":"):
            return None
        return Path(raw)

    def _find_config_path(self) -> Path | None:
        """Search project dir, then CWD, then up to 3 parent dirs for claw-forge.yaml."""
        # Prefer the project directory the service was started for
        if self._project_path is not None:
            p = self._project_path / "claw-forge.yaml"
            if p.exists():
                return p
        # Fallback: walk up from CWD
        candidate = Path.cwd()
        for _ in range(4):
            p = candidate / "claw-forge.yaml"
            if p.exists():
                return p
            candidate = candidate.parent
        return None

    @staticmethod
    def _persist_provider_enabled(config_path: Path, provider_name: str, enabled: bool) -> None:
        """Read claw-forge.yaml, set providers.<name>.enabled, write back atomically."""
        text = config_path.read_text()
        data = yaml.safe_load(text)

        if "providers" not in data:
            raise ValueError("No providers section in config")
        if provider_name not in data["providers"]:
            raise ValueError(f"Provider {provider_name!r} not in config")

        data["providers"][provider_name]["enabled"] = enabled

        tmp = config_path.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
        tmp.rename(config_path)

    async def init_db(self) -> None:
        try:
            await self._init_db_inner()
        except SADatabaseError as exc:
            if "malformed" not in str(exc) and "corrupt" not in str(exc).lower():
                raise
            db_path = self._db_path()
            if db_path is None:
                raise
            await self._recover_corrupt_db(db_path)

    async def _recover_corrupt_db(self, db_path: Path) -> None:
        """Attempt tiered recovery of a corrupt SQLite database.

        Level 1: Remove only the WAL/SHM sidecar files.  The main DB file
                 contains all checkpointed data — only uncommitted WAL
                 frames are lost.  This preserves completed task state.
        Level 2: Use ``sqlite3 .recover`` to salvage rows from the corrupt
                 DB into a fresh copy, then swap it in.
        Level 3: If both fail, raise so the operator can decide.
        """
        import shutil
        import subprocess

        # ── Level 1: drop WAL/SHM, keep main DB ─────────────────────────
        logger.warning(
            "Database corruption detected — attempting WAL-only recovery "
            "for %s",
            db_path,
        )
        for suffix in ("-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
        await self._engine.dispose()
        try:
            await self._init_db_inner()
            logger.info("Recovery succeeded (dropped WAL/SHM sidecar files)")
            return
        except SADatabaseError:
            logger.warning("WAL-only recovery failed — trying sqlite3 .recover")

        # ── Level 2: sqlite3 .recover ────────────────────────────────────
        recovered = db_path.with_suffix(".db.recovered")
        try:
            result = subprocess.run(  # noqa: S603, S607
                ["sqlite3", str(db_path), ".recover"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                # Pipe recovered SQL into a fresh database
                result2 = subprocess.run(  # noqa: S603, S607
                    ["sqlite3", str(recovered)],
                    input=result.stdout,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result2.returncode == 0 and recovered.exists():
                    backup = db_path.with_suffix(".db.corrupt")
                    shutil.move(str(db_path), str(backup))
                    shutil.move(str(recovered), str(db_path))
                    # Clean up any leftover sidecar files from the corrupt copy
                    for suffix in ("-wal", "-shm"):
                        Path(str(db_path) + suffix).unlink(missing_ok=True)
                    await self._engine.dispose()
                    await self._init_db_inner()
                    logger.info(
                        "Recovery succeeded via sqlite3 .recover "
                        "(corrupt backup at %s)",
                        backup,
                    )
                    return
        except (OSError, subprocess.TimeoutExpired) as recover_err:
            logger.warning("sqlite3 .recover failed: %s", recover_err)
        finally:
            recovered.unlink(missing_ok=True)

        # ── Level 3: give up — let the operator decide ───────────────────
        raise SADatabaseError(
            statement="init_db recovery",
            params=None,
            orig=Exception(
                f"Database {db_path} is corrupt and automatic "
                f"recovery failed. To start fresh: "
                f"rm -f '{db_path}' '{db_path}-wal' '{db_path}-shm'"
            ),
        )

    async def _init_db_inner(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with self._engine.begin() as conn:
            # SQLite: verify database integrity early so corruption is
            # caught here (where tiered recovery can handle it).
            if self._is_sqlite:
                result = await conn.execute(text("PRAGMA quick_check"))
                status = result.scalar()
                if status != "ok":
                    raise SADatabaseError(
                        statement="PRAGMA quick_check",
                        params=None,
                        orig=Exception(f"quick_check failed: {status}"),
                    )
            # Schema migration: add columns introduced after initial table creation.
            # SQLite has no IF NOT EXISTS for ALTER TABLE ADD COLUMN, so we catch errors.
            for ddl in [
                "ALTER TABLE sessions ADD COLUMN project_paused INTEGER NOT NULL DEFAULT 0",
            ]:
                with suppress(Exception):
                    await conn.execute(text(ddl))
            # Reset tasks orphaned in 'running' state by a previously crashed runner;
            # also clear any project_paused flag so the dispatcher isn't permanently blocked.
            await conn.execute(
                text("UPDATE tasks SET status='pending', started_at=NULL WHERE status='running'")
            )
            await conn.execute(text("UPDATE sessions SET project_paused=0"))

    async def dispose(self) -> None:
        """Dispose the async engine, closing all pooled connections.

        Call this during test teardown to prevent 'Event loop is closed'
        warnings from aiosqlite connections that outlive the event loop.
        """
        await self._engine.dispose()

    async def __aenter__(self) -> AgentStateService:
        """Enter async context — initialise the database."""
        await self.init_db()
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Exit async context — dispose engine to close aiosqlite connections."""
        await self.dispose()

    def create_app(self) -> FastAPI:
        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
            await self.init_db()
            # Auto-start regression reviewer in the state service process so it
            # can broadcast WebSocket events directly.  The reviewer is skipped
            # when no project path is available (e.g. bare `create_app_from_env`
            # without a real project).
            if self._project_path is not None:
                from claw_forge.orchestrator.reviewer import ParallelReviewer
                reviewer = ParallelReviewer(
                    project_dir=self._project_path,
                    state_service=self,
                )
                self._reviewer = reviewer
                await reviewer.start()
                logger.info(
                    "Regression reviewer started (cmd=%s)",
                    reviewer.test_command or "none detected",
                )
            yield
            if self._reviewer is not None:
                await self._reviewer.stop()
                self._reviewer = None
            # SQLite WAL checkpoint before closing so the DB is self-contained.
            if self._is_sqlite:
                try:
                    async with self._engine.begin() as _conn:
                        await _conn.execute(
                            text("PRAGMA wal_checkpoint(PASSIVE)")
                        )
                except BaseException:  # noqa: BLE001
                    # CancelledError is a BaseException — must catch it
                    # so engine.dispose() below is guaranteed to run.
                    pass
            await self._engine.dispose()

        app = FastAPI(title="claw-forge State Service", version="0.1.0", lifespan=lifespan)
        self._register_routes(app)
        return app

    def _register_routes(self, app: FastAPI) -> None:
        _db_url_str = str(self._engine.url)
        _svc_project = str(self._project_path) if self._project_path else ""

        @app.get("/info")
        async def service_info() -> dict[str, str]:
            """Return which project this state service instance is serving."""
            from claw_forge import __version__ as _ver
            return {
                "project_path": _svc_project,
                "database_url": _db_url_str,
                "claw_forge_version": _ver,
            }

        @app.post("/shutdown", status_code=200)
        async def shutdown() -> dict[str, str]:
            """Gracefully shut down this service instance (used for restart on project change)."""
            import os
            import signal
            import threading
            # Shut down after a brief delay so the HTTP response can be sent
            def _kill() -> None:
                import time
                time.sleep(0.2)
                os.kill(os.getpid(), signal.SIGTERM)
            threading.Thread(target=_kill, daemon=True).start()
            return {"status": "shutting down"}

        @app.post("/sessions", status_code=201)
        async def create_session(req: CreateSessionRequest) -> dict[str, Any]:
            async with self._session_factory() as db:
                session = Session(project_path=req.project_path, manifest_json=req.manifest)
                db.add(session)
                await db.commit()
                await db.refresh(session)
                await self._emit_event(str(session.id), None, "session.created", {"session_id": str(session.id)})  # noqa: E501
                return {"id": session.id, "status": session.status}

        @app.get("/sessions")
        async def list_sessions() -> list[dict[str, Any]]:
            async with self._session_factory() as db:
                result = await db.execute(select(Session).order_by(Session.created_at.desc()))
                sessions = result.scalars().all()
                return [
                    {
                        "id": s.id,
                        "project_path": s.project_path,
                        "status": s.status,
                        "created_at": str(s.created_at),
                    }
                    for s in sessions
                ]

        @app.post("/sessions/init")
        async def init_session(req: SessionInitRequest) -> dict[str, Any]:
            """Find or create a session, reset orphans, return actionable tasks."""
            async with self._session_factory() as db:
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
                tasks: Sequence[Task] = result.scalars().all()  # type: ignore[assignment]

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
                    "tasks": [_task_summary(t) for t in tasks],
                }

        @app.get("/sessions/{session_id}")
        async def get_session(session_id: str) -> dict[str, Any]:
            async with self._session_factory() as db:
                result = await db.execute(
                    select(Session)
                    .options(selectinload(Session.tasks))
                    .where(Session.id == session_id)
                )
                session = result.scalar_one_or_none()
                if not session:
                    raise HTTPException(404, "Session not found")
                return {
                    "id": session.id,
                    "project_path": session.project_path,
                    "status": session.status,
                    "created_at": str(session.created_at),
                    "task_count": len(session.tasks),
                }

        @app.post("/sessions/{session_id}/tasks", status_code=201)
        async def create_task(session_id: str, req: CreateTaskRequest) -> dict[str, Any]:
            async with self._session_factory() as db:
                session = await db.get(Session, session_id)
                if not session:
                    raise HTTPException(404, "Session not found")
                task = Task(
                    session_id=session_id,
                    plugin_name=req.plugin_name,
                    description=req.description,
                    priority=req.priority,
                    depends_on=req.depends_on,
                    category=req.category,
                    steps=req.steps,
                )
                db.add(task)
                await db.commit()
                await db.refresh(task)
                await self._emit_event(
                    session_id, str(task.id), "task.created", {"task_id": task.id}
                )
                return {"id": task.id, "status": task.status}

        @app.patch("/tasks/{task_id}")
        async def update_task(task_id: str, req: UpdateTaskRequest) -> dict[str, Any]:
            async with self._session_factory() as db:
                task = await db.get(Task, task_id)
                if not task:
                    raise HTTPException(404, "Task not found")
                if req.status:
                    task.status = req.status
                    if req.status == "running" and not task.started_at:
                        task.started_at = datetime.now(UTC)
                    elif req.status == "pending":
                        task.started_at = None
                    elif req.status in ("completed", "failed"):
                        task.completed_at = datetime.now(UTC)
                        if req.status == "completed" and self._reviewer is not None:
                            self._reviewer.notify_feature_completed()
                if req.result is not None:
                    task.result_json = req.result
                if req.error_message is not None:
                    task.error_message = req.error_message
                if req.input_tokens is not None:
                    task.input_tokens = (task.input_tokens or 0) + req.input_tokens
                if req.output_tokens is not None:
                    task.output_tokens = (task.output_tokens or 0) + req.output_tokens
                if req.cost_usd is not None:
                    task.cost_usd = (task.cost_usd or 0.0) + req.cost_usd
                if req.active_subagents is not None:
                    task.active_subagents = req.active_subagents
                await db.commit()
                await self._emit_event(
                    str(task.session_id),
                    str(task.id),
                    "task.updated",
                    {
                        "id": str(task.id),
                        "name": task.description or task.plugin_name,
                        "status": str(task.status),
                        "category": task.category or task.plugin_name,
                        "plugin_name": task.plugin_name,
                        "result_json": task.result_json,
                        "error_message": task.error_message,
                        "cost_usd": task.cost_usd,
                        "input_tokens": task.input_tokens,
                        "output_tokens": task.output_tokens,
                        "active_subagents": task.active_subagents,
                    },
                )
                return {"id": task.id, "status": task.status}

        @app.get("/tasks/{task_id}")
        async def get_task(task_id: str) -> dict[str, Any]:
            async with self._session_factory() as db:
                task = await db.get(Task, task_id)
                if not task:
                    raise HTTPException(404, "Task not found")
                detail = _task_summary(task)
                detail.update(
                    session_id=task.session_id,
                    result_json=task.result_json,
                    error_message=task.error_message,
                    input_tokens=task.input_tokens,
                    output_tokens=task.output_tokens,
                    cost_usd=task.cost_usd,
                    created_at=str(task.created_at) if task.created_at else None,
                    started_at=str(task.started_at) if task.started_at else None,
                    completed_at=str(task.completed_at) if task.completed_at else None,
                )
                return detail

        @app.post("/tasks/{task_id}/agent-log")
        async def post_agent_log(task_id: str, req: AgentLogRequest) -> dict[str, str]:
            """Accept an agent streaming log entry and broadcast it via WebSocket.

            Logs are suppressed for tasks that have been paused via stop-all so
            lingering agent subprocesses don't pollute the activity log.
            """
            if task_id in self._paused_task_ids:
                return {"status": "suppressed"}
            task_name = req.task_name or task_id[:8]
            await self.ws_manager.broadcast_agent_log(
                task_id=task_id,
                task_name=task_name,
                role=req.role,
                content=req.content,
                level=req.level,
                model=req.model,
            )
            return {"status": "ok"}

        @app.get("/sessions/{session_id}/tasks")
        async def list_tasks(session_id: str) -> list[dict[str, Any]]:
            async with self._session_factory() as db:
                result = await db.execute(select(Task).where(Task.session_id == session_id))
                tasks = result.scalars().all()
                return [
                    {
                        "id": t.id,
                        "name": t.description or t.plugin_name,
                        "plugin_name": t.plugin_name,
                        "category": t.category or t.plugin_name,
                        "description": t.description,
                        "status": t.status,
                        "priority": t.priority,
                        "depends_on": t.depends_on,
                        "steps": t.steps or [],
                        "result_json": t.result_json,
                        "error_message": t.error_message,
                        "input_tokens": t.input_tokens,
                        "output_tokens": t.output_tokens,
                        "cost_usd": t.cost_usd,
                        "created_at": str(t.created_at) if t.created_at else None,
                        "started_at": str(t.started_at) if t.started_at else None,
                        "completed_at": str(t.completed_at) if t.completed_at else None,
                    }
                    for t in tasks
                ]

        @app.get("/sessions/{session_id}/events")
        async def stream_events(session_id: str) -> EventSourceResponse:
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
            self._event_queues.append(queue)

            async def event_generator() -> AsyncGenerator[dict[str, str], None]:
                try:
                    while True:
                        event = await queue.get()
                        if event.get("session_id") == session_id:
                            yield {"event": event["type"], "data": json.dumps(event["payload"])}
                finally:
                    with suppress(ValueError):
                        self._event_queues.remove(queue)

            return EventSourceResponse(event_generator())

        @app.websocket("/ws")
        async def websocket_global(websocket: WebSocket) -> None:
            """Global WebSocket endpoint for the Kanban UI.

            Clients connect to ``ws://localhost:8888/ws`` and receive all
            broadcast events (feature_update, pool_update, agent_started,
            agent_completed, cost_update).

            The server responds to ``{"ping": true}`` with ``{"pong": true}``
            to allow keep-alive checks from the UI.
            """
            await self.ws_manager.connect(websocket)
            try:
                while True:
                    try:
                        data = await websocket.receive_json()
                        if isinstance(data, dict) and data.get("ping"):
                            await websocket.send_json({"pong": True})
                    except WebSocketDisconnect:
                        break
                    except Exception:
                        break
            finally:
                self.ws_manager.disconnect(websocket)

        @app.websocket("/ws/{session_id}")
        async def websocket_session(websocket: WebSocket, session_id: str) -> None:
            """Per-session WebSocket for legacy session-scoped consumers."""
            await websocket.accept()
            self._ws_clients.append(websocket)
            try:
                while True:
                    data = await websocket.receive_text()
                    # Echo or handle commands
                    await websocket.send_json({"ack": data})
            except WebSocketDisconnect:
                if websocket in self._ws_clients:
                    self._ws_clients.remove(websocket)

        # ── Pause / Resume endpoints ─────────────────────────────────────────

        @app.post("/project/pause")
        async def pause_project(session_id: str) -> dict[str, Any]:
            """Set the project_paused flag. The dispatcher will drain in-flight
            agents but will not start new ones until resumed."""
            async with self._session_factory() as db:
                session = await db.get(Session, session_id)
                if not session:
                    raise HTTPException(404, "Session not found")
                session.project_paused = True
                await db.commit()
                await self._emit_event(session_id, None, "project.paused", {"session_id": session_id})  # noqa: E501
                return {"session_id": session_id, "paused": True}

        @app.post("/project/resume")
        async def resume_project(session_id: str) -> dict[str, Any]:
            """Clear the project_paused flag. The dispatcher resumes dispatching
            new tasks immediately."""
            async with self._session_factory() as db:
                session = await db.get(Session, session_id)
                if not session:
                    raise HTTPException(404, "Session not found")
                session.project_paused = False
                await db.commit()
                await self._emit_event(session_id, None, "project.resumed", {"session_id": session_id})  # noqa: E501
                return {"session_id": session_id, "paused": False}

        @app.get("/project/paused")
        async def is_project_paused(session_id: str) -> dict[str, Any]:
            """Check whether a session is currently paused."""
            async with self._session_factory() as db:
                session = await db.get(Session, session_id)
                if not session:
                    raise HTTPException(404, "Session not found")
                return {"session_id": session_id, "paused": bool(session.project_paused)}

        # ── Stop task endpoints ──────────────────────────────────────────────

        @app.post("/tasks/{task_id}/stop")
        async def stop_task(task_id: str) -> dict[str, Any]:
            """Stop a running task and pause it.

            Immediately sets the task status to ``paused`` in the DB so it
            remains visible in the In Progress column.  Records the task ID
            in the in-memory ``_stop_requested`` set.  The dispatcher polls
            ``GET /stop-poll`` and cancels the matching asyncio task within
            ~2 s.
            """
            async with self._session_factory() as db:
                task = await db.get(Task, task_id)
                if not task:
                    raise HTTPException(404, "Task not found")
                task.status = "paused"
                task.error_message = None
                task_name = task.description or task.plugin_name
                await db.commit()
            self._stop_requested.add(task_id)
            await self.ws_manager.broadcast_feature_update(
                {"id": task_id, "status": "paused", "name": task_name}
            )
            return {"task_id": task_id, "status": "paused"}

        @app.post("/tasks/{task_id}/resume")
        async def resume_task(task_id: str) -> dict[str, Any]:
            """Request resumption of a paused task.

            The task stays ``paused`` in the DB (so it remains in the
            In Progress column on page refresh).  The dispatcher picks up
            the resume request via ``GET /stop-poll`` and transitions the
            task to ``pending`` → ``running`` during its next cycle.
            """
            async with self._session_factory() as db:
                task = await db.get(Task, task_id)
                if not task:
                    raise HTTPException(404, "Task not found")
            self._resume_task_requested.add(task_id)
            self._paused_task_ids.discard(task_id)
            return {"task_id": task_id, "status": "resuming"}

        @app.post("/sessions/{session_id}/tasks/stop-all")
        async def stop_all_running(session_id: str) -> dict[str, Any]:
            """Pause all running tasks in a session.

            Sets each running task to ``paused`` so they remain visible in the
            In Progress column.  The dispatcher is signalled to drain (finish
            in-flight work, start no new waves) via the ``/stop-poll`` flag.
            Call ``POST /sessions/{session_id}/tasks/resume-all`` to resume.
            """
            async with self._session_factory() as db:
                session = await db.get(Session, session_id)
                if session:
                    session.project_paused = True
                result = await db.execute(
                    select(Task).where(
                        Task.session_id == session_id,
                        Task.status == "running",
                    )
                )
                running_tasks = result.scalars().all()
                stopped_tasks: list[tuple[str, str]] = []
                for task in running_tasks:
                    task.status = "paused"
                    stopped_tasks.append((str(task.id), task.description or task.plugin_name))
                await db.commit()
            stopped_ids = [t[0] for t in stopped_tasks]
            # Signal dispatcher to cancel these tasks and enter drain mode
            for task_id in stopped_ids:
                self._stop_requested.add(task_id)
                self._paused_task_ids.add(task_id)
            self._pause_requested = True
            for task_id, task_name in stopped_tasks:
                await self.ws_manager.broadcast_feature_update(
                    {"id": task_id, "status": "paused", "name": task_name}
                )
            return {"stopped": stopped_ids}

        @app.post("/sessions/{session_id}/tasks/resume-all")
        async def resume_all_paused(session_id: str) -> dict[str, Any]:
            """Resume all paused tasks in a session.

            Sets each paused task back to ``pending`` so the dispatcher can
            pick them up on the next run.  Clears the ``project_paused`` flag.
            """
            async with self._session_factory() as db:
                session = await db.get(Session, session_id)
                if session:
                    session.project_paused = False
                result = await db.execute(
                    select(Task).where(
                        Task.session_id == session_id,
                        Task.status == "paused",
                    )
                )
                paused_tasks = result.scalars().all()
                resumed_tasks: list[tuple[str, str]] = []
                for task in paused_tasks:
                    task.status = "pending"
                    resumed_tasks.append((str(task.id), task.description or task.plugin_name))
                await db.commit()
            resumed_ids = [t[0] for t in resumed_tasks]
            self._resume_requested = True
            # Re-allow log broadcasting for these tasks
            for task_id in resumed_ids:
                self._paused_task_ids.discard(task_id)
            for task_id, task_name in resumed_tasks:
                await self.ws_manager.broadcast_feature_update(
                    {"id": task_id, "status": "pending", "name": task_name}
                )
            return {"resumed": resumed_ids}

        @app.get("/stop-poll")
        async def stop_poll() -> dict[str, Any]:
            """Return and clear the pending stop-request set plus pause/resume signals.

            Called by the dispatcher every ~2 s to discover task IDs that
            the UI has requested to stop and whether to pause or resume.
            All values are cleared atomically so each signal is delivered once.
            """
            task_ids = list(self._stop_requested)
            self._stop_requested.clear()
            pause = self._pause_requested
            self._pause_requested = False
            resume = self._resume_requested
            self._resume_requested = False
            resume_task_ids = list(self._resume_task_requested)
            self._resume_task_requested.clear()
            return {
                "task_ids": task_ids,
                "pause": pause,
                "resume": resume,
                "resume_task_ids": resume_task_ids,
            }

        # ── Human input endpoints ────────────────────────────────────────────

        @app.post("/features/{task_id}/human-input")
        async def request_human_input(task_id: str, req: HumanInputRequest) -> dict[str, Any]:
            """Agent signals it is blocked and needs a human answer.

            Moves the task to ``needs_human`` status and stores the question.
            The Kanban UI displays these tasks in a dedicated "Needs Human" column.
            """
            async with self._session_factory() as db:
                task = await db.get(Task, task_id)
                if not task:
                    raise HTTPException(404, "Task not found")
                task.status = "needs_human"
                task.human_question = req.question
                task.human_answer = None  # clear any stale answer
                await db.commit()
                await self._emit_event(
                    str(task.session_id),
                    task_id,
                    "task.needs_human",
                    {"task_id": task_id, "question": req.question},
                )
                await self.ws_manager.broadcast_feature_update(
                    {"task_id": task_id, "status": "needs_human", "question": req.question}
                )
                return {"task_id": task_id, "status": "needs_human", "question": req.question}

        @app.post("/features/{task_id}/human-answer")
        async def submit_human_answer(task_id: str, req: HumanAnswerRequest) -> dict[str, Any]:
            """Submit a human answer to an awaiting task.

            Stores the answer and moves the task back to ``pending`` so the
            dispatcher will pick it up again.
            """
            async with self._session_factory() as db:
                task = await db.get(Task, task_id)
                if not task:
                    raise HTTPException(404, "Task not found")
                if task.status != "needs_human":
                    raise HTTPException(400, f"Task is not in needs_human status (got: {task.status})")  # noqa: E501
                task.human_answer = req.answer
                task.status = "pending"
                await db.commit()
                await self._emit_event(
                    str(task.session_id),
                    task_id,
                    "task.human_answered",
                    {"task_id": task_id, "answer": req.answer},
                )
                await self.ws_manager.broadcast_feature_update(
                    {"task_id": task_id, "status": "pending", "answer": req.answer}
                )
                return {"task_id": task_id, "status": "pending"}

        @app.get("/features/needs-human")
        async def list_needs_human(session_id: str | None = None) -> list[dict[str, Any]]:
            """List all tasks waiting for human input.

            Optionally filter by *session_id*.  Used by ``claw-forge input``
            CLI command to display pending questions.
            """
            async with self._session_factory() as db:
                query = select(Task).where(Task.status == "needs_human")
                if session_id:
                    query = query.where(Task.session_id == session_id)
                result = await db.execute(query)
                tasks = result.scalars().all()
                return [
                    {
                        "task_id": t.id,
                        "session_id": t.session_id,
                        "description": t.description,
                        "question": t.human_question,
                    }
                    for t in tasks
                ]

        # ── Regression status endpoint ────────────────────────────────────

        @app.get("/regression/status")
        async def regression_status() -> dict[str, Any]:
            """Return the last regression result and run count.

            Used by the Kanban health bar to poll for regression state.
            """
            reviewer = self._reviewer
            if reviewer is None or reviewer.test_command is None:
                return {"run_count": 0, "last_result": None, "has_test_command": False}
            if reviewer.run_count == 0:
                return {"run_count": 0, "last_result": None, "has_test_command": True}
            last = reviewer.last_result
            return {
                "run_count": reviewer.run_count,
                "last_result": last.to_dict() if last else None,
                "has_test_command": True,
            }

        @app.get("/pool/status")
        async def pool_status() -> dict[str, Any]:
            """Return pool provider status.

            When a run is active, returns live stats from the pool manager.
            When idle, reads provider config from claw-forge.yaml so the UI
            can still display and toggle providers.
            """
            pm = self._pool_manager
            if pm is not None:
                status = await pm.get_pool_status()
                return {**status, "active": True}

            # Fallback: read provider config from YAML so the UI isn't empty
            config_path = self._find_config_path()
            if config_path is None:
                return {"providers": [], "model_aliases": {}, "active": False}
            try:
                text = config_path.read_text()
                data = yaml.safe_load(text) or {}
                providers_cfg = data.get("providers", {})
                # Resolve model_aliases (strip ${VAR:-default} to just default)
                raw_aliases = data.get("model_aliases", {})
                model_aliases: dict[str, str] = {}
                for alias, val in (raw_aliases or {}).items():
                    v = str(val)
                    if v.startswith("${") and ":-" in v:
                        v = v.split(":-", 1)[1].rstrip("}")
                    model_aliases[alias] = v
                providers = []
                for name, cfg in providers_cfg.items():
                    if not isinstance(cfg, dict):
                        continue
                    providers.append({
                        "name": name,
                        "type": cfg.get("type", "unknown"),
                        "priority": cfg.get("priority", 99),
                        "enabled": cfg.get("enabled", True),
                        "health": "healthy" if cfg.get("enabled", True) else "unknown",
                        "circuit_state": "closed",
                        "circuit": {
                            "name": name, "state": "closed",
                            "failure_count": 0,
                            "failure_threshold": 5,
                            "recovery_timeout": 60.0,
                        },
                        "rpm": 0,
                        "max_rpm": cfg.get("max_rpm", 60),
                        "total_cost_usd": 0,
                        "avg_latency_ms": 0,
                        "model": cfg.get("model", ""),
                        "model_map": cfg.get("model_map", {}) or {},
                        "active_tiers": cfg.get("active_tiers", []) or [],
                    })
                strategy = data.get("pool", {}).get("strategy", "priority")
                return {
                    "providers": providers,
                    "model_aliases": model_aliases,
                    "active": False,
                    "strategy": strategy,
                }
            except Exception:  # noqa: BLE001
                return {"providers": [], "model_aliases": {}, "active": False}

        # ── Provider toggle endpoints ─────────────────────────────────────

        @app.patch("/pool/providers/{name}")
        async def toggle_provider(name: str, req: ToggleProviderRequest) -> dict[str, Any]:
            """Runtime enable/disable of a provider.

            When a run is active, toggles the live pool manager.
            When idle, writes directly to claw-forge.yaml so the change
            persists for the next run.
            """
            pm = self._pool_manager
            if pm is not None:
                found = pm.enable_provider(name) if req.enabled else pm.disable_provider(name)
                if not found:
                    raise HTTPException(404, f"Provider {name!r} not found")
                status = await pm.get_pool_status()
                await self.ws_manager.broadcast_pool_update(status["providers"])
                return {"name": name, "enabled": req.enabled, "persisted": False}

            # No active run — persist to YAML so next run picks it up
            config_path = self._find_config_path()
            if config_path is None:
                raise HTTPException(422, "No claw-forge.yaml found")
            try:
                self._persist_provider_enabled(config_path, name, req.enabled)
            except ValueError as exc:
                raise HTTPException(404, str(exc)) from exc
            return {"name": name, "enabled": req.enabled, "persisted": True}

        @app.post("/pool/providers/{name}/persist")
        async def persist_provider(name: str, req: ToggleProviderRequest) -> dict[str, Any]:
            """Write enabled state to claw-forge.yaml atomically."""
            pm = self._pool_manager
            if pm is None:
                raise HTTPException(503, "Pool manager not available")
            current = pm.get_provider_enabled(name)
            if current is None:
                raise HTTPException(404, f"Provider {name!r} not found")
            config_path = self._find_config_path()
            if config_path is None:
                raise HTTPException(422, {"error": "config file not found"})
            try:
                self._persist_provider_enabled(config_path, name, req.enabled)
            except ValueError as exc:
                raise HTTPException(422, {"error": str(exc)}) from exc
            # Also apply runtime change to stay in sync
            if req.enabled:
                pm.enable_provider(name)
            else:
                pm.disable_provider(name)
            status = await pm.get_pool_status()
            await self.ws_manager.broadcast_pool_update(status["providers"])
            return {
                "name": name, "enabled": req.enabled,
                "persisted": True, "config_path": str(config_path),
            }

        @app.patch("/pool/providers/{name}/models")
        async def set_provider_models(name: str, req: SetProviderModelsRequest) -> dict[str, Any]:
            """Update the active tier list for a provider at runtime."""
            pm = self._pool_manager
            if pm is None:
                raise HTTPException(503, "Pool manager not available")
            found = pm.set_provider_tiers(name, req.active_tiers)
            if not found:
                raise HTTPException(404, f"Provider {name!r} not found")
            status = await pm.get_pool_status()
            await self.ws_manager.broadcast_pool_update(status["providers"])
            return {"name": name, "active_tiers": req.active_tiers}

        # ── Command palette endpoints ─────────────────────────────────────

        @app.get("/commands/list")
        async def list_commands() -> list[dict[str, Any]]:
            """Return the full command registry for the command palette."""
            return COMMANDS

        @app.post("/commands/execute")
        async def execute_command(req: ExecuteCommandRequest) -> dict[str, Any]:
            """Start executing a command and stream output via WebSocket.

            Returns immediately with an execution_id.  Progress is broadcast
            as ``command_output`` and ``command_done`` WebSocket events.
            """
            if req.command not in COMMAND_IDS:
                raise HTTPException(404, f"Unknown command: {req.command!r}")

            execution_id = str(uuid.uuid4())
            started_at = time.monotonic()

            shell_cmd = list(COMMAND_SHELLS[req.command])

            self._executions[execution_id] = {
                "command": req.command,
                "status": "running",
                "output": [],
                "exit_code": None,
                "started_at": started_at,
            }

            async def _run() -> None:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *shell_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=req.project_dir if req.project_dir != "." else None,
                    )

                    async def _stream(stream: asyncio.StreamReader, stream_name: str) -> None:
                        async for raw in stream:
                            line = raw.decode(errors="replace").rstrip()
                            self._executions[execution_id]["output"].append(line)
                            await self.ws_manager.broadcast(
                                {
                                    "type": "command_output",
                                    "execution_id": execution_id,
                                    "line": line,
                                    "stream": stream_name,
                                }
                            )

                    assert proc.stdout is not None
                    assert proc.stderr is not None
                    await asyncio.gather(
                        _stream(proc.stdout, "stdout"),
                        _stream(proc.stderr, "stderr"),
                    )
                    exit_code = await proc.wait()
                except Exception as exc:
                    logger.exception("Command execution failed: %s", exc)
                    exit_code = 1
                    self._executions[execution_id]["output"].append(str(exc))

                duration_ms = int((time.monotonic() - started_at) * 1000)
                status = "done" if exit_code == 0 else "failed"
                self._executions[execution_id]["status"] = status
                self._executions[execution_id]["exit_code"] = exit_code
                await self.ws_manager.broadcast(
                    {
                        "type": "command_done",
                        "execution_id": execution_id,
                        "exit_code": exit_code,
                        "duration_ms": duration_ms,
                    }
                )

            asyncio.create_task(_run())
            return {"execution_id": execution_id, "status": "started"}

        @app.get("/commands/executions/{execution_id}")
        async def get_execution(execution_id: str) -> dict[str, Any]:
            """Fetch stored execution state by ID."""
            entry = self._executions.get(execution_id)
            if not entry:
                raise HTTPException(404, "Execution not found")
            return {"execution_id": execution_id, **entry}

    async def _emit_event(
        self, session_id: str, task_id: str | None, event_type: str, payload: dict[str, Any]
    ) -> None:
        event_data = {
            "session_id": session_id,
            "task_id": task_id,
            "type": event_type,
            "payload": payload,
        }
        # Persist
        async with self._session_factory() as db:
            db.add(Event(session_id=session_id, task_id=task_id, event_type=event_type, payload=payload))  # noqa: E501
            await db.commit()
        # Notify SSE listeners
        for q in self._event_queues:
            await q.put(event_data)
        # Notify legacy per-session WebSocket clients
        for ws in list(self._ws_clients):
            try:
                await ws.send_json(event_data)
            except Exception:
                if ws in self._ws_clients:
                    self._ws_clients.remove(ws)
        # Notify global Kanban UI WebSocket clients
        # Map task events to kanban-friendly feature_update events
        if event_type in ("task.created", "task.updated"):
            feature_payload: dict[str, Any] = {
                "session_id": session_id,
                "task_id": task_id,
                **payload,
            }
            await self.ws_manager.broadcast_feature_update(feature_payload)
        else:
            await self.ws_manager.broadcast(event_data)
