"""Tests for ProviderPoolManager."""

from unittest.mock import Mock

import pytest

from claw_forge.pool.manager import ProviderPoolExhausted, ProviderPoolManager
from claw_forge.pool.providers.base import (
    BaseProvider,
    ProviderConfig,
    ProviderError,
    ProviderResponse,
    ProviderType,
    RateLimitError,
)


class MockProvider(BaseProvider):
    def __init__(self, config, response=None, error=None):
        super().__init__(config)
        self._response = response
        self._error = error
        self.call_count = 0

    async def execute(self, model, messages, **kwargs):
        self.call_count += 1
        if self._error:
            raise self._error
        return self._response or ProviderResponse(
            content="ok", model=model, provider_name=self.name,
            input_tokens=10, output_tokens=5, latency_ms=100.0,
        )


@pytest.fixture
def configs():
    return [
        ProviderConfig(name="primary", provider_type=ProviderType.ANTHROPIC, priority=1, api_key="k1"),  # noqa: E501
        ProviderConfig(name="fallback", provider_type=ProviderType.ANTHROPIC, priority=2, api_key="k2"),  # noqa: E501
    ]


class TestProviderPoolManager:
    @pytest.mark.asyncio
    async def test_basic_execute(self, configs):
        mgr = ProviderPoolManager(configs)
        primary_mock = MockProvider(configs[0])
        fallback_mock = MockProvider(configs[1])
        mgr._providers = [primary_mock, fallback_mock]
        mgr._circuits = {p.name: mgr._circuits.get(p.name, Mock()) for p in mgr._providers}
        # Re-init circuits
        from claw_forge.pool.health import CircuitBreaker
        mgr._circuits = {p.name: CircuitBreaker(p.name) for p in mgr._providers}

        result = await mgr.execute("claude-sonnet-4-20250514", [{"role": "user", "content": "hi"}])
        assert result.content == "ok"
        assert primary_mock.call_count == 1

    @pytest.mark.asyncio
    async def test_fallback_on_error(self, configs):
        mgr = ProviderPoolManager(configs)
        primary_mock = MockProvider(configs[0], error=ProviderError("fail", retryable=True))
        fallback_mock = MockProvider(configs[1])
        mgr._providers = [primary_mock, fallback_mock]
        from claw_forge.pool.health import CircuitBreaker
        mgr._circuits = {p.name: CircuitBreaker(p.name) for p in mgr._providers}

        result = await mgr.execute("claude-sonnet-4-20250514", [{"role": "user", "content": "hi"}])
        assert result.content == "ok"
        assert primary_mock.call_count == 1
        assert fallback_mock.call_count == 1

    @pytest.mark.asyncio
    async def test_pool_exhausted(self, configs):
        mgr = ProviderPoolManager(configs, max_retries=1)
        error = ProviderError("fail", retryable=False)
        mgr._providers = [MockProvider(c, error=error) for c in configs]
        from claw_forge.pool.health import CircuitBreaker
        mgr._circuits = {p.name: CircuitBreaker(p.name) for p in mgr._providers}

        with pytest.raises(ProviderPoolExhausted):
            await mgr.execute("claude-sonnet-4-20250514", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_rate_limit_fallback(self, configs):
        mgr = ProviderPoolManager(configs)
        primary_mock = MockProvider(configs[0], error=RateLimitError("limited", retry_after=0.01))
        fallback_mock = MockProvider(configs[1])
        mgr._providers = [primary_mock, fallback_mock]
        from claw_forge.pool.health import CircuitBreaker
        mgr._circuits = {p.name: CircuitBreaker(p.name) for p in mgr._providers}

        result = await mgr.execute("claude-sonnet-4-20250514", [{"role": "user", "content": "hi"}])
        assert result.content == "ok"

    @pytest.mark.asyncio
    async def test_pool_status(self, configs):
        mgr = ProviderPoolManager(configs)
        mgr._providers = [MockProvider(c) for c in configs]
        from claw_forge.pool.health import CircuitBreaker
        mgr._circuits = {p.name: CircuitBreaker(p.name) for p in mgr._providers}

        status = await mgr.get_pool_status()
        assert "providers" in status
        assert "usage" in status
        assert len(status["providers"]) == 2

    def test_reset_circuit(self, configs):
        mgr = ProviderPoolManager(configs)
        mgr._providers = [MockProvider(c) for c in configs]
        from claw_forge.pool.health import CircuitBreaker
        mgr._circuits = {p.name: CircuitBreaker(p.name, failure_threshold=1) for p in mgr._providers}  # noqa: E501
        mgr._circuits["primary"].record_failure()
        assert not mgr._circuits["primary"].is_available
        mgr.reset_circuit("primary")
        assert mgr._circuits["primary"].is_available
