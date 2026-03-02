"""FastAPI AgentStateService with SSE and WebSocket support."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sse_starlette.sse import EventSourceResponse

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


class AgentStateService:
    """REST + SSE + WebSocket state service for orchestrating agents."""

    def __init__(self, database_url: str = "sqlite+aiosqlite:///claw_forge.db") -> None:
        self._engine = create_async_engine(database_url, echo=False)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        self._event_queues: list[asyncio.Queue[dict[str, Any]]] = []
        self._ws_clients: list[WebSocket] = []
        # Kanban UI real-time broadcast manager
        self.ws_manager: ConnectionManager = ConnectionManager()

    async def init_db(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

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
                session = await db.get(Session, session_id)
                if not session:
                    raise HTTPException(404, "Session not found")
                return {
                    "id": session.id,
                    "project_path": session.project_path,
                    "status": session.status,
                    "created_at": str(session.created_at),
                    "task_count": len(session.tasks) if session.tasks else 0,
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
                    task.status = req.status  # type: ignore[assignment]  # SQLAlchemy instrumented attr
                    if req.status == "running" and not task.started_at:
                        task.started_at = datetime.now(UTC)  # type: ignore[assignment]
                    elif req.status in ("completed", "failed"):
                        task.completed_at = datetime.now(UTC)  # type: ignore[assignment]
                if req.result is not None:
                    task.result_json = req.result  # type: ignore[assignment]
                if req.error_message is not None:
                    task.error_message = req.error_message  # type: ignore[assignment]
                if req.input_tokens is not None:
                    task.input_tokens = task.input_tokens + req.input_tokens  # type: ignore[assignment]
                if req.output_tokens is not None:
                    task.output_tokens = task.output_tokens + req.output_tokens  # type: ignore[assignment]
                if req.cost_usd is not None:
                    task.cost_usd = task.cost_usd + req.cost_usd  # type: ignore[assignment]
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
                        "plugin_name": t.plugin_name,
                        "status": t.status,
                        "priority": t.priority,
                        "depends_on": t.depends_on,
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
                session.project_paused = True  # type: ignore[assignment]
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
                session.project_paused = False  # type: ignore[assignment]
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
                task.status = "needs_human"  # type: ignore[assignment]
                task.human_question = req.question  # type: ignore[assignment]
                task.human_answer = None  # type: ignore[assignment]  # clear any stale answer
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
                task.human_answer = req.answer  # type: ignore[assignment]
                task.status = "pending"  # type: ignore[assignment]
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
