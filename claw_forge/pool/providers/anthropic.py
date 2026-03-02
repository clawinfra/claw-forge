"""Direct Anthropic API provider."""

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


class AnthropicProvider(BaseProvider):
    """Provider for direct Anthropic API access."""

    API_VERSION = "2023-06-01"

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        if not config.api_key:
            raise ValueError(f"Anthropic provider '{config.name}' requires api_key")
        base = config.base_url or "https://api.anthropic.com"
        self._client = httpx.AsyncClient(
            base_url=base,
            headers={
                "x-api-key": config.api_key,
                "anthropic-version": self.API_VERSION,
                "content-type": "application/json",
            },
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
        text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
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
