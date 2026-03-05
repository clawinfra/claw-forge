"""Tests for per-provider complexity-based model tier selection in ProviderPoolManager."""
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


def make_mgr_with_tiers(
    active_tiers: list[str],
    model_map: dict[str, str] | None = None,
) -> tuple[ProviderPoolManager, RecordingProvider]:
    if model_map is None:
        model_map = {"fast": "claude-haiku-4-5", "medium": "claude-sonnet-4-6", "smart": "claude-opus-4-6"}
    cfg = ProviderConfig(
        name="p1",
        provider_type=ProviderType.ANTHROPIC,
        api_key="k",
        model_map=model_map,
        active_tiers=active_tiers,
    )
    mgr = ProviderPoolManager([cfg])
    provider = RecordingProvider(cfg)
    mgr._providers = [provider]  # type: ignore[assignment]
    mgr._circuits = {"p1": CircuitBreaker("p1")}
    return mgr, provider


class TestGetModelForComplexity:
    def test_returns_none_when_no_tiers(self):
        mgr, _ = make_mgr_with_tiers([])
        assert mgr.get_model_for_complexity("p1", "low") is None

    def test_returns_none_for_unknown_provider(self):
        mgr, _ = make_mgr_with_tiers(["fast"])
        assert mgr.get_model_for_complexity("ghost", "low") is None

    def test_low_complexity_picks_first_tier(self):
        mgr, _ = make_mgr_with_tiers(["fast", "smart"])
        assert mgr.get_model_for_complexity("p1", "low") == "claude-haiku-4-5"

    def test_high_complexity_picks_last_tier(self):
        mgr, _ = make_mgr_with_tiers(["fast", "smart"])
        assert mgr.get_model_for_complexity("p1", "high") == "claude-opus-4-6"

    def test_medium_complexity_picks_middle_tier(self):
        mgr, _ = make_mgr_with_tiers(["fast", "medium", "smart"])
        assert mgr.get_model_for_complexity("p1", "medium") == "claude-sonnet-4-6"

    def test_single_tier_all_complexities_return_same(self):
        mgr, _ = make_mgr_with_tiers(["smart"])
        assert mgr.get_model_for_complexity("p1", "low") == "claude-opus-4-6"
        assert mgr.get_model_for_complexity("p1", "medium") == "claude-opus-4-6"
        assert mgr.get_model_for_complexity("p1", "high") == "claude-opus-4-6"

    def test_two_tiers_medium_picks_second(self):
        """With 2 tiers, medium (index len//2=1) picks the last."""
        mgr, _ = make_mgr_with_tiers(["fast", "smart"])
        assert mgr.get_model_for_complexity("p1", "medium") == "claude-opus-4-6"

    def test_alias_not_in_model_map_returns_none(self):
        mgr, _ = make_mgr_with_tiers(["unknown-alias"])
        assert mgr.get_model_for_complexity("p1", "low") is None

    def test_none_complexity_returns_none(self):
        """None complexity means caller-supplied model; no tier lookup."""
        mgr, _ = make_mgr_with_tiers(["fast", "smart"])
        assert mgr.get_model_for_complexity("p1", None) is None


class TestSetProviderTiers:
    def test_set_tiers_found_returns_true(self):
        mgr, _ = make_mgr_with_tiers([])
        assert mgr.set_provider_tiers("p1", ["fast", "smart"]) is True

    def test_set_tiers_not_found_returns_false(self):
        mgr, _ = make_mgr_with_tiers([])
        assert mgr.set_provider_tiers("ghost", ["fast"]) is False

    def test_set_tiers_updates_config(self):
        mgr, provider = make_mgr_with_tiers([])
        mgr.set_provider_tiers("p1", ["fast", "smart"])
        assert provider.config.active_tiers == ["fast", "smart"]

    def test_set_empty_tiers_clears_pool(self):
        mgr, _ = make_mgr_with_tiers(["fast", "smart"])
        mgr.set_provider_tiers("p1", [])
        assert mgr.get_model_for_complexity("p1", "low") is None


class TestExecuteUsesComplexity:
    @pytest.mark.asyncio
    async def test_low_complexity_uses_cheapest_model(self):
        mgr, provider = make_mgr_with_tiers(["fast", "smart"])
        await mgr.execute("caller-model", [{"role": "user", "content": "hi"}], complexity="low")
        assert provider.calls == ["claude-haiku-4-5"]

    @pytest.mark.asyncio
    async def test_high_complexity_uses_smartest_model(self):
        mgr, provider = make_mgr_with_tiers(["fast", "smart"])
        await mgr.execute("caller-model", [{"role": "user", "content": "hi"}], complexity="high")
        assert provider.calls == ["claude-opus-4-6"]

    @pytest.mark.asyncio
    async def test_no_complexity_uses_caller_model(self):
        mgr, provider = make_mgr_with_tiers(["fast", "smart"])
        await mgr.execute("caller-model", [{"role": "user", "content": "hi"}])
        assert provider.calls == ["caller-model"]

    @pytest.mark.asyncio
    async def test_no_tiers_falls_back_to_caller_model(self):
        mgr, provider = make_mgr_with_tiers([])
        await mgr.execute("caller-model", [{"role": "user", "content": "hi"}], complexity="high")
        assert provider.calls == ["caller-model"]

    @pytest.mark.asyncio
    async def test_get_pool_status_includes_active_tiers(self):
        mgr, _ = make_mgr_with_tiers(["fast", "smart"])
        status = await mgr.get_pool_status()
        p = status["providers"][0]
        assert "active_tiers" in p
        assert p["active_tiers"] == ["fast", "smart"]


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
        active_tiers=["fast"],
    )
    mgr = ProviderPoolManager([cfg])
    mgr._providers = [RecordingProvider(cfg)]  # type: ignore[assignment]
    mgr._circuits = {"p1": CircuitBreaker("p1")}
    return mgr


class TestSetTiersEndpoint:
    @pytest.fixture
    def client_and_mgr(self):
        mgr = make_mgr_for_service()
        svc = AgentStateService(database_url="sqlite+aiosqlite:///:memory:", pool_manager=mgr)
        app = svc.create_app()
        client = TestClient(app, raise_server_exceptions=True)
        return client, mgr

    def test_set_tiers_updates_pool(self, client_and_mgr):
        client, mgr = client_and_mgr
        resp = client.patch(
            "/pool/providers/p1/models",
            json={"active_tiers": ["fast", "smart"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_tiers"] == ["fast", "smart"]
        assert mgr._active_tiers["p1"] == ["fast", "smart"]

    def test_set_tiers_unknown_provider_404(self, client_and_mgr):
        client, _ = client_and_mgr
        resp = client.patch(
            "/pool/providers/ghost/models",
            json={"active_tiers": ["fast"]},
        )
        assert resp.status_code == 404

    def test_set_tiers_no_pool_manager_503(self):
        svc = AgentStateService(database_url="sqlite+aiosqlite:///:memory:", pool_manager=None)
        app = svc.create_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.patch("/pool/providers/p1/models", json={"active_tiers": []})
        assert resp.status_code == 503

    def test_pool_status_includes_model_map_and_active_tiers(self, client_and_mgr):
        client, _ = client_and_mgr
        resp = client.get("/pool/status")
        assert resp.status_code == 200
        providers = resp.json()["providers"]
        p = next(x for x in providers if x["name"] == "p1")
        assert "model_map" in p
        assert "active_tiers" in p
        assert p["model_map"] == {"fast": "claude-haiku-4-5", "smart": "claude-opus-4-6"}
        assert p["active_tiers"] == ["fast"]
