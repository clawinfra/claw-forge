"""Generic OpenAI-compatible provider (Groq, proxies, local endpoints)."""

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


class OpenAICompatProvider(BaseProvider):
    """Provider for any OpenAI-compatible API endpoint."""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        if not config.base_url:
            raise ValueError(f"OpenAI-compat provider '{config.name}' requires base_url")
        headers: dict[str, str] = {"content-type": "application/json"}
        if config.api_key:
            headers["authorization"] = f"Bearer {config.api_key}"
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
        msgs = list(messages)
        if system:
            msgs.insert(0, {"role": "system", "content": system})

        body: dict[str, Any] = {
            "model": resolved,
            "messages": msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]

        with self._timed() as timer:
            try:
                resp = await self._client.post("/v1/chat/completions", json=body)
            except httpx.TimeoutException as e:
                raise ProviderError(f"Timeout: {e}", retryable=True) from e

        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            raise RateLimitError(
                "Rate limited",
                retry_after=float(retry_after) if retry_after else None,
            )
        if resp.status_code in (401, 403):
            raise AuthenticationError("Authentication failed")
        if resp.status_code >= 400:
            raise ProviderError(
                f"Error {resp.status_code}: {resp.text}",
                retryable=resp.status_code >= 500,
                status_code=resp.status_code,
            )

        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})

        return ProviderResponse(
            content=choice["message"].get("content", ""),
            model=data.get("model", resolved),
            provider_name=self.name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            stop_reason=choice.get("finish_reason"),
            raw=data,
            latency_ms=timer.elapsed_ms,
        )
