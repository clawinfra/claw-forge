"""ProviderPoolManager — core multi-provider rotation with fallback."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, cast

from claw_forge.pool.health import CircuitBreaker, CircuitState
from claw_forge.pool.providers.base import (
    BaseProvider,
    ProviderConfig,
    ProviderError,
    ProviderResponse,
    RateLimitError,
)
from claw_forge.pool.providers.registry import create_providers_from_configs
from claw_forge.pool.router import Router, RoutingStrategy
from claw_forge.pool.tracker import UsageTracker

logger = logging.getLogger(__name__)


class ProviderPoolExhausted(Exception):
    """All providers failed or are unavailable."""


class ProviderNotFoundError(Exception):
    """Named provider does not exist in the pool."""


class ProviderUnavailableError(Exception):
    """Named provider exists but is currently unavailable."""


class ProviderPoolManager:
    """Multi-provider API rotation pool with circuit breaker, health checking,
    rate limit detection, and cost tracking.

    Fallback chain: try providers by priority, skip circuit-open or rate-limited ones.
    If all fail, raise ProviderPoolExhausted.
    """

    def __init__(
        self,
        configs: list[ProviderConfig],
        *,
        strategy: RoutingStrategy = RoutingStrategy.PRIORITY,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        backoff_max: float = 30.0,
    ) -> None:
        self._providers = create_providers_from_configs(configs)
        self._circuits: dict[str, CircuitBreaker] = {
            p.name: CircuitBreaker(
                name=p.name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
            )
            for p in self._providers
        }
        self._router = Router(strategy=strategy)
        self._tracker = UsageTracker()
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._lock = asyncio.Lock()
        # Per-provider active tier list (ordered model_map alias names, cheapest → smartest).
        # Empty list = use caller-supplied model (no tier routing).
        self._active_tiers: dict[str, list[str]] = {
            p.name: list(p.config.active_tiers) for p in self._providers
        }

    @property
    def providers(self) -> list[BaseProvider]:
        return list(self._providers)

    @property
    def tracker(self) -> UsageTracker:
        return self._tracker

    async def execute(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        provider_hint: str | None = None,
        complexity: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ProviderResponse:
        """Execute a request with automatic provider fallback.

        When ``provider_hint`` is set the request is pinned to that specific
        provider (skipping pool rotation).  Raises ``ProviderNotFoundError`` if
        the name is not registered, or ``ProviderUnavailableError`` if the
        provider is disabled / circuit-open.

        Without ``provider_hint``, tries providers in order determined by the
        routing strategy.  On failure, records the error, trips circuit breaker
        if needed, and falls through to the next provider.

        ``complexity`` is an optional hint ("low", "medium", "high") that
        selects a model tier from the provider's active_tiers list.  When None,
        the caller-supplied ``model`` is used directly.
        """
        # ── Pinned-provider fast path ─────────────────────────────────────
        if provider_hint is not None:
            provider_map = {p.name: p for p in self._providers}
            if provider_hint not in provider_map:
                available = ", ".join(sorted(provider_map.keys()))
                raise ProviderNotFoundError(
                    f"Provider {provider_hint!r} not found in pool. Available: {available}"
                )
            pinned = provider_map[provider_hint]
            cb = self._circuits[provider_hint]
            if not pinned.config.enabled or cb.state == CircuitState.OPEN:
                raise ProviderUnavailableError(
                    f"Pinned provider {provider_hint!r} is unavailable "
                    "(disabled or circuit open)"
                )
            if cb.state == CircuitState.HALF_OPEN:
                cb.record_half_open_attempt()
            effective_model = self.get_model_for_complexity(provider_hint, complexity) or model
            pinned_resp: ProviderResponse = cast(
                ProviderResponse,
                await pinned.execute(  # type: ignore[attr-defined]
                    model=effective_model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    tools=tools,
                    **kwargs,
                ),
            )
            cb.record_success()
            self._tracker.record_request(
                provider_name=pinned.name,
                input_tokens=pinned_resp.input_tokens,
                output_tokens=pinned_resp.output_tokens,
                cost_input_per_mtok=pinned.config.cost_per_mtok_input,
                cost_output_per_mtok=pinned.config.cost_per_mtok_output,
                latency_ms=pinned_resp.latency_ms,
            )
            return pinned_resp

        errors: list[tuple[str, Exception]] = []

        for attempt in range(self._max_retries):
            ordered = self._router.select(self._providers, self._circuits, self._tracker)
            if not ordered:
                if attempt < self._max_retries - 1:
                    wait = min(self._backoff_base * (2**attempt), self._backoff_max)
                    logger.warning("No providers available, backing off %.1fs", wait)
                    await asyncio.sleep(wait)
                    continue
                break

            for provider in ordered:
                cb = self._circuits[provider.name]
                if cb.state == CircuitState.HALF_OPEN:
                    cb.record_half_open_attempt()

                try:
                    effective_model = self.get_model_for_complexity(provider.name, complexity) or model
                    response: ProviderResponse = cast(
                        ProviderResponse,
                        await provider.execute(  # type: ignore[attr-defined]  # subclasses implement execute
                            model=effective_model,
                            messages=messages,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            system=system,
                            tools=tools,
                            **kwargs,
                        ),
                    )
                    cb.record_success()
                    self._tracker.record_request(
                        provider_name=provider.name,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        cost_input_per_mtok=provider.config.cost_per_mtok_input,
                        cost_output_per_mtok=provider.config.cost_per_mtok_output,
                        latency_ms=response.latency_ms,
                    )
                    return response

                except RateLimitError as e:
                    logger.warning("Rate limited on %s: %s", provider.name, e)
                    self._tracker.record_error(provider.name)
                    errors.append((provider.name, e))
                    if e.retry_after:
                        wait = min(e.retry_after, self._backoff_max)
                    else:
                        # Exponential backoff with jitter when no retry-after header
                        base_wait = min(
                            self._backoff_base * (2 ** attempt), self._backoff_max
                        )
                        jitter = random.uniform(0, base_wait * 0.5)  # noqa: S311
                        wait = base_wait + jitter
                    logger.info(
                        "Rate-limit backoff on %s: %.1fs (attempt %d)",
                        provider.name, wait, attempt,
                    )
                    await asyncio.sleep(wait)
                    continue

                except ProviderError as e:
                    logger.warning("Provider %s error: %s", provider.name, e)
                    cb.record_failure()
                    self._tracker.record_error(provider.name)
                    errors.append((provider.name, e))
                    if e.retryable:
                        # Exponential backoff with jitter for retryable errors
                        base_wait = min(
                            self._backoff_base * (2 ** attempt), self._backoff_max
                        )
                        jitter = random.uniform(0, 1)  # noqa: S311
                        wait = base_wait + jitter
                        logger.info(
                            "Retryable error backoff on %s: %.1fs (attempt %d)",
                            provider.name, wait, attempt,
                        )
                        await asyncio.sleep(wait)
                    continue

                except Exception as e:
                    logger.exception("Unexpected error from %s", provider.name)
                    cb.record_failure()
                    self._tracker.record_error(provider.name)
                    errors.append((provider.name, e))
                    continue

        error_summary = "; ".join(f"{n}: {e}" for n, e in errors)
        raise ProviderPoolExhausted(f"All providers exhausted. Errors: {error_summary}")

    def _derive_health(self, circuit_state: str) -> str:
        """Map circuit breaker state to a UI health label."""
        if circuit_state == "closed":
            return "healthy"
        if circuit_state == "half_open":
            return "degraded"
        return "unhealthy"

    async def get_pool_status(
        self, *, model_aliases: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Return current pool status including circuits, usage, and optional model aliases.

        Each provider dict is flattened to include usage stats, health,
        rpm, max_rpm, circuit_state, model, and avg_latency_ms so the
        frontend can consume the data directly.
        """
        usage = self._tracker.get_all_stats()
        providers = []
        for p in self._providers:
            cb = self._circuits[p.name]
            cb_dict = cb.to_dict()
            circuit_state = str(cb_dict.get("state", "closed"))
            p_usage = usage.get(p.name, {})
            providers.append({
                "name": p.name,
                "type": p.config.provider_type.value,
                "priority": p.config.priority,
                "enabled": p.config.enabled,
                "health": self._derive_health(circuit_state) if p.config.enabled else "unknown",
                "circuit_state": circuit_state,
                "circuit": cb_dict,
                "rpm": self._tracker.get_rpm(p.name),
                "max_rpm": p.config.max_rpm,
                "total_cost_usd": round(float(p_usage.get("total_cost_usd", 0) or 0), 6),
                "avg_latency_ms": round(float(p_usage.get("avg_latency_ms", 0) or 0), 1),
                "model": p.config.model or "",
                "model_map": dict(p.config.model_map),
                "active_tiers": list(self._active_tiers.get(p.name, [])),
            })
        result: dict[str, Any] = {
            "providers": providers,
            "usage": usage,
            "strategy": self._router.strategy.value,
        }
        if model_aliases is not None:
            result["model_aliases"] = model_aliases
        return result

    async def health_check_all(self) -> dict[str, bool]:
        """Run health checks on all providers concurrently."""
        async def _check(p: BaseProvider) -> tuple[str, bool]:
            try:
                ok = await p.health_check()
            except Exception:
                ok = False
            return p.name, ok

        results = await asyncio.gather(*[_check(p) for p in self._providers])
        return dict(results)

    def reset_circuit(self, provider_name: str) -> None:
        """Manually reset a provider's circuit breaker."""
        if provider_name in self._circuits:
            self._circuits[provider_name].reset()

    def disable_provider(self, name: str) -> bool:
        """Soft-disable a provider at runtime. Returns True if found."""
        for p in self._providers:
            if p.name == name:
                p.config.enabled = False
                return True
        return False

    def enable_provider(self, name: str) -> bool:
        """Re-enable a previously disabled provider. Returns True if found."""
        for p in self._providers:
            if p.name == name:
                p.config.enabled = True
                return True
        return False

    def get_provider_enabled(self, name: str) -> bool | None:
        """Returns enabled state, or None if provider not found."""
        for p in self._providers:
            if p.name == name:
                return p.config.enabled
        return None

    def get_model_for_complexity(self, provider_name: str, complexity: str | None) -> str | None:
        """Return the appropriate model ID for this provider based on task complexity.

        ``active_tiers`` is an ordered list of model_map alias names where the
        first entry is the cheapest/least-capable tier and the last is the
        most capable.  The complexity hint maps to a position in that list:

        - "low"    → first tier (cheapest)
        - "medium" → middle tier
        - "high"   → last tier (most capable)
        - None     → no tier routing; caller-supplied model is used

        Returns None when complexity is None, the provider has no active tiers,
        or the selected alias is not in model_map.
        """
        if complexity is None:
            return None
        tiers = self._active_tiers.get(provider_name)
        if not tiers:
            return None
        provider = next((p for p in self._providers if p.name == provider_name), None)
        if provider is None:
            return None
        if complexity == "low":
            alias = tiers[0]
        elif complexity == "high":
            alias = tiers[-1]
        else:  # "medium" or unrecognised
            alias = tiers[len(tiers) // 2]
        return provider.config.model_map.get(alias)

    def set_provider_tiers(self, name: str, active_tiers: list[str]) -> bool:
        """Update the active tier list for a provider at runtime.

        ``active_tiers`` is an ordered list of model_map alias names
        (cheapest first, most capable last).  Returns True if the provider
        was found.
        """
        for p in self._providers:
            if p.name == name:
                self._active_tiers[name] = list(active_tiers)
                p.config.active_tiers = list(active_tiers)
                return True
        return False
