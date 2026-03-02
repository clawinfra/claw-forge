"""Ollama local provider — OpenAI-compatible /v1/chat/completions endpoint."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from claw_forge.pool.providers.base import (
    BaseProvider,
    ProviderConfig,
    ProviderError,
    ProviderResponse,
)

logger = logging.getLogger(__name__)

# Default model used when neither the call-site nor the config specifies one.
_DEFAULT_MODEL = "llama3.2"


class OllamaProvider(BaseProvider):
    """Calls a local Ollama instance via its OpenAI-compat /v1/chat/completions
    endpoint.

    Auth is optional — set ``api_key`` in the config if your Ollama instance
    requires a Bearer token (unusual for local deployments).

    Example config::

        providers:
          local-ollama:
            type: ollama
            base_url: "http://localhost:11434"
            model: "llama3.2"
            # api_key: optional, usually not needed

    The ``model`` config field sets a per-provider default that the caller can
    override by passing ``model=`` to :meth:`execute`.
    """

    DEFAULT_BASE_URL = "http://localhost:11434"

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self.base_url = (config.base_url or self.DEFAULT_BASE_URL).rstrip("/")

    # ------------------------------------------------------------------
    # Provider protocol
    # ------------------------------------------------------------------

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
        """Send a chat completion request to Ollama.

        The *model* parameter is resolved through the provider's
        ``model_map``.  If the resolved name is empty, fall back to the
        per-provider default set in config, then to ``"llama3.2"``.
        """
        resolved = self._resolve_model(model) or self._config.model or _DEFAULT_MODEL
        url = f"{self.base_url}/v1/chat/completions"

        msgs = list(messages)
        if system:
            msgs.insert(0, {"role": "system", "content": system})

        body: dict[str, Any] = {
            "model": resolved,
            "messages": msgs,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        body.update(kwargs)

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"

        with self._timed() as timer:
            try:
                async with httpx.AsyncClient(
                    timeout=self._config.timeout if hasattr(self._config, "timeout") else 120.0
                ) as client:
                    r = await client.post(url, json=body, headers=headers)
            except httpx.ConnectError as exc:
                raise ProviderError(
                    "Cannot connect to Ollama. Is it running? `ollama serve`",
                    retryable=True,
                ) from exc
            except httpx.TimeoutException as exc:
                raise ProviderError("Ollama request timed out", retryable=True) from exc

        if r.status_code == 404:
            raise ProviderError(
                f"Model '{resolved}' not found in Ollama. "
                f"Pull it first: ollama pull {resolved}",
                retryable=False,
            )
        if r.status_code >= 500:
            raise ProviderError(f"Ollama server error {r.status_code}", retryable=True)
        r.raise_for_status()

        data = r.json()
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

    # ------------------------------------------------------------------
    # Ollama-specific helpers
    # ------------------------------------------------------------------

    async def list_models(self) -> list[str]:
        """Return the names of locally available Ollama models."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{self.base_url}/api/tags")
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]

    async def health_check(self) -> bool:
        """Return ``True`` if the Ollama daemon is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{self.base_url}/api/tags")
                return r.status_code == 200
        except Exception:
            return False
