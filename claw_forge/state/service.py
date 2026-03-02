"""FastAPI AgentStateService with SSE and WebSocket support."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sse_starlette.sse import EventSourceResponse

from claw_forge.state.models import Base, Event, Session, Task

logger = logging.getLogger(__name__)


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


class AgentStateService:
    """REST + SSE + WebSocket state service for orchestrating agents."""

    def __init__(self, database_url: str = "sqlite+aiosqlite:///claw_forge.db") -> None:
        self._engine = create_async_engine(database_url, echo=False)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        self._event_queues: list[asyncio.Queue[dict[str, Any]]] = []
        self._ws_clients: list[WebSocket] = []

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
                await self._emit_event(session.id, None, "session.created", {"session_id": session.id})
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
                await self._emit_event(session_id, task.id, "task.created", {"task_id": task.id})
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
                        task.started_at = datetime.now(timezone.utc)
                    elif req.status in ("completed", "failed"):
                        task.completed_at = datetime.now(timezone.utc)
                if req.result is not None:
                    task.result_json = req.result
                if req.error_message is not None:
                    task.error_message = req.error_message
                if req.input_tokens is not None:
                    task.input_tokens += req.input_tokens
                if req.output_tokens is not None:
                    task.output_tokens += req.output_tokens
                if req.cost_usd is not None:
                    task.cost_usd += req.cost_usd
                await db.commit()
                await self._emit_event(
                    task.session_id, task.id, "task.updated", {"status": task.status}
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

        @app.websocket("/ws/{session_id}")
        async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
            await websocket.accept()
            self._ws_clients.append(websocket)
            try:
                while True:
                    data = await websocket.receive_text()
                    # Echo or handle commands
                    await websocket.send_json({"ack": data})
            except WebSocketDisconnect:
                self._ws_clients.remove(websocket)

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
            db.add(Event(session_id=session_id, task_id=task_id, event_type=event_type, payload=payload))
            await db.commit()
        # Notify SSE listeners
        for q in self._event_queues:
            await q.put(event_data)
        # Notify WebSocket clients
        for ws in list(self._ws_clients):
            try:
                await ws.send_json(event_data)
            except Exception:
                self._ws_clients.remove(ws)
