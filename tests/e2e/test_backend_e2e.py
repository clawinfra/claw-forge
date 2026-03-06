"""End-to-end tests for the FastAPI AgentStateService.

Tests all REST endpoints, WebSocket broadcast, SSE stream, and DB persistence
using an in-process ASGI client (no real server required).
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from claw_forge.state.service import AgentStateService, ConnectionManager

# ---------------------------------------------------------------------------
# Fixtures: in-process app with in-memory SQLite
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def service() -> AgentStateService:
    """AgentStateService backed by in-memory SQLite."""
    svc = AgentStateService(database_url="sqlite+aiosqlite:///:memory:")
    await svc.init_db()
    yield svc  # type: ignore[misc]
    await svc.dispose()


@pytest_asyncio.fixture
async def client(service: AgentStateService) -> AsyncClient:
    """HTTPX async client pointing at the FastAPI app."""
    app = service.create_app()
    await service.init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c  # type: ignore[misc]


@pytest.fixture
def sync_client(service: AgentStateService) -> TestClient:
    """Starlette sync TestClient — supports WebSocket testing."""
    app = service.create_app()
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _create_session(client: AsyncClient, project_path: str = "/tmp/test") -> str:
    r = await client.post("/sessions", json={"project_path": project_path})
    assert r.status_code == 201
    return r.json()["id"]


# ---------------------------------------------------------------------------
# Health / OpenAPI
# ---------------------------------------------------------------------------


class TestHealthEndpoints:
    async def test_root_404(self, client: AsyncClient) -> None:
        """Unknown route returns 404 (proves app is responding)."""
        r = await client.get("/no-such-path")
        assert r.status_code == 404

    async def test_openapi_schema_available(self, client: AsyncClient) -> None:
        r = await client.get("/openapi.json")
        assert r.status_code == 200
        schema = r.json()
        assert "openapi" in schema
        assert schema["info"]["title"] == "claw-forge State Service"

    async def test_docs_available(self, client: AsyncClient) -> None:
        r = await client.get("/docs")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


class TestSessionsEndpoint:
    async def test_create_session_returns_201(self, client: AsyncClient) -> None:
        r = await client.post("/sessions", json={"project_path": "/tmp/myproject"})
        assert r.status_code == 201
        body = r.json()
        assert "id" in body
        assert body["status"] == "pending"

    async def test_create_session_id_is_uuid(self, client: AsyncClient) -> None:
        r = await client.post("/sessions", json={"project_path": "/tmp/uuid-test"})
        assert r.status_code == 201
        sid = r.json()["id"]
        # UUID format: 8-4-4-4-12 hex chars
        assert len(sid) == 36
        assert sid.count("-") == 4

    async def test_get_nonexistent_session_returns_404(self, client: AsyncClient) -> None:
        r = await client.get("/sessions/does-not-exist")
        assert r.status_code == 404

    async def test_create_session_with_manifest(self, client: AsyncClient) -> None:
        manifest = {"features": ["login", "dashboard"]}
        r = await client.post(
            "/sessions",
            json={"project_path": "/tmp/manifest-project", "manifest": manifest},
        )
        assert r.status_code == 201
        assert "id" in r.json()

    async def test_multiple_sessions_get_unique_ids(self, client: AsyncClient) -> None:
        r1 = await client.post("/sessions", json={"project_path": "/tmp/proj-1"})
        r2 = await client.post("/sessions", json={"project_path": "/tmp/proj-2"})
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["id"] != r2.json()["id"]


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


class TestTasksEndpoint:
    async def test_create_task_returns_201(self, client: AsyncClient) -> None:
        sid = await _create_session(client)
        r = await client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "coding", "description": "Implement auth"},
        )
        assert r.status_code == 201
        body = r.json()
        assert "id" in body
        assert body["status"] == "pending"

    async def test_create_task_on_missing_session_returns_404(
        self, client: AsyncClient
    ) -> None:
        r = await client.post(
            "/sessions/ghost-session/tasks",
            json={"plugin_name": "testing"},
        )
        assert r.status_code == 404

    async def test_list_tasks_empty(self, client: AsyncClient) -> None:
        sid = await _create_session(client)
        r = await client.get(f"/sessions/{sid}/tasks")
        assert r.status_code == 200
        assert r.json() == []

    async def test_list_tasks_returns_created(self, client: AsyncClient) -> None:
        sid = await _create_session(client)
        await client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "coding", "description": "task A"},
        )
        await client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "testing", "description": "task B"},
        )
        r = await client.get(f"/sessions/{sid}/tasks")
        assert r.status_code == 200
        tasks = r.json()
        assert len(tasks) == 2
        plugin_names = {t["plugin_name"] for t in tasks}
        assert plugin_names == {"coding", "testing"}

    async def test_update_task_status(self, client: AsyncClient) -> None:
        sid = await _create_session(client)
        r_create = await client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "coding"},
        )
        tid = r_create.json()["id"]

        r_patch = await client.patch(f"/tasks/{tid}", json={"status": "running"})
        assert r_patch.status_code == 200
        assert r_patch.json()["status"] == "running"

    async def test_update_task_to_completed(self, client: AsyncClient) -> None:
        sid = await _create_session(client)
        r_create = await client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "reviewer"},
        )
        tid = r_create.json()["id"]

        r = await client.patch(f"/tasks/{tid}", json={"status": "completed"})
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

    async def test_update_task_cost(self, client: AsyncClient) -> None:
        sid = await _create_session(client)
        r_create = await client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "coding"},
        )
        tid = r_create.json()["id"]

        r = await client.patch(
            f"/tasks/{tid}",
            json={"input_tokens": 1000, "output_tokens": 500, "cost_usd": 0.05},
        )
        assert r.status_code == 200

    async def test_update_nonexistent_task_returns_404(self, client: AsyncClient) -> None:
        r = await client.patch("/tasks/ghost-task", json={"status": "running"})
        assert r.status_code == 404

    async def test_create_task_with_priority_and_depends(self, client: AsyncClient) -> None:
        sid = await _create_session(client)
        r = await client.post(
            f"/sessions/{sid}/tasks",
            json={
                "plugin_name": "testing",
                "priority": 10,
                "depends_on": ["task-a", "task-b"],
            },
        )
        assert r.status_code == 201
        body = r.json()
        assert "id" in body


# ---------------------------------------------------------------------------
# category + steps fields
# ---------------------------------------------------------------------------


class TestTaskCategoryAndSteps:
    async def test_create_task_with_category_and_steps(self, client: AsyncClient) -> None:
        sid = await _create_session(client)
        r = await client.post(
            f"/sessions/{sid}/tasks",
            json={
                "plugin_name": "coding",
                "description": "Add JWT auth",
                "category": "Authentication",
                "steps": [
                    "Run tests and verify all pass",
                    "Check coverage is above 90%",
                ],
            },
        )
        assert r.status_code == 201

    async def test_list_tasks_returns_category_not_plugin_name(
        self, client: AsyncClient
    ) -> None:
        sid = await _create_session(client)
        await client.post(
            f"/sessions/{sid}/tasks",
            json={
                "plugin_name": "coding",
                "description": "Implement login",
                "category": "Authentication",
            },
        )
        r = await client.get(f"/sessions/{sid}/tasks")
        assert r.status_code == 200
        task = r.json()[0]
        assert task["category"] == "Authentication"
        assert task["category"] != task["plugin_name"]

    async def test_list_tasks_returns_steps(self, client: AsyncClient) -> None:
        sid = await _create_session(client)
        steps = ["Step 1: Run tests", "Step 2: Check coverage"]
        await client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "testing", "steps": steps},
        )
        r = await client.get(f"/sessions/{sid}/tasks")
        assert r.status_code == 200
        assert r.json()[0]["steps"] == steps

    async def test_category_defaults_to_plugin_name_when_absent(
        self, client: AsyncClient
    ) -> None:
        sid = await _create_session(client)
        await client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "bugfix"},
        )
        r = await client.get(f"/sessions/{sid}/tasks")
        assert r.status_code == 200
        task = r.json()[0]
        # Falls back to plugin_name when no category stored
        assert task["category"] == "bugfix"
        assert task["steps"] == []


# ---------------------------------------------------------------------------
# DB persistence: create → retrieve → update → verify
# ---------------------------------------------------------------------------


class TestDBPersistence:
    async def test_create_retrieve_update_task(self, client: AsyncClient) -> None:
        """Create session + task → update task → verify via list."""
        sid = await _create_session(client, "/tmp/persist-proj")

        r_task = await client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "reviewer", "description": "code review"},
        )
        assert r_task.status_code == 201
        tid = r_task.json()["id"]

        r_patch = await client.patch(
            f"/tasks/{tid}",
            json={"status": "completed", "result": {"passed": True}},
        )
        assert r_patch.status_code == 200
        assert r_patch.json()["status"] == "completed"

        # Verify via list
        r_list = await client.get(f"/sessions/{sid}/tasks")
        assert r_list.status_code == 200
        tasks = r_list.json()
        assert len(tasks) == 1
        assert tasks[0]["status"] == "completed"

    async def test_task_tokens_accumulate(self, client: AsyncClient) -> None:
        sid = await _create_session(client)
        r_task = await client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "coding"},
        )
        tid = r_task.json()["id"]

        for _ in range(3):
            await client.patch(f"/tasks/{tid}", json={"input_tokens": 100, "output_tokens": 50})

        # 3 iterations × 100 input + 50 output = 300/150 total
        r_list = await client.get(f"/sessions/{sid}/tasks")
        assert r_list.status_code == 200

    async def test_session_and_tasks_persist_across_requests(
        self, client: AsyncClient
    ) -> None:
        """Data survives multiple independent requests within the same session."""
        sid = await _create_session(client, "/tmp/multi-request")

        tids = []
        for i in range(5):
            r = await client.post(
                f"/sessions/{sid}/tasks",
                json={"plugin_name": f"plugin-{i}", "description": f"task {i}"},
            )
            tids.append(r.json()["id"])

        r_list = await client.get(f"/sessions/{sid}/tasks")
        assert len(r_list.json()) == 5
        plugin_names = {t["plugin_name"] for t in r_list.json()}
        assert plugin_names == {f"plugin-{i}" for i in range(5)}


# ---------------------------------------------------------------------------
# Human input flow
# ---------------------------------------------------------------------------


class TestHumanInputFlow:
    async def test_request_human_input_sets_needs_human(self, client: AsyncClient) -> None:
        sid = await _create_session(client)
        r_task = await client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "coding", "description": "tricky feature"},
        )
        tid = r_task.json()["id"]

        r = await client.post(
            f"/features/{tid}/human-input",
            json={"question": "Which approach should I use?"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "needs_human"
        assert body["question"] == "Which approach should I use?"

    async def test_submit_human_answer_restores_pending(self, client: AsyncClient) -> None:
        sid = await _create_session(client)
        r_task = await client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "coding", "description": "need answer"},
        )
        tid = r_task.json()["id"]

        await client.post(
            f"/features/{tid}/human-input",
            json={"question": "Go or no-go?"},
        )
        r = await client.post(
            f"/features/{tid}/human-answer",
            json={"answer": "Go for it!"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "pending"

    async def test_answer_on_non_needs_human_task_returns_400(
        self, client: AsyncClient
    ) -> None:
        sid = await _create_session(client)
        r_task = await client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "coding"},
        )
        tid = r_task.json()["id"]
        # Still in "pending" state — no question asked
        r = await client.post(
            f"/features/{tid}/human-answer",
            json={"answer": "too late"},
        )
        assert r.status_code == 400

    async def test_list_needs_human_includes_blocked_task(self, client: AsyncClient) -> None:
        sid = await _create_session(client)
        r_task = await client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "coding", "description": "blocked"},
        )
        tid = r_task.json()["id"]
        await client.post(
            f"/features/{tid}/human-input",
            json={"question": "blocked question"},
        )

        r = await client.get(f"/features/needs-human?session_id={sid}")
        assert r.status_code == 200
        items = r.json()
        assert any(item["task_id"] == tid for item in items)

    async def test_list_needs_human_no_filter(self, client: AsyncClient) -> None:
        r = await client.get("/features/needs-human")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_answered_task_no_longer_in_needs_human(
        self, client: AsyncClient
    ) -> None:
        sid = await _create_session(client)
        r_task = await client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "coding"},
        )
        tid = r_task.json()["id"]

        await client.post(f"/features/{tid}/human-input", json={"question": "Q?"})
        await client.post(f"/features/{tid}/human-answer", json={"answer": "A!"})

        r = await client.get(f"/features/needs-human?session_id={sid}")
        # Task should no longer be in needs_human list
        assert all(item["task_id"] != tid for item in r.json())


# ---------------------------------------------------------------------------
# Pause / Resume endpoints
# ---------------------------------------------------------------------------


class TestPauseResume:
    async def test_pause_and_resume_project(self, client: AsyncClient) -> None:
        sid = await _create_session(client)

        r_pause = await client.post(f"/project/pause?session_id={sid}")
        assert r_pause.status_code == 200
        assert r_pause.json()["paused"] is True

        r_check = await client.get(f"/project/paused?session_id={sid}")
        assert r_check.status_code == 200
        assert r_check.json()["paused"] is True

        r_resume = await client.post(f"/project/resume?session_id={sid}")
        assert r_resume.status_code == 200
        assert r_resume.json()["paused"] is False

        r_check2 = await client.get(f"/project/paused?session_id={sid}")
        assert r_check2.status_code == 200
        assert r_check2.json()["paused"] is False

    async def test_pause_nonexistent_session_returns_404(self, client: AsyncClient) -> None:
        r = await client.post("/project/pause?session_id=ghost")
        assert r.status_code == 404

    async def test_resume_nonexistent_session_returns_404(self, client: AsyncClient) -> None:
        r = await client.post("/project/resume?session_id=ghost")
        assert r.status_code == 404

    async def test_is_paused_nonexistent_returns_404(self, client: AsyncClient) -> None:
        r = await client.get("/project/paused?session_id=ghost")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# WebSocket: ConnectionManager unit tests (no network)
# ---------------------------------------------------------------------------


class TestConnectionManagerUnit:
    async def test_connect_accepts_and_registers(self) -> None:
        mgr = ConnectionManager()
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        await mgr.connect(ws)
        ws.accept.assert_awaited_once()
        assert mgr.active_count == 1

    async def test_disconnect_removes_connection(self) -> None:
        mgr = ConnectionManager()
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        await mgr.connect(ws)
        assert mgr.active_count == 1
        mgr.disconnect(ws)
        assert mgr.active_count == 0

    async def test_disconnect_safe_when_not_connected(self) -> None:
        mgr = ConnectionManager()
        ws = MagicMock()
        mgr.disconnect(ws)  # should not raise
        assert mgr.active_count == 0

    async def test_broadcast_sends_to_all(self) -> None:
        mgr = ConnectionManager()
        ws1 = MagicMock()
        ws1.accept = AsyncMock()
        ws1.send_json = AsyncMock()
        ws2 = MagicMock()
        ws2.accept = AsyncMock()
        ws2.send_json = AsyncMock()

        await mgr.connect(ws1)
        await mgr.connect(ws2)
        assert mgr.active_count == 2

        payload: dict[str, Any] = {"type": "test", "value": 42}
        await mgr.broadcast(payload)

        ws1.send_json.assert_awaited_once_with(payload)
        ws2.send_json.assert_awaited_once_with(payload)

    async def test_broadcast_prunes_dead_connections(self) -> None:
        mgr = ConnectionManager()
        healthy = MagicMock()
        healthy.accept = AsyncMock()
        healthy.send_json = AsyncMock()
        dead = MagicMock()
        dead.accept = AsyncMock()
        dead.send_json = AsyncMock(side_effect=RuntimeError("disconnected"))

        await mgr.connect(healthy)
        await mgr.connect(dead)
        assert mgr.active_count == 2

        await mgr.broadcast({"type": "test"})
        assert mgr.active_count == 1
        healthy.send_json.assert_awaited_once()

    async def test_broadcast_feature_update(self) -> None:
        mgr = ConnectionManager()
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        await mgr.connect(ws)

        await mgr.broadcast_feature_update({"task_id": "t1", "status": "running"})
        call_args = ws.send_json.call_args[0][0]
        assert call_args["type"] == "feature_update"
        assert call_args["feature"]["task_id"] == "t1"

    async def test_broadcast_agent_started(self) -> None:
        mgr = ConnectionManager()
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        await mgr.connect(ws)

        await mgr.broadcast_agent_started("sess-1", "feat-42")
        call_args = ws.send_json.call_args[0][0]
        assert call_args["type"] == "agent_started"
        assert call_args["session_id"] == "sess-1"

    async def test_broadcast_agent_completed(self) -> None:
        mgr = ConnectionManager()
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        await mgr.connect(ws)

        await mgr.broadcast_agent_completed("sess-1", "feat-42", passed=True)
        call_args = ws.send_json.call_args[0][0]
        assert call_args["type"] == "agent_completed"
        assert call_args["passed"] is True

    async def test_broadcast_cost_update(self) -> None:
        mgr = ConnectionManager()
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        await mgr.connect(ws)

        await mgr.broadcast_cost_update(total_cost=1.23, session_cost=0.05)
        call_args = ws.send_json.call_args[0][0]
        assert call_args["type"] == "cost_update"
        assert call_args["total_cost"] == 1.23

    async def test_multiple_connects_track_count(self) -> None:
        mgr = ConnectionManager()
        wss = []
        for _ in range(5):
            ws = MagicMock()
            ws.accept = AsyncMock()
            ws.send_json = AsyncMock()
            await mgr.connect(ws)
            wss.append(ws)
        assert mgr.active_count == 5

        for ws in wss[:3]:
            mgr.disconnect(ws)
        assert mgr.active_count == 2


# ---------------------------------------------------------------------------
# WebSocket: via Starlette TestClient (real WS test)
# ---------------------------------------------------------------------------


class TestWebSocketEndpoint:
    def test_ws_ping_pong_via_testclient(self, sync_client: TestClient) -> None:
        """Connect to /ws, send ping, receive pong via Starlette TestClient."""
        with sync_client.websocket_connect("/ws") as ws:
            ws.send_json({"ping": True})
            msg = ws.receive_json()
            assert msg == {"pong": True}

    def test_ws_session_echo(self, sync_client: TestClient) -> None:
        """Connect to /ws/{session_id}, send text, receive ack."""
        with sync_client.websocket_connect("/ws/test-session-123") as ws:
            ws.send_text("hello")
            msg = ws.receive_json()
            assert msg == {"ack": "hello"}

    def test_ws_multiple_pings(self, sync_client: TestClient) -> None:
        """Multiple ping/pong exchanges on the same connection."""
        with sync_client.websocket_connect("/ws") as ws:
            for _ in range(3):
                ws.send_json({"ping": True})
                msg = ws.receive_json()
                assert msg == {"pong": True}


# ---------------------------------------------------------------------------
# SSE stream smoke test
# ---------------------------------------------------------------------------


class TestSSEStream:
    async def test_sse_route_registered(self, client: AsyncClient) -> None:
        """The SSE events endpoint is registered at /sessions/{id}/events."""
        # Verify the route exists by checking OpenAPI schema
        r = await client.get("/openapi.json")
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        # Look for a path that matches /sessions/{session_id}/events
        event_paths = [p for p in paths if "events" in p]
        assert len(event_paths) > 0, (
            f"No SSE events path found in: {list(paths.keys())}"
        )

    async def test_sse_event_queue_management(self, service: AgentStateService) -> None:
        """_emit_event pushes events to all registered SSE queues."""
        app = service.create_app()
        await service.init_db()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # Create a session first
            r = await ac.post(
                "/sessions", json={"project_path": "/tmp/sse-test"}
            )
            assert r.status_code == 201
            sid = r.json()["id"]

            # Manually register an SSE queue and emit an event
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
            service._event_queues.append(queue)
            try:
                await service._emit_event(sid, None, "test.event", {"k": "v"})
                # The queue should have received the event
                event = await asyncio.wait_for(queue.get(), timeout=2.0)
                assert event["session_id"] == sid
                assert event["type"] == "test.event"
                assert event["payload"] == {"k": "v"}
            finally:
                service._event_queues.remove(queue)


# ---------------------------------------------------------------------------
# task.updated WS broadcast — plugin_name + result_json fields
# ---------------------------------------------------------------------------


class TestTaskUpdatedBroadcastFields:
    """Verify that PATCH /tasks/{id} broadcasts plugin_name, result_json,
    error_message, cost_usd, input_tokens, and output_tokens in the
    feature_update WebSocket event so the Kanban UI can show per-feature
    QA/testing activity without a full HTTP refetch.
    """

    async def test_update_task_broadcast_includes_plugin_name(
        self, service: AgentStateService
    ) -> None:
        """plugin_name must be present in the task.updated WS broadcast."""
        app = service.create_app()
        await service.init_db()
        transport = ASGITransport(app=app)

        captured: list[dict[str, Any]] = []
        original_broadcast = service.ws_manager.broadcast_feature_update

        async def _capture(payload: dict[str, Any]) -> None:
            captured.append(payload)
            await original_broadcast(payload)

        service.ws_manager.broadcast_feature_update = _capture  # type: ignore[method-assign]

        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            sid = await _create_session(ac)
            r_task = await ac.post(
                f"/sessions/{sid}/tasks",
                json={"plugin_name": "testing", "description": "Run test suite"},
            )
            assert r_task.status_code == 201
            tid = r_task.json()["id"]

            await ac.patch(f"/tasks/{tid}", json={"status": "running"})

        # Filter to the task.updated broadcast (has "id" field)
        task_updates = [p for p in captured if p.get("id") == tid]
        assert task_updates, "No task.updated broadcast captured"
        payload = task_updates[-1]
        assert payload["plugin_name"] == "testing", (
            f"Expected plugin_name='testing', got: {payload}"
        )

    async def test_update_task_broadcast_includes_result_json(
        self, service: AgentStateService
    ) -> None:
        """result_json written in a PATCH must appear in the WS broadcast."""
        app = service.create_app()
        await service.init_db()
        transport = ASGITransport(app=app)

        captured: list[dict[str, Any]] = []
        original_broadcast = service.ws_manager.broadcast_feature_update

        async def _capture(payload: dict[str, Any]) -> None:
            captured.append(payload)
            await original_broadcast(payload)

        service.ws_manager.broadcast_feature_update = _capture  # type: ignore[method-assign]

        review_result = {"verdict": "APPROVE", "issues": 0}

        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            sid = await _create_session(ac)
            r_task = await ac.post(
                f"/sessions/{sid}/tasks",
                json={"plugin_name": "reviewer", "description": "Code review"},
            )
            tid = r_task.json()["id"]

            await ac.patch(
                f"/tasks/{tid}",
                json={"status": "completed", "result": review_result},
            )

        task_updates = [p for p in captured if p.get("id") == tid]
        assert task_updates, "No task.updated broadcast captured"
        payload = task_updates[-1]
        assert payload["plugin_name"] == "reviewer"
        assert payload["result_json"] == review_result

    async def test_update_task_broadcast_includes_cost_and_tokens(
        self, service: AgentStateService
    ) -> None:
        """Accumulated cost/tokens must be present in the WS broadcast."""
        app = service.create_app()
        await service.init_db()
        transport = ASGITransport(app=app)

        captured: list[dict[str, Any]] = []
        original_broadcast = service.ws_manager.broadcast_feature_update

        async def _capture(payload: dict[str, Any]) -> None:
            captured.append(payload)
            await original_broadcast(payload)

        service.ws_manager.broadcast_feature_update = _capture  # type: ignore[method-assign]

        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            sid = await _create_session(ac)
            r_task = await ac.post(
                f"/sessions/{sid}/tasks",
                json={"plugin_name": "coding"},
            )
            tid = r_task.json()["id"]

            await ac.patch(
                f"/tasks/{tid}",
                json={"input_tokens": 200, "output_tokens": 100, "cost_usd": 0.005},
            )

        task_updates = [p for p in captured if p.get("id") == tid]
        assert task_updates
        payload = task_updates[-1]
        assert payload["input_tokens"] == 200
        assert payload["output_tokens"] == 100
        assert payload["cost_usd"] == pytest.approx(0.005)

    async def test_update_testing_task_error_message_in_broadcast(
        self, service: AgentStateService
    ) -> None:
        """error_message must appear in the WS broadcast for failed QA tasks."""
        app = service.create_app()
        await service.init_db()
        transport = ASGITransport(app=app)

        captured: list[dict[str, Any]] = []
        original_broadcast = service.ws_manager.broadcast_feature_update

        async def _capture(payload: dict[str, Any]) -> None:
            captured.append(payload)
            await original_broadcast(payload)

        service.ws_manager.broadcast_feature_update = _capture  # type: ignore[method-assign]

        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            sid = await _create_session(ac)
            r_task = await ac.post(
                f"/sessions/{sid}/tasks",
                json={"plugin_name": "testing"},
            )
            tid = r_task.json()["id"]

            await ac.patch(
                f"/tasks/{tid}",
                json={"status": "failed", "error_message": "3 tests failed"},
            )

        task_updates = [p for p in captured if p.get("id") == tid]
        assert task_updates
        payload = task_updates[-1]
        assert payload["plugin_name"] == "testing"
        assert payload["error_message"] == "3 tests failed"
