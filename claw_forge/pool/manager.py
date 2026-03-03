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
            pinned_resp: ProviderResponse = cast(
                ProviderResponse,
                await pinned.execute(  # type: ignore[attr-defined]
                    model=model,
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
                    response: ProviderResponse = cast(
                        ProviderResponse,
                        await provider.execute(  # type: ignore[attr-defined]  # subclasses implement execute
                            model=model,
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

    async def get_pool_status(
        self, *, model_aliases: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Return current pool status including circuits, usage, and optional model aliases."""
        result: dict[str, Any] = {
            "providers": [
                {
                    "name": p.name,
                    "type": p.config.provider_type.value,
                    "priority": p.config.priority,
                    "enabled": p.config.enabled,
                    "circuit": self._circuits[p.name].to_dict(),
                }
                for p in self._providers
            ],
            "usage": self._tracker.get_all_stats(),
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
