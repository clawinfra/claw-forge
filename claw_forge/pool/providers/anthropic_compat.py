"""Anthropic-compatible provider for proxies exposing the Anthropic API format.

Use this when you have a proxy at a custom ``base_url`` that accepts the same
``x-api-key`` header and ``/v1/messages`` endpoint as ``api.anthropic.com``.

Supports:
- Custom ``base_url`` (required)
- Custom ``api_key`` (optional — set to ``null`` for internal no-auth proxies)
- Optional ``model_map`` for renaming models at the proxy level
- Same rate-limit / error classification as :class:`AnthropicProvider`

Config example::

    providers:
      my-proxy:
        type: anthropic_compat
        api_key: sk-my-proxy-key
        base_url: https://proxy.example.com/v1
        model_map:
          claude-sonnet-4-6: my-claude-sonnet   # optional rename

      internal-gateway:
        type: anthropic_compat
        api_key: null                            # no auth for internal proxy
        base_url: http://internal-gateway:8080/v1
"""

from __future__ import annotations

from typing import Any

import httpx

from claw_forge.pool.providers.base import (
    AuthenticationError,
    BaseProvider,
    ProviderConfig,
    ProviderError,
    ProviderResponse,
    RateLimitError,
)


class AnthropicCompatProvider(BaseProvider):
    """Provider for Anthropic-format API proxies.

    Identical wire format to :class:`AnthropicProvider` (``x-api-key`` header,
    ``/v1/messages`` endpoint, ``anthropic-version`` header) but targets an
    arbitrary ``base_url`` instead of ``https://api.anthropic.com``.

    Key differences from :class:`OpenAICompatProvider`:
    - Uses ``x-api-key`` header (not ``Authorization: Bearer``)
    - Hits ``/v1/messages`` (not ``/v1/chat/completions``)
    - Sends ``anthropic-version: 2023-06-01`` header
    - Parses Anthropic-style response (``content`` blocks, ``usage.input_tokens``)
    - Supports ``api_key: null`` for no-auth internal proxies
    """

    API_VERSION = "2023-06-01"

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        if not config.base_url:
            raise ValueError(
                f"AnthropicCompat provider '{config.name}' requires base_url"
            )
        headers: dict[str, str] = {
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
        }
        if config.api_key:
            headers["x-api-key"] = config.api_key
        # Else: no auth header — internal proxies that skip auth entirely

        self._client = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(300.0, connect=10.0),
        )

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
    ) -> ProviderResponse:
        resolved = self._resolve_model(model)
        body: dict[str, Any] = {
            "model": resolved,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = tools

        with self._timed() as timer:
            try:
                resp = await self._client.post("/v1/messages", json=body)
            except httpx.TimeoutException as e:
                raise ProviderError(f"Timeout: {e}", retryable=True) from e

        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            raise RateLimitError(
                "Rate limited",
                retry_after=float(retry_after) if retry_after else None,
            )
        if resp.status_code == 401:
            raise AuthenticationError("Invalid API key")
        if resp.status_code == 529:
            # Anthropic overload
            raise RateLimitError("API overloaded (529)")
        if resp.status_code >= 500:
            raise ProviderError(f"Server error {resp.status_code}", retryable=True)
        if resp.status_code >= 400:
            raise ProviderError(
                f"Client error {resp.status_code}: {resp.text}",
                retryable=False,
                status_code=resp.status_code,
            )

        data = resp.json()
        content_blocks = data.get("content", [])
        text = "".join(
            b.get("text", "") for b in content_blocks if b.get("type") == "text"
        )
        usage = data.get("usage", {})

        return ProviderResponse(
            content=text,
            model=data.get("model", resolved),
            provider_name=self.name,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            stop_reason=data.get("stop_reason"),
            raw=data,
            latency_ms=timer.elapsed_ms,
        )
