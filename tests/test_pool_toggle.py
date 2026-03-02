"""Tests for provider enable/disable toggle (runtime + config persistence)."""

from __future__ import annotations

import sys
import types
import unittest.mock as mock

# Mock claude_agent_sdk if not installed
if "claude_agent_sdk" not in sys.modules:
    sys.modules["claude_agent_sdk"] = types.ModuleType("claude_agent_sdk")

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from claw_forge.pool.health import CircuitBreaker
from claw_forge.pool.manager import ProviderPoolManager
from claw_forge.pool.providers.base import (
    BaseProvider,
    ProviderConfig,
    ProviderResponse,
    ProviderType,
)
from claw_forge.pool.router import Router, RoutingStrategy
from claw_forge.pool.tracker import UsageTracker
from claw_forge.state.service import AgentStateService


# ── Helpers ────────────────────────────────────────────────────────────────────

class MockProvider(BaseProvider):
    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)

    async def execute(self, model: str, messages: list, **kwargs):  # type: ignore[override]
        return ProviderResponse(
            content="ok", model=model, provider_name=self.name,
            input_tokens=10, output_tokens=5, latency_ms=50.0,
        )

    async def health_check(self) -> bool:
        return True


def make_manager(names: list[str] | None = None) -> ProviderPoolManager:
    names = names or ["alpha", "beta"]
    configs = [
        ProviderConfig(name=n, provider_type=ProviderType.ANTHROPIC, priority=i + 1, api_key="k")
        for i, n in enumerate(names)
    ]
    mgr = ProviderPoolManager(configs)
    mgr._providers = [MockProvider(c) for c in configs]
    mgr._circuits = {p.name: CircuitBreaker(p.name) for p in mgr._providers}
    return mgr


def make_service_with_manager(mgr: ProviderPoolManager | None = None) -> AgentStateService:
    svc = AgentStateService(database_url="sqlite+aiosqlite:///:memory:", pool_manager=mgr)
    return svc


# ── Part 1a: ProviderPoolManager methods ──────────────────────────────────────

class TestDisableProvider:
    def test_disable_provider_found(self):
        mgr = make_manager(["alpha", "beta"])
        assert mgr.disable_provider("alpha") is True
        assert mgr._providers[0].config.enabled is False

    def test_disable_provider_not_found(self):
        mgr = make_manager(["alpha"])
        assert mgr.disable_provider("nonexistent") is False

    def test_disable_already_disabled(self):
        mgr = make_manager(["alpha"])
        mgr.disable_provider("alpha")
        assert mgr.disable_provider("alpha") is True  # found, returns True
        assert mgr._providers[0].config.enabled is False

    def test_enable_provider_restores(self):
        mgr = make_manager(["alpha", "beta"])
        mgr.disable_provider("alpha")
        assert mgr._providers[0].config.enabled is False
        assert mgr.enable_provider("alpha") is True
        assert mgr._providers[0].config.enabled is True

    def test_enable_provider_not_found(self):
        mgr = make_manager(["alpha"])
        assert mgr.enable_provider("ghost") is False

    def test_get_provider_enabled_true(self):
        mgr = make_manager(["alpha"])
        assert mgr.get_provider_enabled("alpha") is True

    def test_get_provider_enabled_false(self):
        mgr = make_manager(["alpha"])
        mgr.disable_provider("alpha")
        assert mgr.get_provider_enabled("alpha") is False

    def test_get_provider_enabled_not_found(self):
        mgr = make_manager(["alpha"])
        assert mgr.get_provider_enabled("ghost") is None

    def test_disable_only_one_provider(self):
        """Disabling alpha should leave beta enabled."""
        mgr = make_manager(["alpha", "beta"])
        mgr.disable_provider("alpha")
        assert mgr._providers[0].config.enabled is False
        assert mgr._providers[1].config.enabled is True

    def test_multiple_toggles(self):
        """Toggle on/off/on round-trip."""
        mgr = make_manager(["alpha"])
        mgr.disable_provider("alpha")
        mgr.enable_provider("alpha")
        mgr.disable_provider("alpha")
        assert mgr.get_provider_enabled("alpha") is False


# ── Part 1b: REST endpoints ────────────────────────────────────────────────────

@pytest.fixture
def service_with_manager():
    mgr = make_manager(["anthropic-direct", "groq-backup"])
    svc = make_service_with_manager(mgr)
    return svc, mgr


@pytest.fixture
def app_client(service_with_manager):
    svc, mgr = service_with_manager
    app = svc.create_app()
    client = TestClient(app, raise_server_exceptions=True)
    return client, svc, mgr


class TestToggleEndpoint:
    def test_toggle_endpoint_disable(self, app_client):
        client, svc, mgr = app_client
        resp = client.patch("/pool/providers/anthropic-direct", json={"enabled": False})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "anthropic-direct"
        assert data["enabled"] is False
        assert data["persisted"] is False
        assert mgr.get_provider_enabled("anthropic-direct") is False

    def test_toggle_endpoint_enable(self, app_client):
        client, svc, mgr = app_client
        mgr.disable_provider("groq-backup")
        resp = client.patch("/pool/providers/groq-backup", json={"enabled": True})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True
        assert mgr.get_provider_enabled("groq-backup") is True

    def test_toggle_endpoint_unknown_provider_404(self, app_client):
        client, _, _ = app_client
        resp = client.patch("/pool/providers/nonexistent", json={"enabled": False})
        assert resp.status_code == 404

    def test_toggle_no_pool_manager_503(self):
        svc = make_service_with_manager(None)
        app = svc.create_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.patch("/pool/providers/alpha", json={"enabled": False})
        assert resp.status_code == 503

    def test_toggle_broadcasts_ws(self, service_with_manager):
        """After toggle, broadcast_pool_update should be called."""
        svc, mgr = service_with_manager
        svc.ws_manager.broadcast_pool_update = AsyncMock()
        app = svc.create_app()
        client = TestClient(app)
        client.patch("/pool/providers/anthropic-direct", json={"enabled": False})
        svc.ws_manager.broadcast_pool_update.assert_awaited_once()


class TestPersistEndpoint:
    def test_persist_endpoint_writes_yaml(self, app_client, tmp_path):
        client, svc, mgr = app_client
        # Write a config file
        cfg = tmp_path / "claw-forge.yaml"
        cfg.write_text(yaml.dump({
            "providers": {
                "anthropic-direct": {"enabled": True},
                "groq-backup": {"enabled": True},
            }
        }))
        with patch.object(svc.__class__, "_find_config_path", staticmethod(lambda: cfg)):
            resp = client.post("/pool/providers/anthropic-direct/persist", json={"enabled": False})
        assert resp.status_code == 200
        data = resp.json()
        assert data["persisted"] is True
        assert data["name"] == "anthropic-direct"
        # Check file was updated
        written = yaml.safe_load(cfg.read_text())
        assert written["providers"]["anthropic-direct"]["enabled"] is False

    def test_persist_endpoint_config_not_found_422(self, app_client):
        client, svc, mgr = app_client
        with patch.object(svc.__class__, "_find_config_path", staticmethod(lambda: None)):
            resp = client.post("/pool/providers/anthropic-direct/persist", json={"enabled": False})
        assert resp.status_code == 422

    def test_persist_endpoint_unknown_provider_404(self, app_client, tmp_path):
        client, svc, mgr = app_client
        cfg = tmp_path / "claw-forge.yaml"
        cfg.write_text(yaml.dump({"providers": {}}))
        with patch.object(svc.__class__, "_find_config_path", staticmethod(lambda: cfg)):
            resp = client.post("/pool/providers/ghost/persist", json={"enabled": False})
        assert resp.status_code == 404

    def test_persist_no_pool_manager_503(self):
        svc = make_service_with_manager(None)
        app = svc.create_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/pool/providers/alpha/persist", json={"enabled": False})
        assert resp.status_code == 503

    def test_persist_provider_not_in_yaml_422(self, app_client, tmp_path):
        """Provider exists in runtime but not in YAML — should 422."""
        client, svc, mgr = app_client
        cfg = tmp_path / "claw-forge.yaml"
        cfg.write_text(yaml.dump({"providers": {"other": {"enabled": True}}}))
        with patch.object(svc.__class__, "_find_config_path", staticmethod(lambda: cfg)):
            resp = client.post("/pool/providers/anthropic-direct/persist", json={"enabled": False})
        assert resp.status_code == 422


# ── Part 1c: pool status includes enabled ─────────────────────────────────────

class TestPoolStatusEnabled:
    @pytest.mark.asyncio
    async def test_pool_status_includes_enabled_field(self):
        mgr = make_manager(["alpha", "beta"])
        status = await mgr.get_pool_status()
        for p in status["providers"]:
            assert "enabled" in p

    @pytest.mark.asyncio
    async def test_pool_status_reflects_disabled(self):
        mgr = make_manager(["alpha", "beta"])
        mgr.disable_provider("alpha")
        status = await mgr.get_pool_status()
        alpha = next(p for p in status["providers"] if p["name"] == "alpha")
        assert alpha["enabled"] is False

    @pytest.mark.asyncio
    async def test_disabled_provider_excluded_from_routing(self):
        """Disabled provider must not appear in Router.select()."""
        mgr = make_manager(["alpha", "beta"])
        mgr.disable_provider("alpha")
        tracker = UsageTracker()
        router = Router(strategy=RoutingStrategy.PRIORITY)
        selected = router.select(mgr._providers, mgr._circuits, tracker)
        names = [p.name for p in selected]
        assert "alpha" not in names
        assert "beta" in names


# ── Helper: _persist_provider_enabled ─────────────────────────────────────────

class TestPersistHelper:
    def test_atomic_write(self, tmp_path):
        cfg = tmp_path / "claw-forge.yaml"
        cfg.write_text(yaml.dump({
            "providers": {"prov-a": {"enabled": True}}
        }))
        AgentStateService._persist_provider_enabled(cfg, "prov-a", False)
        data = yaml.safe_load(cfg.read_text())
        assert data["providers"]["prov-a"]["enabled"] is False
        # tmp file should be gone
        assert not cfg.with_suffix(".yaml.tmp").exists()

    def test_no_providers_section_raises(self, tmp_path):
        cfg = tmp_path / "claw-forge.yaml"
        cfg.write_text(yaml.dump({"other": {}}))
        with pytest.raises(ValueError, match="No providers section"):
            AgentStateService._persist_provider_enabled(cfg, "prov-a", False)

    def test_provider_not_in_yaml_raises(self, tmp_path):
        cfg = tmp_path / "claw-forge.yaml"
        cfg.write_text(yaml.dump({"providers": {"other": {}}}))
        with pytest.raises(ValueError, match="not in config"):
            AgentStateService._persist_provider_enabled(cfg, "prov-a", False)


# ── Integration: toggle + persist full flow ────────────────────────────────────

class TestTogglePersistFlow:
    def test_toggle_then_persist_full_flow(self, app_client, tmp_path):
        client, svc, mgr = app_client
        cfg = tmp_path / "claw-forge.yaml"
        cfg.write_text(yaml.dump({
            "providers": {
                "anthropic-direct": {"enabled": True},
                "groq-backup": {"enabled": True},
            }
        }))

        # Step 1: runtime toggle
        resp = client.patch("/pool/providers/anthropic-direct", json={"enabled": False})
        assert resp.status_code == 200
        assert mgr.get_provider_enabled("anthropic-direct") is False

        # Step 2: persist
        with patch.object(svc.__class__, "_find_config_path", staticmethod(lambda: cfg)):
            resp2 = client.post("/pool/providers/anthropic-direct/persist", json={"enabled": False})
        assert resp2.status_code == 200
        assert resp2.json()["persisted"] is True
        data = yaml.safe_load(cfg.read_text())
        assert data["providers"]["anthropic-direct"]["enabled"] is False
