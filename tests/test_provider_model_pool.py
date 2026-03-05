"""Tests for per-provider model pool round-robin in ProviderPoolManager."""
from __future__ import annotations

import pytest

from claw_forge.pool.health import CircuitBreaker
from claw_forge.pool.manager import ProviderPoolManager
from claw_forge.pool.providers.base import (
    ProviderConfig, ProviderResponse, ProviderType,
)
from claw_forge.pool.providers.base import BaseProvider


class RecordingProvider(BaseProvider):
    """Records the model arg passed to each execute() call."""
    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self.calls: list[str] = []

    async def execute(self, model: str, messages: list, **kwargs) -> ProviderResponse:  # type: ignore[override]
        self.calls.append(model)
        return ProviderResponse(
            content="ok", model=model, provider_name=self.name,
            input_tokens=10, output_tokens=5, latency_ms=50.0,
        )

    async def health_check(self) -> bool:
        return True


def make_mgr_with_pool(active_models: list[str]) -> tuple[ProviderPoolManager, RecordingProvider]:
    cfg = ProviderConfig(
        name="p1",
        provider_type=ProviderType.ANTHROPIC,
        api_key="k",
        active_models=active_models,
    )
    mgr = ProviderPoolManager([cfg])
    provider = RecordingProvider(cfg)
    mgr._providers = [provider]  # type: ignore[assignment]
    mgr._circuits = {"p1": CircuitBreaker("p1")}
    return mgr, provider


class TestGetNextModel:
    def test_returns_none_when_pool_empty(self):
        mgr, _ = make_mgr_with_pool([])
        assert mgr.get_next_model("p1") is None

    def test_returns_none_for_unknown_provider(self):
        mgr, _ = make_mgr_with_pool(["m1"])
        assert mgr.get_next_model("ghost") is None

    def test_single_model_pool_always_returns_same(self):
        mgr, _ = make_mgr_with_pool(["claude-haiku-4-5"])
        assert mgr.get_next_model("p1") == "claude-haiku-4-5"
        assert mgr.get_next_model("p1") == "claude-haiku-4-5"

    def test_two_model_pool_round_robins(self):
        mgr, _ = make_mgr_with_pool(["haiku", "sonnet"])
        results = [mgr.get_next_model("p1") for _ in range(4)]
        assert results == ["haiku", "sonnet", "haiku", "sonnet"]


class TestSetProviderModels:
    def test_set_models_found_returns_true(self):
        mgr, _ = make_mgr_with_pool([])
        assert mgr.set_provider_models("p1", ["m1", "m2"]) is True

    def test_set_models_not_found_returns_false(self):
        mgr, _ = make_mgr_with_pool([])
        assert mgr.set_provider_models("ghost", ["m1"]) is False

    def test_set_models_resets_rr_index(self):
        mgr, _ = make_mgr_with_pool(["a", "b"])
        mgr.get_next_model("p1")  # advance index to 1
        mgr.set_provider_models("p1", ["x", "y", "z"])
        # After reset, should start from "x"
        assert mgr.get_next_model("p1") == "x"

    def test_set_empty_models_clears_pool(self):
        mgr, _ = make_mgr_with_pool(["a", "b"])
        mgr.set_provider_models("p1", [])
        assert mgr.get_next_model("p1") is None


class TestExecuteUsesModelPool:
    @pytest.mark.asyncio
    async def test_execute_uses_pool_model_not_caller_model(self):
        mgr, provider = make_mgr_with_pool(["claude-haiku-4-5", "claude-sonnet-4-6"])
        await mgr.execute("caller-supplied-model", [{"role": "user", "content": "hi"}])
        await mgr.execute("caller-supplied-model", [{"role": "user", "content": "hi"}])
        assert provider.calls == ["claude-haiku-4-5", "claude-sonnet-4-6"]

    @pytest.mark.asyncio
    async def test_execute_uses_caller_model_when_pool_empty(self):
        mgr, provider = make_mgr_with_pool([])
        await mgr.execute("caller-model", [{"role": "user", "content": "hi"}])
        assert provider.calls == ["caller-model"]

    @pytest.mark.asyncio
    async def test_get_pool_status_includes_active_models(self):
        mgr, _ = make_mgr_with_pool(["haiku", "sonnet"])
        status = await mgr.get_pool_status()
        p = status["providers"][0]
        assert "active_models" in p
        assert p["active_models"] == ["haiku", "sonnet"]


# ── Service endpoint tests ─────────────────────────────────────────────────────

import sys
import types
if "claude_agent_sdk" not in sys.modules:
    sys.modules["claude_agent_sdk"] = types.ModuleType("claude_agent_sdk")

from fastapi.testclient import TestClient  # noqa: E402
from claw_forge.state.service import AgentStateService  # noqa: E402


def make_mgr_for_service() -> ProviderPoolManager:
    cfg = ProviderConfig(
        name="p1", provider_type=ProviderType.ANTHROPIC, api_key="k",
        model_map={"fast": "claude-haiku-4-5", "smart": "claude-opus-4-6"},
        active_models=["claude-haiku-4-5"],
    )
    mgr = ProviderPoolManager([cfg])
    mgr._providers = [RecordingProvider(cfg)]  # type: ignore[assignment]
    mgr._circuits = {"p1": CircuitBreaker("p1")}
    return mgr


class TestSetModelsEndpoint:
    @pytest.fixture
    def client_and_mgr(self):
        mgr = make_mgr_for_service()
        svc = AgentStateService(database_url="sqlite+aiosqlite:///:memory:", pool_manager=mgr)
        app = svc.create_app()
        client = TestClient(app, raise_server_exceptions=True)
        return client, mgr

    def test_set_models_updates_pool(self, client_and_mgr):
        client, mgr = client_and_mgr
        resp = client.patch(
            "/pool/providers/p1/models",
            json={"active_models": ["claude-haiku-4-5", "claude-opus-4-6"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_models"] == ["claude-haiku-4-5", "claude-opus-4-6"]
        assert mgr._model_pools["p1"] == ["claude-haiku-4-5", "claude-opus-4-6"]

    def test_set_models_unknown_provider_404(self, client_and_mgr):
        client, _ = client_and_mgr
        resp = client.patch(
            "/pool/providers/ghost/models",
            json={"active_models": ["m1"]},
        )
        assert resp.status_code == 404

    def test_set_models_no_pool_manager_503(self):
        svc = AgentStateService(database_url="sqlite+aiosqlite:///:memory:", pool_manager=None)
        app = svc.create_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.patch("/pool/providers/p1/models", json={"active_models": []})
        assert resp.status_code == 503

    def test_pool_status_includes_model_map_and_active_models(self, client_and_mgr):
        client, _ = client_and_mgr
        resp = client.get("/pool/status")
        assert resp.status_code == 200
        providers = resp.json()["providers"]
        p = next(x for x in providers if x["name"] == "p1")
        assert "model_map" in p
        assert "active_models" in p
        assert p["model_map"] == {"fast": "claude-haiku-4-5", "smart": "claude-opus-4-6"}
        assert p["active_models"] == ["claude-haiku-4-5"]
