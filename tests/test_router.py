"""Tests for routing strategy."""

from claw_forge.pool.health import CircuitBreaker
from claw_forge.pool.providers.base import BaseProvider, ProviderConfig, ProviderResponse, ProviderType
from claw_forge.pool.router import Router, RoutingStrategy
from claw_forge.pool.tracker import UsageTracker


class FakeProvider(BaseProvider):
    async def execute(self, model, messages, **kwargs):
        return ProviderResponse(content="ok", model=model, provider_name=self.name)


def _make_providers(n=3):
    providers = []
    for i in range(n):
        cfg = ProviderConfig(
            name=f"p{i}",
            provider_type=ProviderType.ANTHROPIC,
            priority=i,
            weight=float(n - i),
            cost_per_mtok_input=float(i + 1),
        )
        providers.append(FakeProvider(cfg))
    return providers


class TestRouter:
    def test_priority_ordering(self):
        r = Router(strategy=RoutingStrategy.PRIORITY)
        providers = _make_providers()
        result = r.select(providers, {}, UsageTracker())
        assert [p.name for p in result] == ["p0", "p1", "p2"]

    def test_least_cost_ordering(self):
        r = Router(strategy=RoutingStrategy.LEAST_COST)
        providers = _make_providers()
        result = r.select(providers, {}, UsageTracker())
        assert result[0].name == "p0"  # cheapest

    def test_skips_circuit_open(self):
        r = Router(strategy=RoutingStrategy.PRIORITY)
        providers = _make_providers()
        cb = CircuitBreaker("p0", failure_threshold=1)
        cb.record_failure()
        result = r.select(providers, {"p0": cb}, UsageTracker())
        assert "p0" not in [p.name for p in result]

    def test_skips_rate_limited(self):
        r = Router(strategy=RoutingStrategy.PRIORITY)
        providers = _make_providers()
        tracker = UsageTracker()
        for _ in range(60):
            tracker.record_request("p0", 10, 10, 1.0, 1.0, 10.0)
        providers[0]._config.max_rpm = 60
        result = r.select(providers, {}, tracker)
        assert "p0" not in [p.name for p in result]

    def test_skips_disabled(self):
        r = Router(strategy=RoutingStrategy.PRIORITY)
        providers = _make_providers()
        providers[0]._config.enabled = False
        result = r.select(providers, {}, UsageTracker())
        assert "p0" not in [p.name for p in result]

    def test_round_robin(self):
        r = Router(strategy=RoutingStrategy.ROUND_ROBIN)
        providers = _make_providers(2)
        t = UsageTracker()
        first = r.select(providers, {}, t)
        second = r.select(providers, {}, t)
        assert first[0].name != second[0].name

    def test_empty_when_all_unavailable(self):
        r = Router(strategy=RoutingStrategy.PRIORITY)
        providers = _make_providers(1)
        cb = CircuitBreaker("p0", failure_threshold=1)
        cb.record_failure()
        result = r.select(providers, {"p0": cb}, UsageTracker())
        assert result == []
