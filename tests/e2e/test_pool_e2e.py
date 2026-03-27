"""End-to-end tests for the ProviderPoolManager.

When PROXY_1_* env vars are set, tests hit the real proxy endpoint.
Otherwise, tests use a mock provider so they never skip.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from claw_forge.pool.health import CircuitState
from claw_forge.pool.manager import ProviderPoolExhausted, ProviderPoolManager
from claw_forge.pool.providers.base import (
    ProviderConfig,
    ProviderResponse,
    ProviderType,
)

# ---------------------------------------------------------------------------
# Load .env from project root (proxy-6 credentials)
# ---------------------------------------------------------------------------


def _load_env() -> dict[str, str]:
    """Read .env file and return PROXY_1_* vars without polluting os.environ."""
    result: dict[str, str] = {}
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                if key.startswith("PROXY_1_"):
                    result[key] = val.strip()
    return result


_env_vars = _load_env()

PROXY_API_KEY = _env_vars.get("PROXY_1_API_KEY", "") or os.environ.get("PROXY_1_API_KEY", "")
_raw_base = _env_vars.get("PROXY_1_BASE_URL", "") or os.environ.get("PROXY_1_BASE_URL", "")
# The AnthropicCompatProvider posts to /v1/messages, so strip trailing /v1
# to avoid double-pathing (e.g. .../v1/v1/messages).
PROXY_BASE_URL = _raw_base.rstrip("/").removesuffix("/v1") if _raw_base else ""
PROXY_MODEL = _env_vars.get("PROXY_1_MODEL", "") or os.environ.get("PROXY_1_MODEL", "glm-4.5-air")

HAS_PROXY = bool(PROXY_API_KEY and PROXY_BASE_URL)


def _proxy6_config(name: str = "proxy6", priority: int = 1) -> ProviderConfig:
    """Build ProviderConfig for the z.ai proxy-6 endpoint."""
    return ProviderConfig(
        name=name,
        provider_type=ProviderType.ANTHROPIC_COMPAT,
        api_key=PROXY_API_KEY or "fake-key-for-construction",
        base_url=PROXY_BASE_URL or "http://localhost:19998",
        priority=priority,
        cost_per_mtok_input=0.5,
        cost_per_mtok_output=1.5,
    )


def _broken_config(name: str = "broken", priority: int = 0) -> ProviderConfig:
    """Build a ProviderConfig pointing at an invalid URL (always fails)."""
    return ProviderConfig(
        name=name,
        provider_type=ProviderType.ANTHROPIC_COMPAT,
        api_key="invalid-key",
        base_url="http://127.0.0.1:19999",  # nothing listening here
        priority=priority,
    )


def _mock_response(provider_name: str = "proxy6") -> ProviderResponse:
    """Build a mock ProviderResponse for testing without real API calls."""
    return ProviderResponse(
        content="hello",
        model=PROXY_MODEL,
        provider_name=provider_name,
        input_tokens=10,
        output_tokens=5,
        stop_reason="end_turn",
        latency_ms=42.0,
    )


# ---------------------------------------------------------------------------
# Pool construction (no network needed)
# ---------------------------------------------------------------------------


class TestPoolConstruction:
    def test_pool_created_with_proxy6(self) -> None:
        """Pool initialises correctly with a single provider config."""
        pool = ProviderPoolManager(configs=[_proxy6_config()])
        assert len(pool.providers) == 1
        assert pool.providers[0].name == "proxy6"

    def test_pool_created_with_multiple_providers(self) -> None:
        """Pool handles multiple providers."""
        pool = ProviderPoolManager(
            configs=[_broken_config(), _proxy6_config()],
        )
        assert len(pool.providers) == 2

    def test_pool_status_structure(self) -> None:
        """get_pool_status() returns the expected keys."""
        pool = ProviderPoolManager(configs=[_proxy6_config()])
        status = asyncio.run(pool.get_pool_status())
        assert "providers" in status
        assert "usage" in status
        assert "strategy" in status
        assert len(status["providers"]) == 1
        prov = status["providers"][0]
        assert prov["name"] == "proxy6"
        assert "circuit" in prov


# ---------------------------------------------------------------------------
# API call (mocked when no proxy credentials)
# ---------------------------------------------------------------------------


class TestRealAPICall:
    @pytest.mark.asyncio
    async def test_hello_world_via_proxy6(self) -> None:
        """API call returns non-empty response with cost tracking."""
        pool = ProviderPoolManager(configs=[_proxy6_config()])

        if HAS_PROXY:
            response = await pool.execute(
                model=PROXY_MODEL,
                messages=[{"role": "user", "content": "Say exactly: hello"}],
                max_tokens=32,
            )
        else:
            mock_resp = _mock_response()
            with patch.object(
                pool.providers[0], "execute", new_callable=AsyncMock,
                return_value=mock_resp,
            ):
                response = await pool.execute(
                    model=PROXY_MODEL,
                    messages=[{"role": "user", "content": "Say exactly: hello"}],
                    max_tokens=32,
                )

        assert response.content
        assert response.provider_name == "proxy6"
        assert response.input_tokens >= 0
        assert response.output_tokens >= 0
        assert response.latency_ms > 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_stays_closed_after_success(self) -> None:
        """After a successful call, the circuit breaker stays CLOSED."""
        pool = ProviderPoolManager(configs=[_proxy6_config()])

        if HAS_PROXY:
            await pool.execute(
                model=PROXY_MODEL,
                messages=[{"role": "user", "content": "Say: ok"}],
                max_tokens=16,
            )
        else:
            with patch.object(
                pool.providers[0], "execute", new_callable=AsyncMock,
                return_value=_mock_response(),
            ):
                await pool.execute(
                    model=PROXY_MODEL,
                    messages=[{"role": "user", "content": "Say: ok"}],
                    max_tokens=16,
                )

        circuit = pool._circuits["proxy6"]
        assert circuit.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_cost_tracking_updates_after_call(self) -> None:
        """UsageTracker records cost after a successful API call."""
        pool = ProviderPoolManager(configs=[_proxy6_config()])

        if HAS_PROXY:
            await pool.execute(
                model=PROXY_MODEL,
                messages=[{"role": "user", "content": "Ping"}],
                max_tokens=16,
            )
        else:
            with patch.object(
                pool.providers[0], "execute", new_callable=AsyncMock,
                return_value=_mock_response(),
            ):
                await pool.execute(
                    model=PROXY_MODEL,
                    messages=[{"role": "user", "content": "Ping"}],
                    max_tokens=16,
                )

        stats = pool.tracker.get_all_stats()
        assert "proxy6" in stats
        pstats = stats["proxy6"]
        assert pstats["total_requests"] >= 1
        assert pstats["total_input_tokens"] >= 0
        assert pstats["total_output_tokens"] >= 0
        assert pstats["total_cost_usd"] >= 0


# ---------------------------------------------------------------------------
# Failover
# ---------------------------------------------------------------------------


class TestFailover:
    @pytest.mark.asyncio
    async def test_failover_from_broken_to_proxy6(self) -> None:
        """Broken provider fails, pool falls back to proxy6."""
        pool = ProviderPoolManager(
            configs=[
                _broken_config(name="broken", priority=2),
                _proxy6_config(name="proxy6", priority=1),
            ],
            failure_threshold=1,
            max_retries=2,
        )

        if HAS_PROXY:
            response = await pool.execute(
                model=PROXY_MODEL,
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=16,
            )
        else:
            # Mock only the good provider; broken will fail naturally
            good_provider = next(p for p in pool.providers if p.name == "proxy6")
            with patch.object(
                good_provider, "execute", new_callable=AsyncMock,
                return_value=_mock_response("proxy6"),
            ):
                response = await pool.execute(
                    model=PROXY_MODEL,
                    messages=[{"role": "user", "content": "Hello"}],
                    max_tokens=16,
                )

        assert response.content
        assert response.provider_name == "proxy6"

    @pytest.mark.asyncio
    async def test_all_providers_exhausted_raises(self) -> None:
        """ProviderPoolExhausted is raised when all providers fail."""
        pool = ProviderPoolManager(
            configs=[_broken_config(name="b1"), _broken_config(name="b2")],
            failure_threshold=1,
            max_retries=1,
        )

        with pytest.raises(ProviderPoolExhausted):
            await pool.execute(
                model="any-model",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=16,
            )


# ---------------------------------------------------------------------------
# Circuit breaker unit tests (no network needed)
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_circuit_starts_closed(self) -> None:
        from claw_forge.pool.health import CircuitBreaker

        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=60.0)
        assert cb.state == CircuitState.CLOSED

    def test_circuit_opens_after_threshold_failures(self) -> None:
        from claw_forge.pool.health import CircuitBreaker

        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=60.0)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_circuit_resets_to_closed(self) -> None:
        from claw_forge.pool.health import CircuitBreaker

        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED

    def test_circuit_records_success_closes(self) -> None:
        from claw_forge.pool.health import CircuitBreaker

        cb = CircuitBreaker("test", failure_threshold=5, recovery_timeout=60.0)
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_circuit_to_dict(self) -> None:
        from claw_forge.pool.health import CircuitBreaker

        cb = CircuitBreaker("myp", failure_threshold=5, recovery_timeout=30.0)
        d = cb.to_dict()
        assert d["name"] == "myp"
        assert "state" in d
        assert "failure_count" in d


# ---------------------------------------------------------------------------
# Pool reset_circuit (no network needed)
# ---------------------------------------------------------------------------


class TestPoolResetCircuit:
    def test_reset_circuit_by_name(self) -> None:
        """reset_circuit() manually closes a tripped circuit."""
        pool = ProviderPoolManager(
            configs=[_proxy6_config()],
            failure_threshold=1,
        )
        circuit = pool._circuits["proxy6"]
        circuit.record_failure()
        assert circuit.state == CircuitState.OPEN

        pool.reset_circuit("proxy6")
        assert circuit.state == CircuitState.CLOSED

    def test_reset_nonexistent_circuit_noop(self) -> None:
        """reset_circuit() on unknown name is a safe no-op."""
        pool = ProviderPoolManager(configs=[], max_retries=1)
        pool.reset_circuit("does-not-exist")  # should not raise


# ---------------------------------------------------------------------------
# provider/model format + provider pinning
# ---------------------------------------------------------------------------


class TestProviderSlashModelFormat:
    def test_provider_slash_model_format_in_pool(self) -> None:
        """Execute with provider_hint routes to the named provider."""
        pool = ProviderPoolManager(configs=[_proxy6_config()], max_retries=1)

        if HAS_PROXY:
            response = asyncio.run(pool.execute(
                model=PROXY_MODEL,
                messages=[{"role": "user", "content": "Say: pong"}],
                provider_hint="proxy6",
                max_tokens=32,
            ))
        else:
            async def _run() -> ProviderResponse:
                with patch.object(
                    pool.providers[0], "execute", new_callable=AsyncMock,
                    return_value=_mock_response(),
                ):
                    return await pool.execute(
                        model=PROXY_MODEL,
                        messages=[{"role": "user", "content": "Say: pong"}],
                        provider_hint="proxy6",
                        max_tokens=32,
                    )

            response = asyncio.run(_run())

        assert response.content
        assert isinstance(response.input_tokens, int)

    def test_unknown_provider_hint_raises(self) -> None:
        """provider_hint to unknown name raises ProviderNotFoundError."""
        from claw_forge.pool.manager import ProviderNotFoundError

        pool = ProviderPoolManager(configs=[], max_retries=1)

        async def _run() -> Any:
            return await pool.execute(
                model="some-model",
                messages=[],
                provider_hint="ghost-provider",
            )

        with pytest.raises(ProviderNotFoundError, match="ghost-provider"):
            asyncio.run(_run())
