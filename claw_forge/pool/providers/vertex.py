"""Google Vertex AI provider using Anthropic Vertex SDK."""

from __future__ import annotations

from typing import Any

from claw_forge.pool.providers.base import (
    BaseProvider,
    ProviderConfig,
    ProviderError,
    ProviderResponse,
    RateLimitError,
)


class VertexProvider(BaseProvider):
    """Provider for Anthropic models via Google Vertex AI."""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._region = config.region or "us-east5"
        self._project_id = config.project_id
        if not self._project_id:
            raise ValueError(f"Vertex provider '{config.name}' requires project_id")
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from anthropic import AsyncAnthropicVertex
            except ImportError as e:
                raise ProviderError(
                    "Install vertex extras: pip install claw-forge[vertex]",
                    retryable=False,
                ) from e
            assert self._project_id is not None  # guaranteed by __init__ check
            self._client = AsyncAnthropicVertex(
                project_id=self._project_id,
                region=self._region,
            )
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
                if "quota" in err_str or "rate" in err_str or "429" in err_str:
                    raise RateLimitError(f"Vertex rate limit: {e}") from e
                raise ProviderError(f"Vertex error: {e}", retryable=True) from e

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
