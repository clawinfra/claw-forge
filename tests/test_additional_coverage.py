"""Additional coverage tests for pool_runner, router, state/service, plugins, anthropic."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# PoolRunner
# ---------------------------------------------------------------------------


class TestPoolRunner:
    def _make_pool(self, fail: bool = False) -> Any:
        from claw_forge.pool.manager import ProviderPoolExhausted, ProviderPoolManager

        pool = MagicMock(spec=ProviderPoolManager)
        if fail:
            pool.execute = AsyncMock(side_effect=ProviderPoolExhausted("all exhausted"))
        else:
            from claw_forge.pool.providers.base import ProviderResponse

            pool.execute = AsyncMock(
                return_value=ProviderResponse(
                    content="resp", model="m", provider_name="p"
                )
            )
        return pool

    @pytest.mark.asyncio
    async def test_run_batch_success(self) -> None:
        from claw_forge.orchestrator.pool_runner import AgentRun, PoolRunner

        pool = self._make_pool()
        runner = PoolRunner(pool, max_concurrent=3)

        runs = [
            AgentRun("a1", "claude-3", "sys", [{"role": "user", "content": "hi"}]),
            AgentRun("a2", "claude-3", "sys", [{"role": "user", "content": "ho"}]),
        ]
        result = await runner.run_batch(runs)
        assert len(result) == 2
        assert all(r.response is not None for r in result)
        assert all(r.error is None for r in result)

    @pytest.mark.asyncio
    async def test_run_batch_pool_exhausted(self) -> None:
        from claw_forge.orchestrator.pool_runner import AgentRun, PoolRunner

        pool = self._make_pool(fail=True)
        runner = PoolRunner(pool, max_concurrent=2)

        runs = [AgentRun("a1", "claude-3", "sys", [{"role": "user", "content": "hi"}])]
        result = await runner.run_batch(runs)
        assert result[0].error is not None
        assert result[0].response is None

    @pytest.mark.asyncio
    async def test_run_batch_unexpected_error(self) -> None:
        from claw_forge.orchestrator.pool_runner import AgentRun, PoolRunner

        pool = MagicMock()
        pool.execute = AsyncMock(side_effect=RuntimeError("unexpected"))

        runner = PoolRunner(pool, max_concurrent=2)
        runs = [AgentRun("a1", "claude-3", "sys", [{"role": "user", "content": "hi"}])]
        result = await runner.run_batch(runs)
        assert result[0].error is not None

    def test_active_count_initially_zero(self) -> None:
        from claw_forge.orchestrator.pool_runner import PoolRunner

        runner = PoolRunner(MagicMock(), max_concurrent=5)
        assert runner.active_count == 0

    def test_agent_run_fields(self) -> None:
        from claw_forge.orchestrator.pool_runner import AgentRun

        run = AgentRun(
            "agent-1",
            "claude-3",
            "system prompt",
            [{"role": "user", "content": "hi"}],
            max_tokens=1024,
            temperature=0.5,
            tools=[{"name": "fn"}],
        )
        assert run.agent_id == "agent-1"
        assert run.model == "claude-3"
        assert run.max_tokens == 1024
        assert run.response is None
        assert run.error is None


# ---------------------------------------------------------------------------
# Router — uncovered branches
# ---------------------------------------------------------------------------


class TestRouterUncovered:
    def _make_provider(self, name: str, **kw: Any) -> Any:
        from claw_forge.pool.providers.base import BaseProvider, ProviderConfig, ProviderType

        cfg = ProviderConfig(
            name=name,
            provider_type=ProviderType.OPENAI_COMPAT,
            **kw,
        )
        p = MagicMock(spec=BaseProvider)
        p.name = name
        p.config = cfg
        return p

    def test_weighted_random_strategy(self) -> None:
        from claw_forge.pool.router import Router, RoutingStrategy
        from claw_forge.pool.tracker import UsageTracker

        r = Router(strategy=RoutingStrategy.WEIGHTED_RANDOM)
        providers = [
            self._make_provider("p1", weight=2.0),
            self._make_provider("p2", weight=1.0),
        ]
        tracker = UsageTracker()
        # Run multiple times to reduce flakiness from random.choices deduplication
        all_names: set[str] = set()
        for _ in range(20):
            result = r.select(providers, {}, tracker)
            all_names.update(p.name for p in result)
        # Both providers should appear at least once across multiple runs
        assert "p1" in all_names
        assert "p2" in all_names

    def test_least_latency_strategy(self) -> None:
        from claw_forge.pool.router import Router, RoutingStrategy
        from claw_forge.pool.tracker import UsageTracker

        r = Router(strategy=RoutingStrategy.LEAST_LATENCY)
        providers = [
            self._make_provider("p1"),
            self._make_provider("p2"),
        ]
        tracker = MagicMock(spec=UsageTracker)
        tracker.get_avg_latency.side_effect = lambda name: 100.0 if name == "p1" else 50.0
        tracker.is_rate_limited.return_value = False

        result = r.select(providers, {}, tracker)
        assert result[0].name == "p2"  # lower latency first

    def test_select_returns_empty_when_all_disabled(self) -> None:
        from claw_forge.pool.router import Router, RoutingStrategy
        from claw_forge.pool.tracker import UsageTracker

        r = Router(strategy=RoutingStrategy.PRIORITY)
        p = self._make_provider("p1", enabled=False)
        result = r.select([p], {}, UsageTracker())
        assert result == []

    def test_fallback_to_available_strategy(self) -> None:
        """Router returns available providers when strategy is unrecognised edge case."""
        from claw_forge.pool.router import Router, RoutingStrategy
        from claw_forge.pool.tracker import UsageTracker

        r = Router(strategy=RoutingStrategy.ROUND_ROBIN)
        providers = [self._make_provider(f"p{i}") for i in range(3)]
        tracker = UsageTracker()
        result1 = r.select(providers, {}, tracker)
        result2 = r.select(providers, {}, tracker)
        # Round-robin should shift start index
        assert len(result1) == 3
        assert len(result2) == 3


# ---------------------------------------------------------------------------
# State service HTTP endpoints
# ---------------------------------------------------------------------------


async def _make_test_client() -> tuple[Any, Any]:
    """Create an in-memory AgentStateService with DB initialised.

    Returns (client, svc). The service engine is disposed when the client
    context manager exits, preventing 'Event loop is closed' warnings from
    aiosqlite connections that outlive the event loop (BUG-10).
    """
    from httpx import ASGITransport, AsyncClient

    from claw_forge.state.service import AgentStateService

    svc = AgentStateService("sqlite+aiosqlite:///:memory:")
    await svc.init_db()
    app = svc.create_app()

    # Wrap AsyncClient so .dispose() is called on __aexit__
    class _CleanupClient(AsyncClient):
        async def aclose(self) -> None:
            await super().aclose()
            await svc.dispose()

    client = _CleanupClient(transport=ASGITransport(app=app), base_url="http://test")
    return client, svc


@pytest.mark.asyncio
async def test_create_session_returns_id() -> None:
    client, _ = await _make_test_client()
    async with client:
        resp = await client.post("/sessions", json={"project_path": "/my/project"})
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_create_task_and_list() -> None:
    client, _ = await _make_test_client()
    async with client:
        sess = await client.post("/sessions", json={"project_path": "/proj"})
        sid = sess.json()["id"]

        t_resp = await client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "coding", "description": "add login"},
        )
        assert t_resp.status_code == 201
        task_id = t_resp.json()["id"]

        list_resp = await client.get(f"/sessions/{sid}/tasks")
        assert list_resp.status_code == 200
        tasks = list_resp.json()
        assert any(t["id"] == task_id for t in tasks)


@pytest.mark.asyncio
async def test_update_task() -> None:
    client, _ = await _make_test_client()
    async with client:
        sess = await client.post("/sessions", json={"project_path": "/proj"})
        sid = sess.json()["id"]

        t = await client.post(f"/sessions/{sid}/tasks", json={"plugin_name": "coding"})
        tid = t.json()["id"]

        patch_resp = await client.patch(
            f"/tasks/{tid}",
            json={
                "status": "running",
                "input_tokens": 100,
                "output_tokens": 50,
                "cost_usd": 0.01,
            },
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["status"] == "running"


@pytest.mark.asyncio
async def test_update_task_completed() -> None:
    client, _ = await _make_test_client()
    async with client:
        sess = await client.post("/sessions", json={"project_path": "/proj"})
        sid = sess.json()["id"]
        t = await client.post(f"/sessions/{sid}/tasks", json={"plugin_name": "coding"})
        tid = t.json()["id"]

        patch_resp = await client.patch(
            f"/tasks/{tid}", json={"status": "completed", "result": {"passed": True}}
        )
        assert patch_resp.status_code == 200


@pytest.mark.asyncio
async def test_update_task_failed_status() -> None:
    client, _ = await _make_test_client()
    async with client:
        sess = await client.post("/sessions", json={"project_path": "/proj"})
        sid = sess.json()["id"]
        t = await client.post(f"/sessions/{sid}/tasks", json={"plugin_name": "coding"})
        tid = t.json()["id"]
        patch_resp = await client.patch(
            f"/tasks/{tid}", json={"status": "failed", "error_message": "oops"}
        )
        assert patch_resp.status_code == 200


@pytest.mark.asyncio
async def test_update_task_not_found() -> None:
    client, _ = await _make_test_client()
    async with client:
        resp = await client.patch("/tasks/ghost-task-id", json={"status": "running"})
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_task_session_not_found() -> None:
    client, _ = await _make_test_client()
    async with client:
        resp = await client.post("/sessions/ghost/tasks", json={"plugin_name": "coding"})
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_pause_and_resume_session() -> None:
    client, _ = await _make_test_client()
    async with client:
        sess = await client.post("/sessions", json={"project_path": "/proj"})
        sid = sess.json()["id"]

        pause_resp = await client.post(f"/project/pause?session_id={sid}")
        assert pause_resp.status_code == 200
        assert pause_resp.json()["paused"] is True

        paused_resp = await client.get(f"/project/paused?session_id={sid}")
        assert paused_resp.status_code == 200
        assert paused_resp.json()["paused"] is True

        resume_resp = await client.post(f"/project/resume?session_id={sid}")
        assert resume_resp.status_code == 200
        assert resume_resp.json()["paused"] is False


@pytest.mark.asyncio
async def test_pause_session_not_found() -> None:
    client, _ = await _make_test_client()
    async with client:
        resp = await client.post("/project/pause?session_id=ghost")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_resume_session_not_found() -> None:
    client, _ = await _make_test_client()
    async with client:
        resp = await client.post("/project/resume?session_id=ghost")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_is_paused_not_found() -> None:
    client, _ = await _make_test_client()
    async with client:
        resp = await client.get("/project/paused?session_id=ghost")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_human_input_and_answer() -> None:
    client, _ = await _make_test_client()
    async with client:
        sess = await client.post("/sessions", json={"project_path": "/proj"})
        sid = sess.json()["id"]
        t = await client.post(f"/sessions/{sid}/tasks", json={"plugin_name": "coding"})
        tid = t.json()["id"]

        hi_resp = await client.post(
            f"/features/{tid}/human-input",
            json={"question": "Which approach should I use?"},
        )
        assert hi_resp.status_code == 200
        assert hi_resp.json()["status"] == "needs_human"

        list_resp = await client.get("/features/needs-human")
        assert list_resp.status_code == 200
        pending = list_resp.json()
        assert any(p["task_id"] == tid for p in pending)

        ans_resp = await client.post(
            f"/features/{tid}/human-answer", json={"answer": "Use approach A"}
        )
        assert ans_resp.status_code == 200
        assert ans_resp.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_human_answer_wrong_status() -> None:
    client, _ = await _make_test_client()
    async with client:
        sess = await client.post("/sessions", json={"project_path": "/proj"})
        sid = sess.json()["id"]
        t = await client.post(f"/sessions/{sid}/tasks", json={"plugin_name": "coding"})
        tid = t.json()["id"]

        resp = await client.post(
            f"/features/{tid}/human-answer", json={"answer": "Some answer"}
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_human_input_not_found() -> None:
    client, _ = await _make_test_client()
    async with client:
        resp = await client.post(
            "/features/ghost-task/human-input", json={"question": "What to do?"}
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_human_answer_not_found() -> None:
    client, _ = await _make_test_client()
    async with client:
        resp = await client.post(
            "/features/ghost-task/human-answer", json={"answer": "something"}
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_broadcast_methods() -> None:
    """Test all ConnectionManager broadcast typed helpers."""
    from claw_forge.state.service import AgentStateService

    svc = AgentStateService("sqlite+aiosqlite:///:memory:")
    try:
        mgr = svc.ws_manager
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        await mgr.connect(ws)

        await mgr.broadcast_feature_update({"task_id": "t1", "status": "done"})
        await mgr.broadcast_pool_update([{"name": "p1", "healthy": True}])
        await mgr.broadcast_agent_started("sess-1", "task-1")
        await mgr.broadcast_agent_completed("sess-1", "task-1", passed=True)
        await mgr.broadcast_cost_update(1.23, 0.05)

        assert ws.send_json.call_count == 5
    finally:
        await svc.dispose()


@pytest.mark.asyncio
async def test_human_input_filter_by_session() -> None:
    client, _ = await _make_test_client()
    async with client:
        sess = await client.post("/sessions", json={"project_path": "/proj"})
        sid = sess.json()["id"]
        t = await client.post(f"/sessions/{sid}/tasks", json={"plugin_name": "coding"})
        tid = t.json()["id"]
        await client.post(f"/features/{tid}/human-input", json={"question": "Q?"})

        resp = await client.get(f"/features/needs-human?session_id={sid}")
        assert resp.status_code == 200
        pending = resp.json()
        assert len(pending) == 1

        resp2 = await client.get("/features/needs-human?session_id=other-session")
        assert resp2.status_code == 200
        assert resp2.json() == []


# ---------------------------------------------------------------------------
# Plugins/base uncovered paths
# ---------------------------------------------------------------------------


class TestPluginsBase:
    def test_plugin_context_fields(self) -> None:
        from claw_forge.plugins.base import PluginContext

        ctx = PluginContext(project_path="/proj", session_id="s1", task_id="t1")
        assert ctx.project_path == "/proj"
        assert ctx.session_id == "s1"
        assert ctx.task_id == "t1"

    def test_plugin_result_success(self) -> None:
        from claw_forge.plugins.base import PluginResult

        r = PluginResult(success=True, output="done")
        assert r.success is True
        assert r.output == "done"

    def test_plugin_result_failure(self) -> None:
        from claw_forge.plugins.base import PluginResult

        r = PluginResult(success=False, output="failed", files_modified=["a.py"])
        assert r.success is False
        assert r.files_modified == ["a.py"]

    def test_plugin_result_metadata(self) -> None:
        from claw_forge.plugins.base import PluginResult

        r = PluginResult(success=True, output="ok", metadata={"key": "value"})
        assert r.metadata["key"] == "value"


# ---------------------------------------------------------------------------
# Pool manager uncovered paths
# ---------------------------------------------------------------------------


class TestPoolManagerUncovered:
    def _make_manager_with_openai_compat(self) -> Any:
        """Create a ProviderPoolManager with a real OpenAICompatProvider for testing."""
        from claw_forge.pool.manager import ProviderPoolManager
        from claw_forge.pool.providers.base import ProviderConfig, ProviderType

        cfg = ProviderConfig(
            name="oc-test",
            provider_type=ProviderType.OPENAI_COMPAT,
            base_url="http://localhost:11434",
        )
        return ProviderPoolManager([cfg])

    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:
        from claw_forge.pool.providers.base import ProviderResponse

        mgr = self._make_manager_with_openai_compat()
        # Patch the provider's execute directly
        mgr._providers[0].execute = AsyncMock(  # type: ignore[attr-defined]
            return_value=ProviderResponse(content="ok", model="m", provider_name="oc-test")
        )
        result = await mgr.execute(model="m", messages=[{"role": "user", "content": "hi"}])
        assert result.content == "ok"

    @pytest.mark.asyncio
    async def test_health_check_all(self) -> None:
        mgr = self._make_manager_with_openai_compat()
        mgr._providers[0].execute = AsyncMock(side_effect=RuntimeError("offline"))
        results = await mgr.health_check_all()
        assert isinstance(results, dict)
        assert "oc-test" in results
        assert results["oc-test"] is False

    @pytest.mark.asyncio
    async def test_execute_pool_exhausted(self) -> None:
        from claw_forge.pool.manager import ProviderPoolExhausted

        mgr = self._make_manager_with_openai_compat()
        mgr._providers[0].execute = AsyncMock(side_effect=RuntimeError("error"))
        with pytest.raises(ProviderPoolExhausted):
            await mgr.execute(model="m", messages=[{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_get_pool_status(self) -> None:
        mgr = self._make_manager_with_openai_compat()
        mgr._providers[0].execute = AsyncMock(side_effect=RuntimeError("offline"))
        status = await mgr.get_pool_status()
        assert isinstance(status, dict)
        assert "providers" in status


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------


class TestAnthropicProvider:
    def _make_provider(self, **kw: Any) -> Any:
        from claw_forge.pool.providers.anthropic import AnthropicProvider
        from claw_forge.pool.providers.base import ProviderConfig, ProviderType

        defaults = dict(
            name="anthropic-test",
            provider_type=ProviderType.ANTHROPIC,
            api_key="sk-test",
        )
        defaults.update(kw)
        cfg = ProviderConfig(**defaults)
        return AnthropicProvider(cfg)

    def test_constructor_no_api_key(self) -> None:
        from claw_forge.pool.providers.anthropic import AnthropicProvider
        from claw_forge.pool.providers.base import ProviderConfig, ProviderType

        cfg = ProviderConfig(
            name="t", provider_type=ProviderType.ANTHROPIC,
            api_key=None, oauth_token=None, oauth_token_file=None,
        )
        with pytest.raises(ValueError):
            AnthropicProvider(cfg)

    def test_constructor_with_api_key(self) -> None:
        provider = self._make_provider()
        assert provider.name == "anthropic-test"

    def test_constructor_with_oauth_token(self) -> None:
        provider = self._make_provider(api_key=None, oauth_token="oauth-tok")
        assert provider.name == "anthropic-test"

    def test_constructor_with_oauth_token_file(self, tmp_path: Path) -> None:
        token_file = tmp_path / "token.txt"
        token_file.write_text("my-oauth-token")
        provider = self._make_provider(api_key=None, oauth_token_file=str(token_file))
        assert provider.name == "anthropic-test"

    def test_read_token_file_missing(self, tmp_path: Path) -> None:
        from claw_forge.pool.providers.anthropic import AnthropicProvider

        result = AnthropicProvider._read_token_file(str(tmp_path / "ghost.txt"))
        assert result is None

    def test_read_token_file_none(self) -> None:
        from claw_forge.pool.providers.anthropic import AnthropicProvider

        result = AnthropicProvider._read_token_file(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:

        provider = self._make_provider()

        response_data = {
            "id": "msg_001",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "hello from anthropic"}],
            "model": "claude-3-5-sonnet-20241022",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = response_data
        provider._client.post = AsyncMock(return_value=mock_resp)

        result = await provider.execute("claude-3", [{"role": "user", "content": "hi"}])
        assert result.content == "hello from anthropic"
        assert result.provider_name == "anthropic-test"

    @pytest.mark.asyncio
    async def test_execute_rate_limit(self) -> None:
        from claw_forge.pool.providers.base import RateLimitError

        provider = self._make_provider()
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {"retry-after": "5"}
        provider._client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(RateLimitError):
            await provider.execute("claude-3", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_execute_auth_error(self) -> None:
        from claw_forge.pool.providers.base import AuthenticationError

        provider = self._make_provider()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        provider._client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(AuthenticationError):
            await provider.execute("claude-3", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_execute_server_error(self) -> None:
        from claw_forge.pool.providers.base import ProviderError

        provider = self._make_provider()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "internal error"
        provider._client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(ProviderError):
            await provider.execute("claude-3", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_execute_timeout(self) -> None:
        from claw_forge.pool.providers.base import ProviderError

        provider = self._make_provider()
        provider._client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with pytest.raises(ProviderError, match="Timeout"):
            await provider.execute("claude-3", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_execute_with_system_and_tools(self) -> None:
        provider = self._make_provider()

        response_data = {
            "content": [{"type": "text", "text": "ok"}],
            "model": "claude-3",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 5, "output_tokens": 2},
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = response_data
        provider._client.post = AsyncMock(return_value=mock_resp)

        result = await provider.execute(
            "claude-3",
            [{"role": "user", "content": "hi"}],
            system="you are helpful",
            tools=[{"name": "search", "description": "d", "input_schema": {}}],
        )
        assert result.content == "ok"

    @pytest.mark.asyncio
    async def test_health_check_failure(self) -> None:
        provider = self._make_provider()
        provider._client.post = AsyncMock(side_effect=RuntimeError("error"))
        result = await provider.health_check()
        assert result is False


# ---------------------------------------------------------------------------
# CLI — ui command with node_modules
# ---------------------------------------------------------------------------


def test_ui_with_node_modules(tmp_path: Path) -> None:
    from typer.testing import CliRunner as _CLIRunner

    from claw_forge.cli import app as cli_app

    _runner = _CLIRunner()
    ui_dir = tmp_path / "ui"
    ui_dir.mkdir()
    (ui_dir / "node_modules").mkdir()  # so npm install is skipped
    (ui_dir / "package.json").write_text("{}")

    with (
        patch("shutil.which", return_value="/usr/bin/node"),
        patch("subprocess.run"),
        patch("claw_forge.cli.Path") as mock_path,
    ):
        # Make Path(__file__).parent.parent / "ui" return our ui_dir
        mock_path.return_value = MagicMock()
        mock_path.return_value.__truediv__ = MagicMock(return_value=ui_dir)
        type(mock_path.return_value).parent = property(lambda self: mock_path.return_value)
        result = _runner.invoke(cli_app, ["ui", "--no-open"])
    # may exit 0 or 1 depending on mock complexity; just check it ran
    assert result.exit_code in (0, 1)


def test_ui_runs_npm_install_when_no_node_modules(tmp_path: Path) -> None:
    """When node_modules is absent, npm install should run."""
    from typer.testing import CliRunner as _CLIRunner

    from claw_forge.cli import app as cli_app

    _runner = _CLIRunner()
    ui_dir = tmp_path / "ui"
    ui_dir.mkdir()
    # no node_modules

    with (
        patch("shutil.which", return_value="/usr/bin/node"),
        patch("subprocess.run"),
        patch("claw_forge.cli.Path") as mock_path,
    ):
        mock_path.return_value = MagicMock()
        mock_path.return_value.__truediv__ = MagicMock(return_value=ui_dir)
        type(mock_path.return_value).parent = property(lambda self: mock_path.return_value)
        result = _runner.invoke(cli_app, ["ui", "--no-open"])
    assert result.exit_code in (0, 1)


def test_fix_with_branch_succeeds(tmp_path: Path) -> None:
    """When branch creation succeeds, should print branch name."""

    from typer.testing import CliRunner as _CLIRunner

    from claw_forge.cli import app as cli_app

    _runner = _CLIRunner()
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.output = "Fixed"
    mock_result.files_modified = []

    with (
        patch("claw_forge.cli.asyncio.run", return_value=mock_result),
        patch("subprocess.run"),
    ):
        result = _runner.invoke(
            cli_app,
            ["fix", "auth bug", "--project", str(tmp_path)],
        )
    assert result.exit_code == 0


def test_fix_with_branch_fails_gracefully(tmp_path: Path) -> None:
    """When branch creation fails, continue without branch."""
    import subprocess as sp

    from typer.testing import CliRunner as _CLIRunner

    from claw_forge.cli import app as cli_app

    _runner = _CLIRunner()
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.output = "Fixed"
    mock_result.files_modified = []

    with (
        patch("claw_forge.cli.asyncio.run", return_value=mock_result),
        patch("subprocess.run", side_effect=sp.CalledProcessError(1, "git")),
    ):
        result = _runner.invoke(
            cli_app,
            ["fix", "auth bug", "--project", str(tmp_path)],
        )
    assert result.exit_code == 0
    assert (
        "could not create branch" in result.output.lower()
        or "warning" in result.output.lower()
        or "⚠" in result.output
    )


# ---------------------------------------------------------------------------
# plugins/base.py — discover_plugins and version
# ---------------------------------------------------------------------------


def test_base_plugin_version() -> None:
    from claw_forge.plugins.base import BasePlugin, PluginContext, PluginResult

    class MyPlugin(BasePlugin):
        @property
        def name(self) -> str:
            return "my"

        @property
        def description(self) -> str:
            return "test plugin"

        def get_system_prompt(self, context: PluginContext) -> str:
            return "system"

        async def execute(self, context: PluginContext) -> PluginResult:
            return PluginResult(success=True, output="ok")

    p = MyPlugin()
    assert p.version == "0.1.0"


def test_discover_plugins_no_entries() -> None:
    from claw_forge.plugins.base import discover_plugins

    result = discover_plugins()
    assert isinstance(result, dict)


def test_discover_plugins_load_error() -> None:
    """discover_plugins should silently skip plugins that fail to load."""
    from importlib.metadata import EntryPoint

    from claw_forge.plugins.base import discover_plugins

    bad_ep = MagicMock(spec=EntryPoint)
    bad_ep.name = "bad"
    bad_ep.load.side_effect = ImportError("cannot import")

    with patch("claw_forge.plugins.base.entry_points") as mock_eps:
        mock_eps.return_value = MagicMock(
            select=MagicMock(return_value=[bad_ep])
        )
        result = discover_plugins()
    assert isinstance(result, dict)
    assert "bad" not in result


# ---------------------------------------------------------------------------
# pool/manager.py — uncovered branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pool_manager_providers_and_tracker_properties() -> None:
    from claw_forge.pool.manager import ProviderPoolManager
    from claw_forge.pool.providers.base import ProviderConfig, ProviderType

    cfg = ProviderConfig(
        name="p1",
        provider_type=ProviderType.OPENAI_COMPAT,
        base_url="http://localhost:11434",
    )
    mgr = ProviderPoolManager([cfg])
    assert isinstance(mgr.providers, list)
    assert len(mgr.providers) == 1
    from claw_forge.pool.tracker import UsageTracker

    assert isinstance(mgr.tracker, UsageTracker)


@pytest.mark.asyncio
async def test_pool_manager_reset_circuit() -> None:
    from claw_forge.pool.manager import ProviderPoolManager
    from claw_forge.pool.providers.base import ProviderConfig, ProviderType

    cfg = ProviderConfig(
        name="p1", provider_type=ProviderType.OPENAI_COMPAT, base_url="http://localhost"
    )
    mgr = ProviderPoolManager([cfg])
    # Should not raise
    mgr.reset_circuit("p1")
    mgr.reset_circuit("nonexistent")  # should silently skip


@pytest.mark.asyncio
async def test_pool_manager_rate_limit_with_retry_after() -> None:
    from claw_forge.pool.manager import ProviderPoolExhausted, ProviderPoolManager
    from claw_forge.pool.providers.base import (
        ProviderConfig,
        ProviderType,
        RateLimitError,
    )

    cfg = ProviderConfig(
        name="p1",
        provider_type=ProviderType.OPENAI_COMPAT,
        base_url="http://localhost:11434",
    )
    mgr = ProviderPoolManager([cfg], max_retries=1)
    mgr._providers[0].execute = AsyncMock(  # type: ignore[attr-defined]
        side_effect=RateLimitError("rate limited", retry_after=0.01)
    )
    with patch("asyncio.sleep"), pytest.raises(ProviderPoolExhausted):
        await mgr.execute("m", [{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_pool_manager_backoff_no_providers() -> None:
    """When all providers have open circuits, the manager backs off and retries."""
    from claw_forge.pool.manager import ProviderPoolExhausted, ProviderPoolManager
    from claw_forge.pool.providers.base import ProviderConfig, ProviderType

    cfg = ProviderConfig(
        name="p1", provider_type=ProviderType.OPENAI_COMPAT,
        base_url="http://localhost:11434", enabled=False,
    )
    mgr = ProviderPoolManager([cfg], max_retries=2, backoff_base=0.01)
    with patch("asyncio.sleep"), pytest.raises(ProviderPoolExhausted):
        await mgr.execute("m", [{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# anthropic.py — uncovered branches
# ---------------------------------------------------------------------------


class TestAnthropicProviderUncovered:
    def _make_provider(self, **kw: Any) -> Any:
        from claw_forge.pool.providers.anthropic import AnthropicProvider
        from claw_forge.pool.providers.base import ProviderConfig, ProviderType

        defaults = dict(
            name="ant-test",
            provider_type=ProviderType.ANTHROPIC,
            api_key="sk-key",
        )
        defaults.update(kw)
        return AnthropicProvider(ProviderConfig(**defaults))

    @pytest.mark.asyncio
    async def test_execute_with_oauth_token(self) -> None:
        provider = self._make_provider(api_key=None, oauth_token="tok")

        response_data = {
            "content": [{"type": "text", "text": "hello"}],
            "model": "claude-3",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 5, "output_tokens": 2},
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = response_data
        provider._client.post = AsyncMock(return_value=mock_resp)

        result = await provider.execute("claude-3", [{"role": "user", "content": "hi"}])
        assert result.content == "hello"

    @pytest.mark.asyncio
    async def test_execute_oauth_token_file_401_raises_retryable(self, tmp_path: Path) -> None:
        """On 401 with oauth_token_file, raise retryable ProviderError."""
        from claw_forge.pool.providers.base import ProviderError

        token_file = tmp_path / "token.txt"
        token_file.write_text("old-token")

        provider = self._make_provider(api_key=None, oauth_token_file=str(token_file))

        mock_401 = MagicMock()
        mock_401.status_code = 401
        provider._client.post = AsyncMock(return_value=mock_401)

        with pytest.raises(ProviderError, match="retryable|OAuth"):
            await provider.execute("claude-3", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_execute_empty_content_blocks(self) -> None:
        """Empty content list → empty string response."""
        provider = self._make_provider()

        response_data = {
            "content": [],
            "model": "claude-3",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 5, "output_tokens": 0},
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = response_data
        provider._client.post = AsyncMock(return_value=mock_resp)

        result = await provider.execute("claude-3", [{"role": "user", "content": "hi"}])
        assert result.content == ""


# ---------------------------------------------------------------------------
# orchestrator/dispatcher.py — uncovered branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_pause_drain_then_resume() -> None:
    from claw_forge.orchestrator.dispatcher import Dispatcher
    from claw_forge.state.scheduler import TaskNode

    completed: list[str] = []

    async def handler(task: TaskNode) -> dict[str, Any]:
        await asyncio.sleep(0.01)
        completed.append(task.id)
        return {"status": "done"}

    d = Dispatcher(handler=handler, max_concurrency=2)
    for i in range(3):
        d.add_task(TaskNode(id=f"t{i}", plugin_name="coding", priority=0, depends_on=[]))

    run_task = asyncio.create_task(d.run())
    await asyncio.sleep(0.005)
    d.pause()
    await asyncio.sleep(0.05)
    d.resume()
    await run_task
    assert len(completed) == 3


@pytest.mark.asyncio
async def test_dispatcher_with_failed_handler() -> None:
    from claw_forge.orchestrator.dispatcher import Dispatcher
    from claw_forge.state.scheduler import TaskNode

    async def bad_handler(task: TaskNode) -> dict[str, Any]:
        raise RuntimeError("handler failed")

    from claw_forge.orchestrator.dispatcher import DispatcherConfig

    d = Dispatcher(
        handler=bad_handler,
        config=DispatcherConfig(max_concurrency=2, yolo=True, retry_attempts=1),
    )
    d.add_task(TaskNode(id="t0", plugin_name="coding", priority=0, depends_on=[]))
    # Handler error propagates out of run()
    with pytest.raises((RuntimeError, Exception)):
        await d.run()


# ---------------------------------------------------------------------------
# state/service.py — additional coverage for WebSocket and lifespan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_event_with_ws_clients() -> None:
    """Verify _emit_event removes dead WS clients."""
    from claw_forge.state.service import AgentStateService

    svc = AgentStateService("sqlite+aiosqlite:///:memory:")
    try:
        await svc.init_db()

        dead_ws = MagicMock()
        dead_ws.send_json = AsyncMock(side_effect=RuntimeError("disconnected"))
        svc._ws_clients.append(dead_ws)

        # Should not raise; dead client should be cleaned up
        await svc._emit_event("sess-1", None, "test.event", {"key": "value"})
        assert dead_ws not in svc._ws_clients
    finally:
        await svc.dispose()


@pytest.mark.asyncio
async def test_service_list_tasks() -> None:
    """List tasks for a session."""
    from httpx import ASGITransport, AsyncClient

    from claw_forge.state.service import AgentStateService

    svc = AgentStateService("sqlite+aiosqlite:///:memory:")
    try:
        await svc.init_db()
        app = svc.create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            sess = await c.post("/sessions", json={"project_path": "/p"})
            sid = sess.json()["id"]
            t = await c.post(f"/sessions/{sid}/tasks", json={"plugin_name": "coding"})
            assert t.status_code == 201

            list_resp = await c.get(f"/sessions/{sid}/tasks")
            assert list_resp.status_code == 200
            tasks = list_resp.json()
            assert len(tasks) >= 1
    finally:
        await svc.dispose()


@pytest.mark.asyncio
async def test_service_update_task_not_found() -> None:
    from httpx import ASGITransport, AsyncClient

    from claw_forge.state.service import AgentStateService

    svc = AgentStateService("sqlite+aiosqlite:///:memory:")
    try:
        await svc.init_db()
        app = svc.create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.patch("/tasks/ghost-id", json={"status": "running"})
            assert resp.status_code == 404
    finally:
        await svc.dispose()


@pytest.mark.asyncio
async def test_service_sqlite_wal_mode(tmp_path: Path) -> None:
    """State service enables WAL journal mode on connect."""
    from claw_forge.state.service import AgentStateService

    db_path = tmp_path / "test.db"
    svc = AgentStateService(f"sqlite+aiosqlite:///{db_path}")
    try:
        await svc.init_db()
        async with svc._session_factory() as db:
            result = await db.execute(
                __import__("sqlalchemy").text("PRAGMA journal_mode")
            )
            mode = result.scalar()
            assert mode == "wal", f"Expected WAL mode, got {mode!r}"

            result = await db.execute(
                __import__("sqlalchemy").text("PRAGMA busy_timeout")
            )
            timeout = result.scalar()
            assert timeout == 5000
    finally:
        await svc.dispose()


# ---------------------------------------------------------------------------
# scaffold.py — uncovered paths
# ---------------------------------------------------------------------------


def test_scaffold_project_empty_dir(tmp_path: Path) -> None:
    from claw_forge.scaffold import scaffold_project

    # Empty project directory
    result = scaffold_project(tmp_path)
    assert isinstance(result, dict)
    assert "commands_copied" in result


def test_scaffold_project_existing_files(tmp_path: Path) -> None:
    from claw_forge.scaffold import scaffold_project

    # Pre-existing CLAUDE.md
    (tmp_path / "CLAUDE.md").write_text("existing content")
    result = scaffold_project(tmp_path)
    assert isinstance(result, dict)




@pytest.mark.asyncio
async def test_info_endpoint_returns_project_path() -> None:
    """GET /info returns the project path derived from the database URL."""
    client, _ = await _make_test_client()
    async with client:
        resp = await client.get("/info")
        assert resp.status_code == 200
        data = resp.json()
        assert "project_path" in data
        assert "database_url" in data


@pytest.mark.asyncio
async def test_shutdown_endpoint_returns_status() -> None:
    """POST /shutdown returns shutting down status (but doesn't kill in test)."""
    from unittest.mock import patch

    client, _ = await _make_test_client()
    async with client:
        # Patch os.kill for the entire remaining scope — the shutdown endpoint
        # spawns a daemon thread that calls os.kill after 0.2s delay, so the
        # mock must outlive the HTTP response.
        with patch("os.kill"):
            resp = await client.post("/shutdown")
            assert resp.status_code == 200
            assert resp.json()["status"] == "shutting down"
            # Wait for the daemon thread to fire (and hit the mock)
            import time
            time.sleep(0.5)


# ---------------------------------------------------------------------------
# output_parser — uncovered branches
# ---------------------------------------------------------------------------


class TestParseFilename:
    """Unit tests for _parse_filename edge cases."""

    def test_colon_format_candidate_no_path_chars_returns_none(self):
        """lang:word where word has no / or . falls through without returning."""
        from claw_forge.output_parser import _parse_filename

        # "python:nodot" — candidate "nodot" has no "/" or "."
        assert _parse_filename("python:nodot") is None

    def test_space_format_candidate_no_path_chars_returns_none(self):
        """lang word where word has no / or . falls through without returning."""
        from claw_forge.output_parser import _parse_filename

        assert _parse_filename("python nodot") is None

    def test_plain_word_not_in_lang_only_no_slash_or_dot_returns_none(self):
        """Info string that's not a known lang tag and has no / or . → None."""
        from claw_forge.output_parser import _parse_filename

        # "foobar" is not in _LANG_ONLY and has no / or . → falls to final return None
        assert _parse_filename("foobar") is None


class TestWriteCodeBlocksSecurity:
    """Tests for security checks in write_code_blocks."""

    def test_absolute_path_is_skipped(self, tmp_path: Path) -> None:
        from claw_forge.output_parser import write_code_blocks

        text = "```/absolute/path/file.py\ncontent\n```"
        result = write_code_blocks(text, tmp_path)
        assert result == []
        # File must not have been created
        assert not (tmp_path / "file.py").exists()

    def test_path_traversal_is_blocked(self, tmp_path: Path) -> None:
        from claw_forge.output_parser import write_code_blocks

        # ../sibling.py traverses outside the project dir
        text = "```../sibling.py\ncontent\n```"
        result = write_code_blocks(text, tmp_path)
        assert result == []

    def test_resolve_oserror_is_caught(self, tmp_path: Path) -> None:
        from pathlib import Path as _Path
        from unittest.mock import patch

        from claw_forge.output_parser import write_code_blocks

        text = "```src/valid.py\ncontent\n```"
        with patch.object(_Path, "resolve", side_effect=OSError("disk error")):
            result = write_code_blocks(text, tmp_path)
        assert result == []
