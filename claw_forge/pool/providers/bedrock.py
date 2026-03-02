"""AWS Bedrock provider using Anthropic Bedrock SDK."""

from __future__ import annotations

from typing import Any

from claw_forge.pool.providers.base import (
    BaseProvider,
    ProviderConfig,
    ProviderError,
    ProviderResponse,
    RateLimitError,
)


class BedrockProvider(BaseProvider):
    """Provider for Anthropic models via AWS Bedrock."""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._region = config.region or "us-east-1"
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from anthropic import AsyncAnthropicBedrock
            except ImportError as e:
                raise ProviderError(
                    "Install bedrock extras: pip install claw-forge[bedrock]",
                    retryable=False,
                ) from e
            self._client = AsyncAnthropicBedrock(aws_region=self._region)
        return self._client

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
        client = self._get_client()
        resolved = self._resolve_model(model)

        params: dict[str, Any] = {
            "model": resolved,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            params["system"] = system
        if tools:
            params["tools"] = tools

        with self._timed() as timer:
            try:
                response = await client.messages.create(**params)
            except Exception as e:
                err_str = str(e).lower()
                if "throttl" in err_str or "rate" in err_str:
                    raise RateLimitError(f"Bedrock rate limit: {e}") from e
                raise ProviderError(f"Bedrock error: {e}", retryable=True) from e

        content_blocks = response.content
        text = "".join(b.text for b in content_blocks if hasattr(b, "text"))

        return ProviderResponse(
            content=text,
            model=response.model,
            provider_name=self.name,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            stop_reason=response.stop_reason,
            raw=response,
            latency_ms=timer.elapsed_ms,
        )
