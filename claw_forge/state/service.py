"""FastAPI AgentStateService with SSE and WebSocket support."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from claw_forge.commands.registry import COMMAND_IDS, COMMAND_SHELLS, COMMANDS
from claw_forge.pool.manager import ProviderPoolManager
from claw_forge.state.models import Base, Event, Session, Task

logger = logging.getLogger(__name__)


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


class UpdateTaskRequest(BaseModel):
    status: str | None = None
    result: dict[str, Any] | None = None
    error_message: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


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


class ToggleProviderRequest(BaseModel):
    """Request to enable or disable a provider at runtime."""

    enabled: bool


class AgentStateService:
    """REST + SSE + WebSocket state service for orchestrating agents."""

    def __init__(
        self,
        database_url: str = "sqlite+aiosqlite:///claw_forge.db",
        pool_manager: ProviderPoolManager | None = None,
    ) -> None:
        self._engine = create_async_engine(database_url, echo=False)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        self._event_queues: list[asyncio.Queue[dict[str, Any]]] = []
        self._ws_clients: list[WebSocket] = []
        # Kanban UI real-time broadcast manager
        self.ws_manager: ConnectionManager = ConnectionManager()
        # Regression reviewer reference (set by dispatcher)
        self._reviewer: Any | None = None
        # Command execution store: {execution_id: {...}}
        self._executions: dict[str, dict[str, Any]] = {}
        # Provider pool manager (optional, used by toggle endpoints)
        self._pool_manager: ProviderPoolManager | None = pool_manager

    @staticmethod
    def _find_config_path() -> Path | None:
        """Search CWD and up to 3 parent dirs for claw-forge.yaml."""
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
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

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
            yield
            await self._engine.dispose()

        app = FastAPI(title="claw-forge State Service", version="0.1.0", lifespan=lifespan)
        self._register_routes(app)
        return app

    def _register_routes(self, app: FastAPI) -> None:
        @app.post("/sessions", status_code=201)
        async def create_session(req: CreateSessionRequest) -> dict[str, Any]:
            async with self._session_factory() as db:
                session = Session(project_path=req.project_path, manifest_json=req.manifest)
                db.add(session)
                await db.commit()
                await db.refresh(session)
                await self._emit_event(str(session.id), None, "session.created", {"session_id": str(session.id)})  # noqa: E501
                return {"id": session.id, "status": session.status}

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
                    elif req.status in ("completed", "failed"):
                        task.completed_at = datetime.now(UTC)
                if req.result is not None:
                    task.result_json = req.result
                if req.error_message is not None:
                    task.error_message = req.error_message
                if req.input_tokens is not None:
                    task.input_tokens = task.input_tokens + req.input_tokens
                if req.output_tokens is not None:
                    task.output_tokens = task.output_tokens + req.output_tokens
                if req.cost_usd is not None:
                    task.cost_usd = task.cost_usd + req.cost_usd
                await db.commit()
                await self._emit_event(
                    str(task.session_id), str(task.id), "task.updated", {"status": str(task.status)}
                )
                return {"id": task.id, "status": task.status}

        @app.get("/sessions/{session_id}/tasks")
        async def list_tasks(session_id: str) -> list[dict[str, Any]]:
            async with self._session_factory() as db:
                result = await db.execute(select(Task).where(Task.session_id == session_id))
                tasks = result.scalars().all()
                return [
                    {
                        "id": t.id,
                        "name": t.description,
                        "plugin_name": t.plugin_name,
                        "description": t.description,
                        "status": t.status,
                        "priority": t.priority,
                        "depends_on": t.depends_on,
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
            if reviewer is None or reviewer.run_count == 0:
                return {"run_count": 0, "last_result": None}
            last = reviewer.last_result
            return {
                "run_count": reviewer.run_count,
                "last_result": last.to_dict() if last else None,
            }

        @app.get("/pool/status")
        async def pool_status() -> dict[str, Any]:
            """Return pool provider status. Returns empty list when no run is active."""
            pm = self._pool_manager
            if pm is None:
                return {"providers": [], "active": False}
            status = await pm.get_pool_status()
            return {**status, "active": True}

        # ── Provider toggle endpoints ─────────────────────────────────────

        @app.patch("/pool/providers/{name}")
        async def toggle_provider(name: str, req: ToggleProviderRequest) -> dict[str, Any]:
            """Runtime enable/disable of a provider. Does NOT write to disk."""
            pm = self._pool_manager
            if pm is None:
                raise HTTPException(503, "Pool manager not available")
            found = pm.enable_provider(name) if req.enabled else pm.disable_provider(name)
            if not found:
                raise HTTPException(404, f"Provider {name!r} not found")
            # Broadcast pool_update so the UI refreshes immediately
            status = await pm.get_pool_status()
            await self.ws_manager.broadcast_pool_update(status["providers"])
            return {"name": name, "enabled": req.enabled, "persisted": False}

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
