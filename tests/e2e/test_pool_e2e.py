"""End-to-end tests for the ProviderPoolManager.

Real-API tests target a local Ollama instance (``OLLAMA_BASE_URL`` /
``OLLAMA_MODEL`` in ``.env``).  When Ollama is unreachable — typical on CI,
where ``.env`` isn't checked out and no Ollama daemon is running — tests
fall back to a mocked provider so they never skip.
"""

from __future__ import annotations

import asyncio
import os
import socket
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch
from urllib.parse import urlparse

import pytest

from claw_forge.pool.health import CircuitState
from claw_forge.pool.manager import ProviderPoolExhausted, ProviderPoolManager
from claw_forge.pool.providers.base import (
    ProviderConfig,
    ProviderResponse,
    ProviderType,
)

# ---------------------------------------------------------------------------
# Load .env from project root (Ollama backend)
# ---------------------------------------------------------------------------

_REAL_ENV_KEYS = ("OLLAMA_BASE_URL", "OLLAMA_MODEL", "OLLAMA_API_KEY")


def _load_env() -> dict[str, str]:
    """Read .env and return Ollama vars without polluting os.environ."""
    result: dict[str, str] = {}
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                if key in _REAL_ENV_KEYS:
                    result[key] = val.strip()
    return result


_env_vars = _load_env()


def _env(name: str, default: str = "") -> str:
    return _env_vars.get(name, "") or os.environ.get(name, default)


def _ollama_reachable(base_url: str, timeout: float = 0.5) -> bool:
    """Quick TCP probe of the Ollama host:port to gate the real-API path.

    Module-level reachability check is brief on purpose: we'd rather mock and
    move on than block test collection on a hung connection.  Connection
    refused / timeout / DNS failure all return False.
    """
    if not base_url:
        return False
    parsed = urlparse(base_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# Ollama (local OpenAI-compat endpoint).  Default port 11434; .env supplies
# OLLAMA_BASE_URL and OLLAMA_MODEL.
OLLAMA_BASE_URL = _env("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = _env("OLLAMA_MODEL", "llama3.2")
OLLAMA_API_KEY = _env("OLLAMA_API_KEY")  # usually empty for local setups

HAS_PROXY = _ollama_reachable(OLLAMA_BASE_URL)
PROXY_MODEL = OLLAMA_MODEL


def _proxy6_config(name: str = "proxy6", priority: int = 1) -> ProviderConfig:
    """Build the real-provider ProviderConfig pointing at local Ollama.

    The config name stays ``"proxy6"`` for assertion-compatibility with the
    rest of this file; only the underlying provider type and base URL change.
    """
    return ProviderConfig(
        name=name,
        provider_type=ProviderType.OLLAMA,
        api_key=OLLAMA_API_KEY or "ollama",  # Ollama ignores the key locally
        base_url=OLLAMA_BASE_URL,
        priority=priority,
        cost_per_mtok_input=0.0,
        cost_per_mtok_output=0.0,
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
