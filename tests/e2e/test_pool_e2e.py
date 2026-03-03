"""End-to-end tests for the ProviderPoolManager.

Tests real API calls against proxy-6 (z.ai), circuit breaker behaviour,
provider failover, and cost tracking.

Set PROXY_1_* env vars (already present in /tmp/claw-forge/.env):
  PROXY_1_API_KEY  - API key for z.ai proxy
  PROXY_1_BASE_URL - Base URL (https://api.z.ai/api/anthropic/v1)
  PROXY_1_MODEL    - Model name (glm-4.5-air)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from claw_forge.pool.health import CircuitState
from claw_forge.pool.manager import ProviderPoolExhausted, ProviderPoolManager
from claw_forge.pool.providers.base import ProviderConfig, ProviderType

# ---------------------------------------------------------------------------
# Load .env from project root (proxy-6 credentials)
# ---------------------------------------------------------------------------

def _load_env() -> None:
    """Load .env file into os.environ if vars not already set."""
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())


_load_env()

PROXY_API_KEY = os.environ.get("PROXY_1_API_KEY", "")
_raw_base = os.environ.get("PROXY_1_BASE_URL", "")
# The AnthropicCompatProvider posts to /v1/messages, so strip trailing /v1
# to avoid double-pathing (e.g. .../v1/v1/messages).
PROXY_BASE_URL = _raw_base.rstrip("/").removesuffix("/v1") if _raw_base else ""
PROXY_MODEL = os.environ.get("PROXY_1_MODEL", "glm-4.5-air")

HAS_PROXY = bool(PROXY_API_KEY and PROXY_BASE_URL)


def _proxy6_config(name: str = "proxy6", priority: int = 1) -> ProviderConfig:
    """Build ProviderConfig for the z.ai proxy-6 endpoint."""
    return ProviderConfig(
        name=name,
        provider_type=ProviderType.ANTHROPIC_COMPAT,
        api_key=PROXY_API_KEY,
        base_url=PROXY_BASE_URL,
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


# ---------------------------------------------------------------------------
# Pool construction
# ---------------------------------------------------------------------------


class TestPoolConstruction:
    def test_pool_created_with_proxy6(self) -> None:
        """Pool initialises correctly with a single provider config."""
        if not HAS_PROXY:
            pytest.skip("PROXY_1_* env vars not set")
        pool = ProviderPoolManager(configs=[_proxy6_config()])
        assert len(pool.providers) == 1
        assert pool.providers[0].name == "proxy6"

    def test_pool_created_with_multiple_providers(self) -> None:
        """Pool handles multiple providers, skipping ones that can't be initialized."""
        if not HAS_PROXY:
            pytest.skip("PROXY_1_* env vars not set")
        pool = ProviderPoolManager(configs=[_broken_config(), _proxy6_config()])
        # Both should appear (broken just hasn't failed yet)
        assert len(pool.providers) == 2

    def test_pool_status_structure(self) -> None:
        """get_pool_status() returns the expected keys."""
        if not HAS_PROXY:
            pytest.skip("PROXY_1_* env vars not set")

        import asyncio

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
# Real API call
# ---------------------------------------------------------------------------


class TestRealAPICall:
    @pytest.mark.asyncio
    async def test_hello_world_via_proxy6(self) -> None:
        """Make a real API call — response must be non-empty and cost tracked."""
        if not HAS_PROXY:
            pytest.skip("PROXY_1_* env vars not set")

        pool = ProviderPoolManager(configs=[_proxy6_config()])

        response = await pool.execute(
            model=PROXY_MODEL,
            messages=[{"role": "user", "content": "Say exactly: hello"}],
            max_tokens=32,
        )

        assert response.content  # non-empty
        assert response.provider_name == "proxy6"
        assert response.input_tokens >= 0
        assert response.output_tokens >= 0
        assert response.latency_ms > 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_stays_closed_after_success(self) -> None:
        """After a successful call, the circuit breaker stays CLOSED."""
        if not HAS_PROXY:
            pytest.skip("PROXY_1_* env vars not set")

        pool = ProviderPoolManager(configs=[_proxy6_config()])
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
        if not HAS_PROXY:
            pytest.skip("PROXY_1_* env vars not set")

        pool = ProviderPoolManager(configs=[_proxy6_config()])
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
        """Broken provider (highest priority) fails, pool falls back to proxy6."""
        if not HAS_PROXY:
            pytest.skip("PROXY_1_* env vars not set")

        # broken has priority=2 (highest), proxy6 has priority=1
        pool = ProviderPoolManager(
            configs=[
                _broken_config(name="broken", priority=2),
                _proxy6_config(name="proxy6", priority=1),
            ],
            failure_threshold=1,  # trip circuit after 1 failure
            max_retries=2,
        )

        response = await pool.execute(
            model=PROXY_MODEL,
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=16,
        )

        # We got a response from proxy6 despite broken being first
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
        # Multiple failures but still under threshold
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        # A success doesn't change state while closed
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
# Pool reset_circuit
# ---------------------------------------------------------------------------


class TestPoolResetCircuit:
    def test_reset_circuit_by_name(self) -> None:
        """reset_circuit() manually closes a tripped circuit."""
        if not HAS_PROXY:
            pytest.skip("PROXY_1_* env vars not set")

        pool = ProviderPoolManager(
            configs=[_proxy6_config()],
            failure_threshold=1,
        )
        circuit = pool._circuits["proxy6"]
        # Trip it
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
        """Create pool with proxy-6, execute with provider_hint='proxy6' to verify routing."""
        if not HAS_PROXY:
            pytest.skip("PROXY_1_* env vars not set")

        import asyncio

        pool = ProviderPoolManager(configs=[_proxy6_config()], max_retries=1)

        async def _run() -> Any:
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
        import asyncio

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
