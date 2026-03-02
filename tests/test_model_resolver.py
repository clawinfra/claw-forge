"""Tests for claw_forge.pool.model_resolver."""
from __future__ import annotations

import sys
import unittest.mock

# Mock claude_agent_sdk before any claw_forge imports
sys.modules["claude_agent_sdk"] = unittest.mock.MagicMock()
sys.modules["claude_agent_sdk.types"] = unittest.mock.MagicMock()

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claw_forge.pool.model_resolver import ResolvedModel, resolve_model


# ---------------------------------------------------------------------------
# Basic resolution tests
# ---------------------------------------------------------------------------


class TestBareModel:
    def test_bare_model_no_provider_hint(self) -> None:
        r = resolve_model("claude-opus-4-5")
        assert r.provider_hint is None
        assert r.model_id == "claude-opus-4-5"
        assert r.raw == "claude-opus-4-5"
        assert r.alias_resolved is False

    def test_bare_model_with_colon(self) -> None:
        """Model IDs containing ':' but no '/' stay as bare models."""
        r = resolve_model("qwen2.5:32b")
        assert r.provider_hint is None
        assert r.model_id == "qwen2.5:32b"
        assert r.alias_resolved is False

    def test_bare_model_no_config(self) -> None:
        r = resolve_model("claude-sonnet-4-5", config=None)
        assert r.provider_hint is None
        assert r.model_id == "claude-sonnet-4-5"

    def test_bare_model_empty_config(self) -> None:
        r = resolve_model("claude-haiku-4-5", config={})
        assert r.provider_hint is None
        assert r.model_id == "claude-haiku-4-5"


class TestProviderSlashModelFormat:
    def test_provider_slash_model_format(self) -> None:
        r = resolve_model("anthropic-proxy-1/claude-opus-4-5")
        assert r.provider_hint == "anthropic-proxy-1"
        assert r.model_id == "claude-opus-4-5"
        assert r.raw == "anthropic-proxy-1/claude-opus-4-5"
        assert r.alias_resolved is False

    def test_provider_slash_model_with_subpath(self) -> None:
        """ollama/qwen2.5:32b — provider is 'ollama', model is 'qwen2.5:32b'."""
        r = resolve_model("ollama/qwen2.5:32b")
        assert r.provider_hint == "ollama"
        assert r.model_id == "qwen2.5:32b"
        assert r.alias_resolved is False

    def test_provider_slash_model_with_multiple_slashes(self) -> None:
        """Only the first '/' splits provider from model."""
        r = resolve_model("my-proxy/some/nested/model")
        assert r.provider_hint == "my-proxy"
        assert r.model_id == "some/nested/model"
        assert r.alias_resolved is False

    def test_provider_slash_model_no_aliases_needed(self) -> None:
        r = resolve_model("proxy-6/glm-4.5-air")
        assert r.provider_hint == "proxy-6"
        assert r.model_id == "glm-4.5-air"

    def test_provider_slash_model_with_version(self) -> None:
        r = resolve_model("bedrock-us-east/anthropic.claude-sonnet-4-20250514-v2:0")
        assert r.provider_hint == "bedrock-us-east"
        assert r.model_id == "anthropic.claude-sonnet-4-20250514-v2:0"


class TestAliasResolution:
    def test_alias_resolution_bare_model(self) -> None:
        cfg = {"model_aliases": {"sonnet": "claude-sonnet-4-5"}}
        r = resolve_model("sonnet", config=cfg)
        assert r.provider_hint is None
        assert r.model_id == "claude-sonnet-4-5"
        assert r.raw == "sonnet"
        assert r.alias_resolved is True

    def test_alias_resolution_provider_model(self) -> None:
        cfg = {"model_aliases": {"opus": "anthropic-proxy-1/claude-opus-4-5"}}
        r = resolve_model("opus", config=cfg)
        assert r.provider_hint == "anthropic-proxy-1"
        assert r.model_id == "claude-opus-4-5"
        assert r.alias_resolved is True

    def test_resolve_model_opus_alias(self) -> None:
        cfg = {"model_aliases": {"opus": "claude-opus-4-5"}}
        r = resolve_model("opus", config=cfg)
        assert r.model_id == "claude-opus-4-5"
        assert r.provider_hint is None
        assert r.alias_resolved is True

    def test_resolve_model_sonnet_alias(self) -> None:
        cfg = {"model_aliases": {"sonnet": "claude-sonnet-4-5"}}
        r = resolve_model("sonnet", config=cfg)
        assert r.model_id == "claude-sonnet-4-5"
        assert r.alias_resolved is True

    def test_resolve_model_local_alias_with_colon(self) -> None:
        """Alias pointing to 'provider/model:tag' format."""
        cfg = {"model_aliases": {"local": "ollama/qwen2.5:32b"}}
        r = resolve_model("local", config=cfg)
        assert r.provider_hint == "ollama"
        assert r.model_id == "qwen2.5:32b"
        assert r.alias_resolved is True

    def test_alias_fast(self) -> None:
        cfg = {"model_aliases": {"fast": "claude-haiku-4-5"}}
        r = resolve_model("fast", config=cfg)
        assert r.model_id == "claude-haiku-4-5"
        assert r.alias_resolved is True

    def test_alias_not_in_config_passthrough(self) -> None:
        """If the key is not in aliases, fall through to normal resolution."""
        cfg = {"model_aliases": {"opus": "claude-opus-4-5"}}
        r = resolve_model("claude-haiku-4-5", config=cfg)
        assert r.provider_hint is None
        assert r.model_id == "claude-haiku-4-5"
        assert r.alias_resolved is False

    def test_no_config_passthrough(self) -> None:
        r = resolve_model("haiku")
        assert r.model_id == "haiku"
        assert r.alias_resolved is False

    def test_empty_aliases_passthrough(self) -> None:
        r = resolve_model("haiku", config={"model_aliases": {}})
        assert r.model_id == "haiku"
        assert r.alias_resolved is False

    def test_alias_chain_does_not_recurse(self) -> None:
        """Alias pointing to another alias is NOT followed — no infinite loop."""
        cfg = {"model_aliases": {"a": "b", "b": "claude-opus-4-5"}}
        r = resolve_model("a", config=cfg)
        # 'a' → 'b' literally (the string 'b', not recursed)
        assert r.model_id == "b"
        assert r.alias_resolved is True
        # Ensure 'b' was NOT further resolved
        assert r.provider_hint is None

    def test_model_aliases_key_missing(self) -> None:
        """Config without model_aliases key → treat as no aliases."""
        cfg = {"pool": {"strategy": "priority"}}
        r = resolve_model("claude-opus-4-5", config=cfg)
        assert r.model_id == "claude-opus-4-5"
        assert r.alias_resolved is False

    def test_model_aliases_not_dict(self) -> None:
        """If model_aliases is not a dict, ignore it gracefully."""
        cfg = {"model_aliases": "not-a-dict"}
        r = resolve_model("claude-opus-4-5", config=cfg)
        assert r.model_id == "claude-opus-4-5"
        assert r.alias_resolved is False

    def test_alias_to_provider_slash_model_fields(self) -> None:
        cfg = {"model_aliases": {"prod": "proxy-a/claude-sonnet-4-5"}}
        r = resolve_model("prod", config=cfg)
        assert r.raw == "prod"
        assert r.alias_resolved is True
        assert r.provider_hint == "proxy-a"
        assert r.model_id == "claude-sonnet-4-5"


class TestResolvedModelDataclass:
    def test_resolved_model_dataclass_fields(self) -> None:
        r = ResolvedModel(
            provider_hint="my-provider",
            model_id="claude-opus-4-5",
            raw="my-provider/claude-opus-4-5",
            alias_resolved=False,
        )
        assert r.provider_hint == "my-provider"
        assert r.model_id == "claude-opus-4-5"
        assert r.raw == "my-provider/claude-opus-4-5"
        assert r.alias_resolved is False

    def test_resolved_model_defaults_none_provider_hint(self) -> None:
        r = ResolvedModel(
            provider_hint=None,
            model_id="claude-haiku-4-5",
            raw="claude-haiku-4-5",
            alias_resolved=False,
        )
        assert r.provider_hint is None


# ---------------------------------------------------------------------------
# Pool execute() with provider_hint — mock pool tests
# ---------------------------------------------------------------------------


class TestProviderHintInPool:
    """Mock-based tests for ProviderPoolManager.execute() with provider_hint."""

    def _make_pool_manager(
        self, providers: list, circuits: dict | None = None
    ) -> object:
        """Build a minimal ProviderPoolManager with mocked internals."""
        from claw_forge.pool.manager import ProviderPoolManager
        from claw_forge.pool.health import CircuitBreaker, CircuitState
        from claw_forge.pool.providers.base import ProviderConfig, ProviderType

        pm = object.__new__(ProviderPoolManager)
        pm._providers = providers
        pm._circuits = circuits or {}
        pm._tracker = MagicMock()
        pm._router = MagicMock()
        pm._max_retries = 3
        pm._backoff_base = 1.0
        pm._backoff_max = 30.0
        pm._lock = asyncio.Lock()
        return pm

    def _make_provider(self, name: str, enabled: bool = True) -> MagicMock:
        p = MagicMock()
        p.name = name
        p.config = MagicMock()
        p.config.enabled = enabled
        p.config.cost_per_mtok_input = 3.0
        p.config.cost_per_mtok_output = 15.0
        return p

    def _make_circuit(self, state_val: str = "closed") -> MagicMock:
        from claw_forge.pool.health import CircuitState

        cb = MagicMock()
        cb.state = CircuitState(state_val)
        return cb

    async def test_provider_hint_execute_pinned(self) -> None:
        """provider_hint routes directly to the named provider."""
        from claw_forge.pool.manager import ProviderPoolManager
        from claw_forge.pool.providers.base import ProviderResponse

        provider = self._make_provider("proxy-6")
        fake_response = ProviderResponse(
            content="ok", model="glm-4.5-air", provider_name="proxy-6",
            input_tokens=10, output_tokens=5, latency_ms=50.0
        )
        provider.execute = AsyncMock(return_value=fake_response)

        cb = self._make_circuit("closed")
        pm = self._make_pool_manager([provider], {"proxy-6": cb})

        result = await ProviderPoolManager.execute(
            pm,
            model="glm-4.5-air",
            messages=[{"role": "user", "content": "hi"}],
            provider_hint="proxy-6",
        )
        assert result.content == "ok"
        provider.execute.assert_called_once()

    async def test_provider_hint_not_found_raises(self) -> None:
        """provider_hint to unknown name raises ProviderNotFoundError."""
        from claw_forge.pool.manager import ProviderNotFoundError, ProviderPoolManager

        provider = self._make_provider("real-provider")
        cb = self._make_circuit("closed")
        pm = self._make_pool_manager([provider], {"real-provider": cb})

        with pytest.raises(ProviderNotFoundError, match="ghost-provider"):
            await ProviderPoolManager.execute(
                pm,
                model="some-model",
                messages=[],
                provider_hint="ghost-provider",
            )

    async def test_provider_hint_unavailable_raises_disabled(self) -> None:
        """provider_hint to disabled provider raises ProviderUnavailableError."""
        from claw_forge.pool.manager import ProviderPoolManager, ProviderUnavailableError

        provider = self._make_provider("proxy-a", enabled=False)
        cb = self._make_circuit("closed")
        pm = self._make_pool_manager([provider], {"proxy-a": cb})

        with pytest.raises(ProviderUnavailableError, match="proxy-a"):
            await ProviderPoolManager.execute(
                pm,
                model="some-model",
                messages=[],
                provider_hint="proxy-a",
            )

    async def test_provider_hint_circuit_open_raises(self) -> None:
        """provider_hint to circuit-open provider raises ProviderUnavailableError."""
        from claw_forge.pool.manager import ProviderPoolManager, ProviderUnavailableError

        provider = self._make_provider("proxy-b", enabled=True)
        cb = self._make_circuit("open")
        pm = self._make_pool_manager([provider], {"proxy-b": cb})

        with pytest.raises(ProviderUnavailableError, match="proxy-b"):
            await ProviderPoolManager.execute(
                pm,
                model="some-model",
                messages=[],
                provider_hint="proxy-b",
            )

    async def test_execute_without_hint_uses_rotation(self) -> None:
        """Without provider_hint, pool rotation is used (router.select called)."""
        from claw_forge.pool.manager import ProviderPoolManager
        from claw_forge.pool.providers.base import ProviderResponse

        provider = self._make_provider("proxy-c")
        fake_response = ProviderResponse(
            content="via-rotation", model="some-model", provider_name="proxy-c",
            input_tokens=5, output_tokens=3, latency_ms=30.0
        )
        provider.execute = AsyncMock(return_value=fake_response)

        cb = self._make_circuit("closed")
        pm = self._make_pool_manager([provider], {"proxy-c": cb})
        pm._router.select = MagicMock(return_value=[provider])

        result = await ProviderPoolManager.execute(
            pm,
            model="some-model",
            messages=[{"role": "user", "content": "hi"}],
            # no provider_hint
        )
        assert result.content == "via-rotation"
        pm._router.select.assert_called()

    async def test_provider_hint_not_found_lists_available(self) -> None:
        """Error message includes available provider names."""
        from claw_forge.pool.manager import ProviderNotFoundError, ProviderPoolManager

        p1 = self._make_provider("prov-alpha")
        p2 = self._make_provider("prov-beta")
        pm = self._make_pool_manager(
            [p1, p2],
            {"prov-alpha": self._make_circuit(), "prov-beta": self._make_circuit()},
        )

        with pytest.raises(ProviderNotFoundError) as exc_info:
            await ProviderPoolManager.execute(
                pm,
                model="m",
                messages=[],
                provider_hint="nonexistent",
            )
        msg = str(exc_info.value)
        assert "prov-alpha" in msg or "prov-beta" in msg

    async def test_provider_hint_unavailable_error_message(self) -> None:
        """ProviderUnavailableError message is clear."""
        from claw_forge.pool.manager import ProviderPoolManager, ProviderUnavailableError

        provider = self._make_provider("flaky-proxy", enabled=False)
        cb = self._make_circuit("closed")
        pm = self._make_pool_manager([provider], {"flaky-proxy": cb})

        with pytest.raises(ProviderUnavailableError) as exc_info:
            await ProviderPoolManager.execute(
                pm,
                model="m",
                messages=[],
                provider_hint="flaky-proxy",
            )
        assert "disabled or circuit open" in str(exc_info.value)
