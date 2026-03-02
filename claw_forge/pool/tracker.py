"""Usage and cost tracking per provider."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class ProviderStats:
    """Accumulated stats for a single provider."""

    total_requests: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    total_errors: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    request_timestamps: list[float] = field(default_factory=list)

    @property
    def avg_latency_ms(self) -> float:
        if not self.latencies_ms:
            return float("inf")
        recent = self.latencies_ms[-100:]
        return sum(recent) / len(recent)


class UsageTracker:
    """Track usage, cost, and rate limits across providers."""

    def __init__(self) -> None:
        self._stats: dict[str, ProviderStats] = defaultdict(ProviderStats)

    def record_request(
        self,
        provider_name: str,
        input_tokens: int,
        output_tokens: int,
        cost_input_per_mtok: float,
        cost_output_per_mtok: float,
        latency_ms: float,
    ) -> None:
        stats = self._stats[provider_name]
        stats.total_requests += 1
        stats.total_input_tokens += input_tokens
        stats.total_output_tokens += output_tokens
        cost = (input_tokens * cost_input_per_mtok + output_tokens * cost_output_per_mtok) / 1_000_000
        stats.total_cost_usd += cost
        stats.latencies_ms.append(latency_ms)
        stats.request_timestamps.append(time.monotonic())
        # Keep only last 1000 timestamps for rate limiting
        if len(stats.request_timestamps) > 1000:
            stats.request_timestamps = stats.request_timestamps[-500:]
        if len(stats.latencies_ms) > 1000:
            stats.latencies_ms = stats.latencies_ms[-500:]

    def record_error(self, provider_name: str) -> None:
        self._stats[provider_name].total_errors += 1

    def is_rate_limited(self, provider_name: str, max_rpm: int) -> bool:
        stats = self._stats.get(provider_name)
        if not stats or not stats.request_timestamps:
            return False
        cutoff = time.monotonic() - 60.0
        recent = sum(1 for t in stats.request_timestamps if t > cutoff)
        return recent >= max_rpm

    def get_avg_latency(self, provider_name: str) -> float:
        stats = self._stats.get(provider_name)
        if not stats:
            return float("inf")
        return stats.avg_latency_ms

    def get_stats(self, provider_name: str) -> ProviderStats:
        return self._stats[provider_name]

    def get_all_stats(self) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for name, stats in self._stats.items():
            result[name] = {
                "total_requests": stats.total_requests,
                "total_input_tokens": stats.total_input_tokens,
                "total_output_tokens": stats.total_output_tokens,
                "total_cost_usd": round(stats.total_cost_usd, 6),
                "total_errors": stats.total_errors,
                "avg_latency_ms": round(stats.avg_latency_ms, 1),
            }
        return result

    def reset(self) -> None:
        self._stats.clear()
