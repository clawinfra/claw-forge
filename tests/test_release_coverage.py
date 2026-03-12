"""Coverage-targeted tests for release readiness.

Covers previously untested endpoints and branches in:
- state/service.py (stop endpoints, agent-log, pool/status YAML fallback, etc.)
- orchestrator/dispatcher.py (stop_reviewer, failed task recording, reviewer notify)
- mcp/feature_mcp.py (missing feature guards, feature_skip, get_summary, get_graph)
"""

from __future__ import annotations

import asyncio
import sys
import types
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import yaml
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession
from starlette.testclient import TestClient
from typer.testing import CliRunner

from claw_forge.state.service import AgentStateService, ConnectionManager

# Ensure claude_agent_sdk is available (may be stubbed in CI)
if "claude_agent_sdk" not in sys.modules:
    sys.modules["claude_agent_sdk"] = types.ModuleType("claude_agent_sdk")


# ---------------------------------------------------------------------------
# Service fixtures (mirrors test_backend_e2e.py)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def service() -> AgentStateService:
    svc = AgentStateService(database_url="sqlite+aiosqlite:///:memory:")
    await svc.init_db()
    yield svc  # type: ignore[misc]
    await svc.dispose()


@pytest_asyncio.fixture
async def client(service: AgentStateService) -> AsyncClient:
    app = service.create_app()
    await service.init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c  # type: ignore[misc]


@pytest.fixture
def sync_client(service: AgentStateService) -> TestClient:
    app = service.create_app()
    return TestClient(app, raise_server_exceptions=True)


async def _create_session(client: AsyncClient, project_path: str = "/tmp/test") -> str:
    r = await client.post("/sessions", json={"project_path": project_path})
    assert r.status_code == 201
    return r.json()["id"]


async def _create_task(
    client: AsyncClient, session_id: str, plugin: str = "coding"
) -> str:
    r = await client.post(
        f"/sessions/{session_id}/tasks",
        json={"plugin_name": plugin, "description": f"Task-{plugin}"},
    )
    assert r.status_code == 201
    return r.json()["id"]


# ===========================================================================
# 1) state/service.py — POST /tasks/{task_id}/agent-log  (lines 452-461)
# ===========================================================================


class TestAgentLogEndpoint:
    async def test_agent_log_ok(self, client: AsyncClient) -> None:
        r = await client.post(
            "/tasks/some-task-id/agent-log",
            json={"role": "assistant", "content": "Thinking..."},
        )
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    async def test_agent_log_with_task_name_and_model(self, client: AsyncClient) -> None:
        r = await client.post(
            "/tasks/abc123/agent-log",
            json={
                "role": "tool_use",
                "content": "read_file",
                "task_name": "Auth Feature",
                "level": "info",
                "model": "claude-sonnet-4-20250514",
            },
        )
        assert r.status_code == 200


# ===========================================================================
# 2) state/service.py — POST /tasks/{task_id}/stop  (lines 595-607)
# ===========================================================================


class TestStopTask:
    async def test_stop_pauses_task(
        self, client: AsyncClient, service: AgentStateService,
    ) -> None:
        sid = await _create_session(client)
        tid = await _create_task(client, sid)
        await client.patch(f"/tasks/{tid}", json={"status": "running"})

        r = await client.post(f"/tasks/{tid}/stop")
        assert r.status_code == 200
        assert r.json() == {"task_id": tid, "status": "paused"}
        assert tid in service._stop_requested

    async def test_stop_unknown_task_404(self, client: AsyncClient) -> None:
        r = await client.post("/tasks/ghost-id/stop")
        assert r.status_code == 404


# ===========================================================================
# 3) state/service.py — POST /sessions/{id}/tasks/stop-all  (lines 612-632)
# ===========================================================================


class TestStopAllTasks:
    async def test_stop_all_running(self, client: AsyncClient, service: AgentStateService) -> None:
        sid = await _create_session(client)
        tids = []
        for _ in range(3):
            tid = await _create_task(client, sid)
            await client.patch(f"/tasks/{tid}", json={"status": "running"})
            tids.append(tid)

        r = await client.post(f"/sessions/{sid}/tasks/stop-all")
        assert r.status_code == 200
        assert set(r.json()["stopped"]) == set(tids)
        for tid in tids:
            assert tid in service._stop_requested

    async def test_stop_all_no_running(self, client: AsyncClient) -> None:
        sid = await _create_session(client)
        await _create_task(client, sid)  # stays pending
        r = await client.post(f"/sessions/{sid}/tasks/stop-all")
        assert r.json()["stopped"] == []

    async def test_stop_all_only_running_not_pending(self, client: AsyncClient) -> None:
        sid = await _create_session(client)
        running = await _create_task(client, sid)
        _pending = await _create_task(client, sid, "testing")
        await client.patch(f"/tasks/{running}", json={"status": "running"})

        r = await client.post(f"/sessions/{sid}/tasks/stop-all")
        assert r.json()["stopped"] == [running]


# ===========================================================================
# 4) state/service.py — GET /stop-poll  (lines 642-644)
# ===========================================================================


class TestStopPoll:
    async def test_stop_poll_returns_and_clears(
        self, client: AsyncClient, service: AgentStateService
    ) -> None:
        service._stop_requested = {"task-a", "task-b"}
        r = await client.get("/stop-poll")
        assert r.status_code == 200
        assert set(r.json()["task_ids"]) == {"task-a", "task-b"}
        assert len(service._stop_requested) == 0

    async def test_stop_poll_empty(self, client: AsyncClient) -> None:
        r = await client.get("/stop-poll")
        assert r.json()["task_ids"] == []


# ===========================================================================
# 5) state/service.py — broadcast_agent_log  (line 137)
# ===========================================================================


class TestBroadcastAgentLog:
    @pytest.mark.asyncio
    async def test_agent_log_event_format(self) -> None:
        mgr = ConnectionManager()
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        await mgr.connect(ws)
        await mgr.broadcast_agent_log(
            "task-1", "Auth Feature", "assistant", "hello", "info", "claude-3",
        )
        payload = ws.send_json.call_args[0][0]
        assert payload["type"] == "agent_log"
        assert payload["task_id"] == "task-1"
        assert payload["model"] == "claude-3"


# ===========================================================================
# 6) state/service.py — create_app_from_env()  (lines 40-46)
# ===========================================================================


class TestCreateAppFromEnv:
    def test_creates_app_with_defaults(self) -> None:
        from claw_forge.state.service import create_app_from_env

        app = create_app_from_env()
        assert app.title == "claw-forge State Service"

    def test_uses_env_var(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("CLAW_FORGE_DB_URL", f"sqlite+aiosqlite:///{tmp_path}/env.db")
        from claw_forge.state.service import create_app_from_env

        app = create_app_from_env()
        assert app is not None


# ===========================================================================
# 7) state/service.py — GET /regression/status with run_count > 0  (line 736)
# ===========================================================================


class TestRegressionStatus:
    async def test_with_run_count(self, client: AsyncClient, service: AgentStateService) -> None:
        mock_reviewer = MagicMock()
        mock_reviewer.run_count = 3
        mock_last = MagicMock()
        mock_last.to_dict.return_value = {"passed": True, "failures": []}
        mock_reviewer.last_result = mock_last
        service._reviewer = mock_reviewer

        r = await client.get("/regression/status")
        assert r.status_code == 200
        data = r.json()
        assert data["run_count"] == 3
        assert data["has_test_command"] is True
        assert data["last_result"] == {"passed": True, "failures": []}

    async def test_with_run_count_no_last_result(
        self, client: AsyncClient, service: AgentStateService
    ) -> None:
        mock_reviewer = MagicMock()
        mock_reviewer.run_count = 1
        mock_reviewer.last_result = None
        service._reviewer = mock_reviewer

        r = await client.get("/regression/status")
        data = r.json()
        assert data["run_count"] == 1
        assert data["last_result"] is None


# ===========================================================================
# 8) state/service.py — GET /pool/status YAML fallback  (lines 758-806)
# ===========================================================================


class TestPoolStatusYAMLFallback:
    async def test_no_config_returns_inactive(
        self, service: AgentStateService,
    ) -> None:
        """No pool manager + no config → empty providers."""
        app = service.create_app()
        transport = ASGITransport(app=app)
        with patch.object(type(service), "_find_config_path", lambda self: None):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                r = await ac.get("/pool/status")
        assert r.status_code == 200
        data = r.json()
        assert data["providers"] == []
        assert data["active"] is False

    async def test_with_yaml_config(self, service: AgentStateService, tmp_path: Path) -> None:
        cfg = tmp_path / "claw-forge.yaml"
        cfg.write_text(
            yaml.dump(
                {
                    "pool": {"strategy": "round_robin"},
                    "providers": {
                        "my-provider": {
                            "type": "anthropic",
                            "priority": 1,
                            "enabled": True,
                            "max_rpm": 30,
                            "model": "claude-3",
                        }
                    },
                    "model_aliases": {"fast": "${FAST_MODEL:-claude-haiku-4-5}"},
                }
            )
        )

        app = service.create_app()
        transport = ASGITransport(app=app)
        with patch.object(type(service), "_find_config_path", lambda self: cfg):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                r = await ac.get("/pool/status")

        assert r.status_code == 200
        data = r.json()
        assert len(data["providers"]) == 1
        assert data["providers"][0]["name"] == "my-provider"
        assert data["model_aliases"]["fast"] == "claude-haiku-4-5"
        assert data["active"] is False
        assert data["strategy"] == "round_robin"

    async def test_yaml_exception_returns_empty(self, service: AgentStateService) -> None:
        bad_path = MagicMock()
        bad_path.read_text.side_effect = OSError("permission denied")
        app = service.create_app()
        transport = ASGITransport(app=app)
        with patch.object(type(service), "_find_config_path", lambda self: bad_path):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                r = await ac.get("/pool/status")
        assert r.json() == {"providers": [], "model_aliases": {}, "active": False}

    async def test_yaml_non_dict_provider_skipped(
        self, service: AgentStateService, tmp_path: Path
    ) -> None:
        cfg = tmp_path / "claw-forge.yaml"
        cfg.write_text(
            yaml.dump(
                {
                    "providers": {
                        "good": {"type": "anthropic", "enabled": True},
                        "bad": "not-a-dict",
                    }
                }
            )
        )
        app = service.create_app()
        transport = ASGITransport(app=app)
        with patch.object(type(service), "_find_config_path", lambda self: cfg):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                r = await ac.get("/pool/status")
        data = r.json()
        assert len(data["providers"]) == 1
        assert data["providers"][0]["name"] == "good"


# ===========================================================================
# 9) orchestrator/dispatcher.py — stop_reviewer  (lines 185-187)
# ===========================================================================


class TestDispatcherStopReviewer:
    @pytest.mark.asyncio
    async def test_stop_reviewer_when_set(self) -> None:
        from claw_forge.orchestrator.dispatcher import Dispatcher

        d = Dispatcher(handler=lambda t: {})
        mock_reviewer = MagicMock()
        mock_reviewer.stop = AsyncMock()
        d._reviewer = mock_reviewer
        await d.stop_reviewer()
        mock_reviewer.stop.assert_awaited_once()
        assert d._reviewer is None

    @pytest.mark.asyncio
    async def test_stop_reviewer_when_none(self) -> None:
        from claw_forge.orchestrator.dispatcher import Dispatcher

        d = Dispatcher(handler=lambda t: {})
        await d.stop_reviewer()  # should be a no-op


# ===========================================================================
# 10) orchestrator/dispatcher.py — failed task in result  (lines 246-247)
# ===========================================================================


class TestDispatcherFailedTask:
    @pytest.mark.asyncio
    async def test_failed_task_raises_exception_group(self) -> None:
        from claw_forge.orchestrator.dispatcher import Dispatcher, DispatcherConfig
        from claw_forge.state.scheduler import TaskNode

        async def _fail_handler(task: TaskNode) -> dict:
            raise RuntimeError("boom")

        cfg = DispatcherConfig(retry_attempts=1)
        d = Dispatcher(handler=_fail_handler, config=cfg)
        d.add_task(TaskNode("fail-task", "coding", 1, []))
        with pytest.raises(ExceptionGroup):
            await d.run()


# ===========================================================================
# 11) orchestrator/dispatcher.py — reviewer notification  (line 254)
# ===========================================================================


class TestDispatcherReviewerNotify:
    @pytest.mark.asyncio
    async def test_reviewer_notified_on_completion(self) -> None:
        from claw_forge.orchestrator.dispatcher import Dispatcher
        from claw_forge.state.scheduler import TaskNode

        async def _ok(task: TaskNode) -> dict:
            return {"status": "done"}

        d = Dispatcher(handler=_ok)
        d.add_task(TaskNode("t1", "coding", 1, []))
        mock_reviewer = MagicMock()
        mock_reviewer.notify_feature_completed = MagicMock()
        d._reviewer = mock_reviewer
        result = await d.run()
        assert result.all_succeeded
        mock_reviewer.notify_feature_completed.assert_called()


# ===========================================================================
# 12) orchestrator/dispatcher.py — CancelledError in handler  (lines 283-286)
# ===========================================================================


class TestDispatcherCancelled:
    @pytest.mark.asyncio
    async def test_cancelled_in_handler(self) -> None:
        from claw_forge.orchestrator.dispatcher import Dispatcher, DispatcherConfig
        from claw_forge.state.scheduler import TaskNode

        async def _cancel_handler(task: TaskNode) -> dict:
            raise asyncio.CancelledError()

        cfg = DispatcherConfig(retry_attempts=1)
        d = Dispatcher(handler=_cancel_handler, config=cfg)
        d.add_task(TaskNode("cancelled-task", "coding", 1, []))
        result = await d.run()
        # Cancelled tasks end up as completed with empty result
        assert "cancelled-task" in result.completed


# ===========================================================================
# 13) mcp/feature_mcp.py — feature_get_summary, feature_get_graph
# ===========================================================================


# Re-use fixture pattern from test_mcp_feature_server.py


def _make_mcp_engine():
    from claw_forge.mcp.feature_mcp import FeatureBase

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    FeatureBase.metadata.create_all(engine)
    return engine


@pytest.fixture
def mcp_engine(monkeypatch):
    _engine = _make_mcp_engine()
    monkeypatch.setattr("claw_forge.mcp.feature_mcp._get_engine", lambda: _engine)
    return _engine


@pytest.fixture
def mcp_features(mcp_engine):
    from claw_forge.mcp.feature_mcp import Feature

    features = []
    with DBSession(mcp_engine) as session:
        for i in range(3):
            f = Feature(
                id=str(uuid.uuid4()),
                name=f"Feature {i}",
                category="test",
                description=f"Desc {i}",
                steps=[f"Step {i}.1"],
                status="pending",
            )
            session.add(f)
            features.append(f)
        session.commit()
        for f in features:
            session.refresh(f)
        dicts = [f.to_dict() for f in features]
    return dicts


class TestFeatureGetSummary:
    def test_returns_list(self, mcp_engine, mcp_features) -> None:
        from claw_forge.mcp.feature_mcp import feature_get_summary

        result = feature_get_summary()
        assert len(result) == 3
        assert all("id" in r and "name" in r for r in result)

    def test_empty(self, mcp_engine) -> None:
        from claw_forge.mcp.feature_mcp import feature_get_summary

        result = feature_get_summary()
        assert result == []


class TestFeatureGetGraph:
    def test_returns_all(self, mcp_engine, mcp_features) -> None:
        from claw_forge.mcp.feature_mcp import feature_get_graph

        graph = feature_get_graph()
        assert len(graph) == 3

    def test_empty(self, mcp_engine) -> None:
        from claw_forge.mcp.feature_mcp import feature_get_graph

        assert feature_get_graph() == []


# ===========================================================================
# 14) mcp/feature_mcp.py — feature_skip  (lines 336-346)
# ===========================================================================


class TestFeatureSkip:
    def test_skip_marks_skipped(self, mcp_engine, mcp_features) -> None:
        from claw_forge.mcp.feature_mcp import feature_skip

        result = feature_skip(mcp_features[0]["id"])
        assert result is not None
        assert result["status"] == "skipped"

    def test_skip_missing_returns_none(self, mcp_engine) -> None:
        from claw_forge.mcp.feature_mcp import feature_skip

        assert feature_skip("nonexistent") is None


# ===========================================================================
# 15) mcp/feature_mcp.py — missing feature guards  (lines 275, 324, 425)
# ===========================================================================


class TestFeatureMissingGuards:
    def test_mark_in_progress_missing(self, mcp_engine) -> None:
        from claw_forge.mcp.feature_mcp import feature_mark_in_progress

        assert feature_mark_in_progress("nonexistent") is None

    def test_clear_in_progress_missing(self, mcp_engine) -> None:
        from claw_forge.mcp.feature_mcp import feature_clear_in_progress

        assert feature_clear_in_progress("nonexistent") is None

    def test_set_dependencies_missing(self, mcp_engine) -> None:
        from claw_forge.mcp.feature_mcp import feature_set_dependencies

        assert feature_set_dependencies("nonexistent", []) is False


# ===========================================================================
# 16) mcp/feature_mcp.py — duplicate dependency guard  (line 411)
# ===========================================================================


class TestFeatureDuplicateDep:
    def test_add_dependency_idempotent(self, mcp_engine) -> None:
        from claw_forge.mcp.feature_mcp import (
            feature_add_dependency,
            feature_create,
            feature_get_by_id,
        )

        a = feature_create(name="A")
        b = feature_create(name="B")
        feature_add_dependency(b["id"], a["id"])
        # Add same dep again
        result = feature_add_dependency(b["id"], a["id"])
        assert result is True
        detail = feature_get_by_id(b["id"])
        assert detail["depends_on"].count(a["id"]) == 1


# ===========================================================================
# 17) mcp/feature_mcp.py — _get_db_path  (lines 126-127)
# ===========================================================================


class TestGetDbPath:
    def test_default(self, monkeypatch) -> None:
        monkeypatch.delenv("PROJECT_DIR", raising=False)
        from claw_forge.mcp.feature_mcp import _get_db_path

        result = _get_db_path()
        assert result == Path(".") / ".claw-forge" / "state.db"

    def test_from_env(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
        from claw_forge.mcp.feature_mcp import _get_db_path

        result = _get_db_path()
        assert result == tmp_path / ".claw-forge" / "state.db"


# ===========================================================================
# 18) mcp/feature_mcp.py — _get_engine  (lines 131-135)
# ===========================================================================


class TestGetEngine:
    def test_creates_engine_and_tables(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
        from claw_forge.mcp.feature_mcp import _get_engine

        engine = _get_engine()
        assert engine is not None
        assert (tmp_path / ".claw-forge").exists()
        engine.dispose()


# ===========================================================================
# 19) state/service.py — _find_config_path fallback  (lines 259, 266-267)
# ===========================================================================


class TestFindConfigPath:
    def test_returns_none_when_absent(self) -> None:
        svc = AgentStateService(database_url="sqlite+aiosqlite:///:memory:")
        # _project_path from :memory: may resolve oddly; ensure no yaml found
        with patch.object(Path, "exists", return_value=False):
            result = svc._find_config_path()
        assert result is None

    def test_finds_in_project_dir(self, tmp_path: Path) -> None:
        db_dir = tmp_path / ".claw-forge"
        db_dir.mkdir()
        db_path = db_dir / "state.db"
        db_path.touch()
        (tmp_path / "claw-forge.yaml").write_text("pool: {}")

        svc = AgentStateService(
            database_url=f"sqlite+aiosqlite:///{db_path}"
        )
        result = svc._find_config_path()
        assert result == tmp_path / "claw-forge.yaml"


# ===========================================================================
# 20) state/service.py — update_task started_at guard  (line 423->425)
# ===========================================================================


class TestUpdateTaskStartedAt:
    async def test_running_twice_preserves_started_at(self, client: AsyncClient) -> None:
        sid = await _create_session(client)
        tid = await _create_task(client, sid)
        await client.patch(f"/tasks/{tid}", json={"status": "running"})
        tasks = (await client.get(f"/sessions/{sid}/tasks")).json()
        first_started = tasks[0]["started_at"]
        assert first_started is not None

        await client.patch(f"/tasks/{tid}", json={"status": "running"})
        tasks = (await client.get(f"/sessions/{sid}/tasks")).json()
        second_started = tasks[0]["started_at"]
        assert first_started == second_started


# ===========================================================================
# 21) dispatcher.py — start_reviewer  (lines 173-181)
# ===========================================================================


class TestDispatcherStartReviewer:
    @pytest.mark.asyncio
    async def test_start_reviewer(self) -> None:
        from claw_forge.orchestrator.dispatcher import Dispatcher
        from claw_forge.state.scheduler import TaskNode

        async def _noop(t: TaskNode) -> dict:
            return {}

        d = Dispatcher(handler=_noop)
        mock_state = MagicMock()
        mock_reviewer = MagicMock()
        mock_reviewer.start = AsyncMock()

        # ParallelReviewer is imported inside start_reviewer body
        with patch(
            "claw_forge.orchestrator.reviewer.ParallelReviewer",
            return_value=mock_reviewer,
        ):
            await d.start_reviewer("/tmp/proj", mock_state, interval_features=5)

        assert d._reviewer is mock_reviewer
        mock_reviewer.start.assert_awaited_once()
        assert mock_state._reviewer is mock_reviewer


# ===========================================================================
# 22) spec/parser.py — XML features with <steps>  (lines 170-182)
# ===========================================================================


class TestXMLFeaturesWithSteps:
    def test_xml_features_with_steps_element(self) -> None:
        import textwrap

        from claw_forge.spec.parser import ProjectSpec

        xml = textwrap.dedent("""\
            <project_specification>
              <project_name>step-test</project_name>
              <overview>Test steps parsing</overview>
              <core_features>
                <auth>
                  <feature>
                    <description>User login with OAuth</description>
                    <steps>
- Configure OAuth provider
- Add callback route
- Store tokens
                    </steps>
                  </feature>
                  <feature>
                    <description>Session management</description>
                  </feature>
                </auth>
              </core_features>
            </project_specification>
        """)
        spec = ProjectSpec._parse_xml(xml)
        assert len(spec.features) == 2
        assert spec.features[0].name.startswith("User login with OAuth")
        assert len(spec.features[0].steps) == 3
        assert "Configure OAuth provider" in spec.features[0].steps[0]
        assert spec.features[1].steps == []

    def test_xml_empty_description_skipped(self) -> None:
        import textwrap

        from claw_forge.spec.parser import ProjectSpec

        xml = textwrap.dedent("""\
            <project_specification>
              <project_name>empty-desc</project_name>
              <core_features>
                <auth>
                  <feature>
                    <description>  </description>
                  </feature>
                  <feature>
                    <description>Valid feature</description>
                  </feature>
                </auth>
              </core_features>
            </project_specification>
        """)
        spec = ProjectSpec._parse_xml(xml)
        assert len(spec.features) == 1


# ===========================================================================
# 23) spec/parser.py — flat features_to_add  (lines 214-229)
# ===========================================================================


class TestXMLFeaturesAsCategories:
    def test_features_to_add_as_categories(self) -> None:
        import textwrap

        from claw_forge.spec.parser import ProjectSpec

        xml = textwrap.dedent("""\
            <project_specification>
              <project_name>brownfield-nested</project_name>
              <features_to_add>
                <auth>
                  - Add login
                  - Add logout
                </auth>
              </features_to_add>
            </project_specification>
        """)
        spec = ProjectSpec._parse_xml(xml)
        assert len(spec.features) == 2
        assert all(f.category == "Auth" for f in spec.features)


# ===========================================================================
# 24) spec/parser.py — brownfield phases  (lines 248-259)
# ===========================================================================


class TestXMLBrownfieldPhases:
    def test_brownfield_phases_parsed(self) -> None:
        import textwrap

        from claw_forge.spec.parser import ProjectSpec

        xml = textwrap.dedent("""\
            <project_specification>
              <project_name>phase-test</project_name>
              <core_features>
                <auth>
                  - Login feature
                </auth>
              </core_features>
              <implementation_steps>
                <phase name="Phase 1">
Login feature
                </phase>
              </implementation_steps>
            </project_specification>
        """)
        spec = ProjectSpec._parse_xml(xml)
        assert "Phase 1" in spec.implementation_phases


# ===========================================================================
# 25) spec/parser.py — text parser edge cases  (lines 414, 418-419, 448)
# ===========================================================================


class TestTextParserEdgeCases:
    def test_bullet_under_section_header(self) -> None:
        from claw_forge.spec.parser import ProjectSpec

        text = """\
Project: BulletTest
Stack: Python

Authentication:
- Login endpoint
- Token refresh

Dashboard:
- Real-time stats
"""
        spec = ProjectSpec._parse_plain_text(text)
        assert len(spec.features) == 3
        auth_features = [f for f in spec.features if f.category == "Authentication"]
        assert len(auth_features) == 2

    def test_empty_bullet_skipped(self) -> None:
        from claw_forge.spec.parser import ProjectSpec

        text = """\
Project: Empty
Features:
- Valid feature
-
- Another valid
"""
        spec = ProjectSpec._parse_plain_text(text)
        # Empty bullet "- " with nothing after should be skipped (line 414)
        names = [f.name for f in spec.features]
        assert "Valid feature" in names
        assert "Another valid" in names

    def test_numbered_then_section_header(self) -> None:
        """Numbered feature followed by section header flushes current."""
        from claw_forge.spec.parser import ProjectSpec

        text = """\
Project: MixedTest
1. First feature
   - Step 1
   - Step 2

Auth:
- Login
"""
        spec = ProjectSpec._parse_plain_text(text)
        # Should have the numbered feature + the section bullet
        assert len(spec.features) == 2
        assert spec.features[0].name == "First feature"
        assert len(spec.features[0].steps) == 2

    def test_description_line_after_numbered(self) -> None:
        """Non-key non-bullet line inside numbered feature is description."""
        from claw_forge.spec.parser import ProjectSpec

        text = """\
1. User Authentication
   Handles login and registration
   - Step: set up routes
"""
        spec = ProjectSpec._parse_plain_text(text)
        assert len(spec.features) == 1
        assert spec.features[0].description == "Handles login and registration"


# ===========================================================================
# 26) spec/parser.py — success_criteria flat text (line 276-281)
# ===========================================================================


class TestXMLSuccessCriteriaFlat:
    def test_flat_success_criteria(self) -> None:
        import textwrap

        from claw_forge.spec.parser import ProjectSpec

        xml = textwrap.dedent("""\
            <project_specification>
              <project_name>criteria-test</project_name>
              <success_criteria>
All tests pass
Coverage above 90%
              </success_criteria>
            </project_specification>
        """)
        spec = ProjectSpec._parse_xml(xml)
        assert "All tests pass" in spec.success_criteria
        assert "Coverage above 90%" in spec.success_criteria


# ===========================================================================
# 27) cli.py — _migrate_schema  (lines 1091-1108)
# ===========================================================================


class TestMigrateSchema:
    @pytest.mark.asyncio
    async def test_idempotent(self) -> None:
        from sqlalchemy.ext.asyncio import create_async_engine

        from claw_forge.cli import _migrate_schema
        from claw_forge.state.models import Base

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        # Call twice — second call should not raise
        await _migrate_schema(engine)
        await _migrate_schema(engine)
        await engine.dispose()


# ===========================================================================
# 28) cli.py — _write_plan_to_db  (lines 1111-1175)
# ===========================================================================


class TestWritePlanToDb:
    @pytest.mark.asyncio
    async def test_creates_tasks(self, tmp_path: Path) -> None:
        from claw_forge.cli import _write_plan_to_db

        features = [
            {
                "index": 0,
                "name": "F1",
                "description": "Do F1",
                "category": "core",
                "steps": [],
                "depends_on_indices": [],
            },
            {
                "index": 1,
                "name": "F2",
                "description": "Do F2",
                "category": "core",
                "steps": ["s1"],
                "depends_on_indices": [0],
            },
        ]
        await _write_plan_to_db(tmp_path, "test-project", features)
        db = tmp_path / ".claw-forge" / "state.db"
        assert db.exists()
        import sqlite3

        with sqlite3.connect(str(db)) as conn:
            rows = conn.execute("SELECT id, description FROM tasks").fetchall()
        # One coding task per feature
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_empty_features(self, tmp_path: Path) -> None:
        from claw_forge.cli import _write_plan_to_db

        await _write_plan_to_db(tmp_path, "empty-proj", [])
        db = tmp_path / ".claw-forge" / "state.db"
        assert db.exists()


# ===========================================================================
# 29) cli.py — _ensure_state_service port scanning  (lines 1640-1662)
# ===========================================================================


class TestEnsureStateServicePortScan:
    def test_all_ports_occupied_raises(self, tmp_path: Path) -> None:
        """All 5 ports occupied → raises RuntimeError."""
        import socket

        from claw_forge.cli import _ensure_state_service

        sockets = []
        try:
            # Bind 5 consecutive ports
            base_port = 0
            for i in range(5):
                s = socket.socket()
                s.bind(("127.0.0.1", 0))
                s.listen(1)
                if i == 0:
                    base_port = s.getsockname()[1]
                sockets.append(s)

            # The ports aren't consecutive, so this won't easily trigger.
            # Instead, mock _listening to return True for all port+0..port+4
            with (
                patch("urllib.request.urlopen", side_effect=Exception("no info")),
                patch(
                    "socket.create_connection",
                    side_effect=lambda addr, **kw: MagicMock(
                        __enter__=lambda s: s,
                        __exit__=MagicMock(return_value=False),
                    ),
                ),
                pytest.raises(RuntimeError, match="Port.*occupied"),
            ):
                _ensure_state_service(tmp_path, base_port)
        finally:
            for s in sockets:
                s.close()


# ===========================================================================
# 30) cli.py — _load_env_file and _expand_env_vars  (test a few more branches)
# ===========================================================================


class TestLoadEnvFile:
    def test_load_env_file_exists(self, tmp_path: Path) -> None:
        from claw_forge.cli import _load_env_file

        env_file = tmp_path / ".env"
        env_file.write_text("TEST_VAR=hello\nOTHER=world\n")
        _load_env_file(tmp_path)
        import os

        assert os.environ.get("TEST_VAR") == "hello"
        assert os.environ.get("OTHER") == "world"

    def test_load_env_file_missing(self, tmp_path: Path) -> None:
        from claw_forge.cli import _load_env_file

        # Should not raise when .env doesn't exist
        _load_env_file(tmp_path)


class TestExpandEnvVars:
    def test_basic_expansion(self) -> None:
        import os

        from claw_forge.cli import _expand_env_vars
        os.environ["TEST_EXPAND"] = "expanded"
        result = _expand_env_vars("${TEST_EXPAND:-default}")
        assert result == "expanded"

    def test_default_value(self) -> None:
        import os

        from claw_forge.cli import _expand_env_vars
        os.environ.pop("NONEXISTENT_VAR_XYZ", None)
        result = _expand_env_vars("${NONEXISTENT_VAR_XYZ:-fallback}")
        assert result == "fallback"


# ===========================================================================
# 31) state/service.py — toggle_provider no config  (line 830)
# ===========================================================================


class TestToggleProviderNoConfig:
    async def test_toggle_no_config_422(self, service: AgentStateService) -> None:
        app = service.create_app()
        transport = ASGITransport(app=app)
        with patch.object(type(service), "_find_config_path", lambda self: None):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                r = await ac.patch(
                    "/pool/providers/alpha",
                    json={"enabled": False},
                )
        assert r.status_code == 422


# ===========================================================================
# 32) state/service.py — regression_status with run_count=0 and reviewer
#     (line 736 — the run_count==0 + has reviewer path)
# ===========================================================================


# ===========================================================================
# Extra: __init__.py exception path (lines 7-8)
# ===========================================================================


class TestInitVersionFallback:
    def test_fallback_when_not_installed(self) -> None:
        with patch(
            "importlib.metadata.version",
            side_effect=Exception("not installed"),
        ):
            import importlib

            import claw_forge

            importlib.reload(claw_forge)
            assert claw_forge.__version__ == "0.4.1"
            # Reload again to restore original
            importlib.reload(claw_forge)



# ===========================================================================
# Extra: permissions.py — write outside project dir  (lines 132-133)
# ===========================================================================


# ===========================================================================
# Extra: tracker.py — get_rpm with actual timestamps (lines 75-76)
# ===========================================================================


class TestTrackerRPM:
    def test_rpm_with_timestamps(self) -> None:
        from claw_forge.pool.tracker import UsageTracker

        tracker = UsageTracker()
        tracker.record_request(
            provider_name="test-prov",
            input_tokens=10,
            output_tokens=5,
            cost_input_per_mtok=1.0,
            cost_output_per_mtok=1.0,
            latency_ms=50.0,
        )
        # Should count at least 1 request in last 60s
        assert tracker.get_rpm("test-prov") >= 1

    def test_rpm_unknown_provider(self) -> None:
        from claw_forge.pool.tracker import UsageTracker

        tracker = UsageTracker()
        assert tracker.get_rpm("no-such") == 0


# ===========================================================================
# Extra: router.py — default return path (line 80)
# ===========================================================================


class TestRouterDefaultReturn:
    def test_unknown_strategy_returns_available(self) -> None:
        from claw_forge.pool.health import CircuitBreaker
        from claw_forge.pool.router import Router, RoutingStrategy

        router = Router(strategy=RoutingStrategy.PRIORITY)
        # Manually set an unrecognised strategy value to hit the default return
        router.strategy = "UNKNOWN"  # type: ignore[assignment]
        # Create a minimal provider mock
        prov = MagicMock()
        prov.name = "p1"
        prov.config.enabled = True
        prov.config.priority = 1
        prov.config.max_rpm = 0
        tracker_mock = MagicMock()
        tracker_mock.is_rate_limited = MagicMock(return_value=False)
        cb = CircuitBreaker(name="p1", failure_threshold=5, recovery_timeout=60)
        result = router.select([prov], {"p1": cb}, tracker_mock)
        assert len(result) == 1


# ===========================================================================
# Extra: scheduler.py — mark_failed for unknown task (line 106)
# ===========================================================================


class TestSchedulerMarkFailed:
    def test_mark_failed_unknown_task(self) -> None:
        from claw_forge.state.scheduler import Scheduler

        s = Scheduler()
        # Should not raise for unknown task
        s.mark_failed("nonexistent-task")


class TestRegressionStatusRunCount0:
    async def test_run_count_0_with_reviewer(
        self, client: AsyncClient, service: AgentStateService
    ) -> None:
        mock_reviewer = MagicMock()
        mock_reviewer.run_count = 0
        service._reviewer = mock_reviewer
        r = await client.get("/regression/status")
        data = r.json()
        assert data["run_count"] == 0
        assert data["has_test_command"] is True
        assert data["last_result"] is None


# ===========================================================================
# 33) cli.py — init with existing spec file  (lines 1083-1085)
# ===========================================================================


class TestInitWithExistingSpec:
    def test_init_shows_spec_found(self, tmp_path: Path) -> None:
        from claw_forge.cli import app

        (tmp_path / "app_spec.txt").write_text("some spec")
        mock_scaffold = {
            "claude_md_written": False,
            "dot_claude_created": False,
            "spec_example_written": False,
            "commands_copied": [],
            "stack": {"language": "python", "framework": "unknown"},
            "git_initialized": False,
        }
        runner_cli = CliRunner()
        with patch("claw_forge.scaffold.scaffold_project", return_value=mock_scaffold):
            result = runner_cli.invoke(app, ["init", "--project", str(tmp_path)])
        assert result.exit_code == 0
        assert "Spec found" in result.output or "claw-forge plan" in result.output


# ===========================================================================
# 34) cli.py — plan failure path  (lines 1304-1306)
# ===========================================================================


class TestPlanFailure:
    def test_plan_fails_gracefully(self, tmp_path: Path) -> None:
        from claw_forge.cli import app

        spec_path = tmp_path / "spec.xml"
        spec_path.write_text(
            '<?xml version="1.0"?>\n'
            "<project_specification>\n"
            "  <project_name>test</project_name>\n"
            "</project_specification>\n"
        )
        cfg_path = tmp_path / "claw-forge.yaml"
        cfg_path.write_text("project: test\nproviders: {}\n")

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.output = "parsing error"

        runner_cli = CliRunner()
        with patch("claw_forge.cli.asyncio.run", return_value=mock_result):
            result = runner_cli.invoke(
                app,
                ["plan", str(spec_path), "--config", str(cfg_path), "--project", str(tmp_path)],
            )
        assert result.exit_code != 0
        assert "Planning failed" in result.output or "failed" in result.output.lower()


# ===========================================================================
# 35) cli.py — plan with phases in metadata  (lines 1288-1290)
# ===========================================================================


class TestPlanWithPhases:
    def test_plan_shows_phases(self, tmp_path: Path) -> None:
        from claw_forge.cli import app

        spec_path = tmp_path / "spec.xml"
        spec_path.write_text(
            '<?xml version="1.0"?>\n'
            "<project_specification>\n"
            "  <project_name>test</project_name>\n"
            "</project_specification>\n"
        )
        cfg_path = tmp_path / "claw-forge.yaml"
        cfg_path.write_text("project: test\nproviders: {}\n")

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "done"
        mock_result.metadata = {
            "project_name": "test",
            "feature_count": 2,
            "phases": ["Phase 1", "Phase 2"],
        }

        runner_cli = CliRunner()
        with patch("claw_forge.cli.asyncio.run", return_value=mock_result):
            result = runner_cli.invoke(
                app,
                ["plan", str(spec_path), "--config", str(cfg_path), "--project", str(tmp_path)],
            )
        assert result.exit_code == 0
        assert "Phase 1" in result.output or "feature" in result.output.lower()


# ===========================================================================
# 36) cli.py — plan no feature_count in meta  (lines 1300-1303)
# ===========================================================================


class TestPlanNoFeatureCount:
    def test_plan_no_feature_count(self, tmp_path: Path) -> None:
        from claw_forge.cli import app

        spec_path = tmp_path / "spec.xml"
        spec_path.write_text(
            '<?xml version="1.0"?>\n'
            "<project_specification>\n"
            "  <project_name>test</project_name>\n"
            "</project_specification>\n"
        )
        cfg_path = tmp_path / "claw-forge.yaml"
        cfg_path.write_text("project: test\nproviders: {}\n")

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "done"
        mock_result.metadata = {"project_name": "test", "custom": "val"}

        runner_cli = CliRunner()
        with patch("claw_forge.cli.asyncio.run", return_value=mock_result):
            result = runner_cli.invoke(
                app,
                ["plan", str(spec_path), "--config", str(cfg_path), "--project", str(tmp_path)],
            )
        assert result.exit_code == 0
        assert "Plan complete" in result.output or "complete" in result.output.lower()
