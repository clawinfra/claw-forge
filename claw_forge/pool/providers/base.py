"""Base provider protocol and types."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class ProviderType(str, Enum):
    """Supported provider backends."""

    ANTHROPIC = "anthropic"
    BEDROCK = "bedrock"
    AZURE = "azure"
    VERTEX = "vertex"
    OPENAI_COMPAT = "openai_compat"
    ANTHROPIC_COMPAT = "anthropic_compat"
    ANTHROPIC_OAUTH = "anthropic_oauth"
    OLLAMA = "ollama"


@dataclass
class ProviderConfig:
    """Configuration for a single provider endpoint."""

    name: str
    provider_type: ProviderType
    priority: int = 1
    weight: float = 1.0
    max_rpm: int = 60
    max_tpd: int = 1_000_000
    cost_per_mtok_input: float = 3.0
    cost_per_mtok_output: float = 15.0
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    # Provider-specific fields
    api_key: str | None = None
    base_url: str | None = None
    region: str | None = None
    project_id: str | None = None
    endpoint: str | None = None
    model_deployment: str | None = None
    model: str | None = None
    model_map: dict[str, str] = field(default_factory=dict)
    # OAuth token support (Claude CLI `claude login`)
    oauth_token: str | None = None
    oauth_token_file: str | None = None


@dataclass
class ProviderResponse:
    """Normalized response from any provider."""

    content: str
    model: str
    provider_name: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None
    raw: Any = None
    latency_ms: float = 0.0


class ProviderError(Exception):
    """Base error for provider failures."""

    def __init__(self, message: str, *, retryable: bool = True, status_code: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class RateLimitError(ProviderError):
    """Rate limit hit — should back off."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message, retryable=True, status_code=429)
        self.retry_after = retry_after


class AuthenticationError(ProviderError):
    """Bad credentials — not retryable on same provider."""

    def __init__(self, message: str):
        super().__init__(message, retryable=False, status_code=401)


@runtime_checkable
class Provider(Protocol):
    """Protocol that all provider backends must implement."""

    @property
    def name(self) -> str: ...

    @property
    def config(self) -> ProviderConfig: ...

    async def execute(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ProviderResponse: ...

    async def health_check(self) -> bool: ...


class BaseProvider:
    """Shared base for provider implementations."""

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def config(self) -> ProviderConfig:
        return self._config

    def _resolve_model(self, model: str) -> str:
        """Resolve model name through provider's model_map."""
        return self._config.model_map.get(model, model)

    def _timed(self) -> _Timer:
        return _Timer()

    async def health_check(self) -> bool:
        """Default health check — try a minimal request."""
        try:
            await self.execute(
                model="claude-sonnet-4-20250514",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            return True
        except Exception:
            return False


class _Timer:
    """Context manager to measure elapsed time in ms."""

    def __init__(self) -> None:
        self.start: float = 0.0
        self.elapsed_ms: float = 0.0

    def __enter__(self) -> "_Timer":
        self.start = time.monotonic()
        return self

    def __exit__(self, *_: Any) -> None:
        self.elapsed_ms = (time.monotonic() - self.start) * 1000
