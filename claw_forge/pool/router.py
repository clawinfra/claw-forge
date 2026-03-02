"""Routing strategy for provider selection."""

from __future__ import annotations

import random
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claw_forge.pool.health import CircuitBreaker
    from claw_forge.pool.providers.base import BaseProvider
    from claw_forge.pool.tracker import UsageTracker


class RoutingStrategy(StrEnum):
    PRIORITY = "priority"
    ROUND_ROBIN = "round_robin"
    WEIGHTED_RANDOM = "weighted_random"
    LEAST_COST = "least_cost"
    LEAST_LATENCY = "least_latency"


class Router:
    """Select the next provider based on strategy, circuit state, and rate limits."""

    def __init__(
        self,
        strategy: RoutingStrategy = RoutingStrategy.PRIORITY,
    ) -> None:
        self.strategy = strategy
        self._rr_index = 0

    def select(
        self,
        providers: list[BaseProvider],
        circuits: dict[str, CircuitBreaker],
        tracker: UsageTracker,
    ) -> list[BaseProvider]:
        """Return providers in preferred order, filtering unavailable ones."""
        available = [
            p for p in providers
            if p.config.enabled
            and circuits.get(p.name, _DUMMY_CB).is_available
            and not tracker.is_rate_limited(p.name, p.config.max_rpm)
        ]

        if not available:
            return []

        if self.strategy == RoutingStrategy.PRIORITY:
            return sorted(available, key=lambda p: p.config.priority)

        if self.strategy == RoutingStrategy.ROUND_ROBIN:
            self._rr_index = self._rr_index % len(available)
            ordered = available[self._rr_index :] + available[: self._rr_index]
            self._rr_index = (self._rr_index + 1) % len(available)
            return ordered

        if self.strategy == RoutingStrategy.WEIGHTED_RANDOM:
            weights = [p.config.weight for p in available]
            shuffled = random.choices(available, weights=weights, k=len(available))
            # Deduplicate while preserving order
            seen: set[str] = set()
            result: list[BaseProvider] = []
            for p in shuffled:
                if p.name not in seen:
                    seen.add(p.name)
                    result.append(p)
            return result

        if self.strategy == RoutingStrategy.LEAST_COST:
            return sorted(available, key=lambda p: p.config.cost_per_mtok_input)

        if self.strategy == RoutingStrategy.LEAST_LATENCY:
            return sorted(
                available,
                key=lambda p: tracker.get_avg_latency(p.name),
            )

        return available


class _DummyCB:
    """Dummy circuit breaker that's always available."""

    @property
    def is_available(self) -> bool:
        return True


_DUMMY_CB = _DummyCB()
