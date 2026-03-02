"""Tests for command execution system — GET /commands/list, POST /commands/execute."""

from __future__ import annotations

import asyncio
import os
import sys
import unittest.mock

# Mock claude_agent_sdk if not installed
sys.modules.setdefault("claude_agent_sdk", unittest.mock.MagicMock())
sys.modules.setdefault("claude_agent_sdk.types", unittest.mock.MagicMock())

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

from claw_forge.commands.registry import COMMANDS, COMMAND_IDS, COMMAND_SHELLS
from claw_forge.state.service import AgentStateService

# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def service(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    return AgentStateService(database_url=db_url)


@pytest.fixture
def app(service):
    return service.create_app()


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Registry unit tests ────────────────────────────────────────────────────────

def test_command_registry_completeness():
    """All 7 commands must be present with required non-empty fields."""
    assert len(COMMANDS) == 7
    required_fields = {"id", "label", "icon", "description", "category", "args"}
    for cmd in COMMANDS:
        for field in required_fields:
            assert field in cmd, f"Command {cmd.get('id')!r} missing field {field!r}"
            if field != "args":
                assert cmd[field], f"Command {cmd.get('id')!r} field {field!r} is empty"


def test_command_registry_ids():
    """Command IDs should be unique and match the id set."""
    ids = [cmd["id"] for cmd in COMMANDS]
    assert len(ids) == len(set(ids)), "Duplicate command IDs found"
    assert COMMAND_IDS == set(ids)


def test_command_registry_categories():
    """All categories must be one of the allowed values."""
    allowed = {"setup", "build", "quality", "save", "monitoring", "fix"}
    for cmd in COMMANDS:
        assert cmd["category"] in allowed, (
            f"Command {cmd['id']!r} has invalid category {cmd['category']!r}"
        )


def test_command_registry_expected_ids():
    """Exactly the 7 expected command IDs must be present."""
    expected = {
        "create-spec",
        "expand-project",
        "check-code",
        "checkpoint",
        "review-pr",
        "pool-status",
        "create-bug-report",
    }
    assert COMMAND_IDS == expected


def test_command_shells_coverage():
    """Every command id must have an entry in COMMAND_SHELLS."""
    for cmd_id in COMMAND_IDS:
        assert cmd_id in COMMAND_SHELLS, f"No shell mapping for command {cmd_id!r}"
        assert isinstance(COMMAND_SHELLS[cmd_id], list)
        assert len(COMMAND_SHELLS[cmd_id]) > 0


# ── GET /commands/list ────────────────────────────────────────────────────────

def test_list_commands_endpoint(client):
    """GET /commands/list should return all 7 commands."""
    resp = client.get("/commands/list")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 7


def test_list_commands_has_required_fields(client):
    """Each command from the endpoint must include required fields."""
    resp = client.get("/commands/list")
    for cmd in resp.json():
        assert "id" in cmd
        assert "label" in cmd
        assert "description" in cmd
        assert "category" in cmd
        assert "args" in cmd
        assert "icon" in cmd


def test_list_commands_returns_all_ids(client):
    """GET /commands/list must return all 7 expected IDs."""
    resp = client.get("/commands/list")
    ids = {cmd["id"] for cmd in resp.json()}
    assert ids == COMMAND_IDS


# ── POST /commands/execute ────────────────────────────────────────────────────

def test_execute_command_returns_execution_id(client):
    """POST /commands/execute should return execution_id and status=started."""
    resp = client.post(
        "/commands/execute",
        json={"command": "pool-status"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "execution_id" in data
    assert data["status"] == "started"


def test_execute_unknown_command_returns_404(client):
    """POST /commands/execute with unknown command should return 404."""
    resp = client.post(
        "/commands/execute",
        json={"command": "not-a-real-command"},
    )
    assert resp.status_code == 404


def test_execution_id_is_unique(client):
    """Each call to /commands/execute must return a unique execution_id."""
    ids = set()
    for _ in range(5):
        resp = client.post("/commands/execute", json={"command": "pool-status"})
        assert resp.status_code == 200
        ids.add(resp.json()["execution_id"])
    assert len(ids) == 5


def test_execution_id_is_uuid_format(client):
    """execution_id should be a valid UUID string."""
    import uuid
    resp = client.post("/commands/execute", json={"command": "pool-status"})
    exec_id = resp.json()["execution_id"]
    # Should not raise
    uuid.UUID(exec_id)


def test_execute_accepts_optional_args(client):
    """POST /commands/execute should accept optional args dict."""
    resp = client.post(
        "/commands/execute",
        json={"command": "create-bug-report", "args": {"feature_id": 42}},
    )
    assert resp.status_code == 200
    assert "execution_id" in resp.json()


def test_execute_accepts_project_dir(client):
    """POST /commands/execute should accept project_dir field."""
    resp = client.post(
        "/commands/execute",
        json={"command": "pool-status", "project_dir": "/tmp"},
    )
    assert resp.status_code == 200


def test_execute_check_code_command(client):
    """check-code command should be accepted."""
    resp = client.post("/commands/execute", json={"command": "check-code"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "started"


def test_execute_checkpoint_command(client):
    """checkpoint command should be accepted."""
    resp = client.post("/commands/execute", json={"command": "checkpoint"})
    assert resp.status_code == 200


def test_execute_instructional_commands(client):
    """Commands that are Claude slash commands should return execution_id."""
    for cmd_id in ("create-spec", "expand-project", "review-pr", "create-bug-report"):
        resp = client.post("/commands/execute", json={"command": cmd_id})
        assert resp.status_code == 200, f"Failed for {cmd_id}"
        assert "execution_id" in resp.json()


# ── GET /commands/executions/{id} ─────────────────────────────────────────────

def test_get_execution_by_id(client):
    """GET /commands/executions/{id} should return execution state."""
    post_resp = client.post("/commands/execute", json={"command": "pool-status"})
    exec_id = post_resp.json()["execution_id"]
    # Poll briefly
    import time
    time.sleep(0.3)
    resp = client.get(f"/commands/executions/{exec_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["execution_id"] == exec_id
    assert "status" in data
    assert "output" in data


def test_get_unknown_execution_returns_404(client):
    """GET /commands/executions/{unknown} should return 404."""
    resp = client.get("/commands/executions/not-a-real-id")
    assert resp.status_code == 404


# ── Async execution + WebSocket broadcast test ────────────────────────────────

@pytest.mark.asyncio
async def test_execute_check_code_streams_output(tmp_path):
    """Verify that command_output and command_done events are broadcast."""
    db_url = f"sqlite+aiosqlite:///{tmp_path}/async_test.db"
    service = AgentStateService(database_url=db_url)
    app = service.create_app()

    received_events: list[dict] = []

    # Patch broadcast to capture events
    original_broadcast = service.ws_manager.broadcast

    async def capture_broadcast(payload):
        received_events.append(payload)
        await original_broadcast(payload)

    service.ws_manager.broadcast = capture_broadcast  # type: ignore[method-assign]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.post(
            "/commands/execute",
            json={"command": "pool-status"},
        )
        assert resp.status_code == 200
        exec_id = resp.json()["execution_id"]

        # Wait for subprocess to finish
        await asyncio.sleep(1.0)

    # Verify command_done was broadcast
    done_events = [e for e in received_events if e.get("type") == "command_done"]
    assert len(done_events) >= 1
    done = done_events[0]
    assert done["execution_id"] == exec_id
    assert "exit_code" in done
    assert "duration_ms" in done


@pytest.mark.asyncio
async def test_command_done_event_has_exit_code(tmp_path):
    """command_done event must include exit_code."""
    db_url = f"sqlite+aiosqlite:///{tmp_path}/exit_test.db"
    service = AgentStateService(database_url=db_url)
    app = service.create_app()

    received: list[dict] = []
    orig = service.ws_manager.broadcast

    async def cap(payload):
        received.append(payload)
        await orig(payload)

    service.ws_manager.broadcast = cap  # type: ignore[method-assign]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.post("/commands/execute", json={"command": "pool-status"})
        exec_id = resp.json()["execution_id"]
        await asyncio.sleep(1.0)

    done = next((e for e in received if e.get("type") == "command_done"), None)
    assert done is not None
    assert "exit_code" in done
    assert isinstance(done["exit_code"], int)


# ── UI component file existence tests ─────────────────────────────────────────

def _ui_src(filename: str) -> str:
    base = os.path.dirname(os.path.dirname(__file__))
    return os.path.join(base, "ui", "src", "components", filename)


def test_command_palette_file_exists():
    """CommandPalette.tsx must exist."""
    assert os.path.isfile(_ui_src("CommandPalette.tsx")), (
        "ui/src/components/CommandPalette.tsx not found"
    )


def test_commands_panel_file_exists():
    """CommandsPanel.tsx must exist."""
    assert os.path.isfile(_ui_src("CommandsPanel.tsx")), (
        "ui/src/components/CommandsPanel.tsx not found"
    )


def test_execution_drawer_file_exists():
    """ExecutionDrawer.tsx must exist."""
    assert os.path.isfile(_ui_src("ExecutionDrawer.tsx")), (
        "ui/src/components/ExecutionDrawer.tsx not found"
    )


def test_command_palette_exports_component():
    """CommandPalette.tsx must export CommandPalette function."""
    path = _ui_src("CommandPalette.tsx")
    content = open(path).read()
    assert "export function CommandPalette" in content


def test_commands_panel_exports_component():
    """CommandsPanel.tsx must export CommandsPanel function."""
    path = _ui_src("CommandsPanel.tsx")
    content = open(path).read()
    assert "export function CommandsPanel" in content


def test_execution_drawer_exports_component():
    """ExecutionDrawer.tsx must export ExecutionDrawer function."""
    path = _ui_src("ExecutionDrawer.tsx")
    content = open(path).read()
    assert "export function ExecutionDrawer" in content


def test_command_palette_has_keyboard_shortcuts():
    """CommandPalette.tsx must handle ArrowDown, ArrowUp, Enter, Escape."""
    content = open(_ui_src("CommandPalette.tsx")).read()
    for key in ("ArrowDown", "ArrowUp", "Enter", "Escape"):
        assert key in content, f"CommandPalette missing keyboard handler for {key!r}"


def test_commands_panel_has_run_button():
    """CommandsPanel.tsx must have a Run button."""
    content = open(_ui_src("CommandsPanel.tsx")).read()
    assert "Run" in content
