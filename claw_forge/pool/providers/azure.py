"""Azure AI Foundry / Azure OpenAI provider."""

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


class AzureProvider(BaseProvider):
    """Provider for Azure OpenAI / Azure AI Foundry endpoints."""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        if not config.endpoint:
            raise ValueError(f"Azure provider '{config.name}' requires endpoint URL")
        if not config.api_key:
            raise ValueError(f"Azure provider '{config.name}' requires api_key")
        self._deployment = config.model_deployment
        self._client = httpx.AsyncClient(
            base_url=config.endpoint.rstrip("/"),
            headers={
                "api-key": config.api_key,
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
        deployment = self._deployment or self._resolve_model(model)
        msgs = list(messages)
        if system:
            msgs.insert(0, {"role": "system", "content": system})

        body: dict[str, Any] = {
            "messages": msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = [
                {"type": "function", "function": t} for t in tools
            ]

        path = f"/openai/deployments/{deployment}/chat/completions?api-version=2024-06-01"

        with self._timed() as timer:
            try:
                resp = await self._client.post(path, json=body)
            except httpx.TimeoutException as e:
                raise ProviderError(f"Timeout: {e}", retryable=True) from e

        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            raise RateLimitError(
                "Azure rate limited",
                retry_after=float(retry_after) if retry_after else None,
            )
        if resp.status_code in (401, 403):
            raise AuthenticationError("Azure auth failed")
        if resp.status_code >= 400:
            raise ProviderError(
                f"Azure error {resp.status_code}: {resp.text}",
                retryable=resp.status_code >= 500,
                status_code=resp.status_code,
            )

        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})

        return ProviderResponse(
            content=choice["message"].get("content", ""),
            model=data.get("model", deployment),
            provider_name=self.name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            stop_reason=choice.get("finish_reason"),
            raw=data,
            latency_ms=timer.elapsed_ms,
        )
