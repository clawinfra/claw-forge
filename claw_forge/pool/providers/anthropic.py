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
    """Provider for direct Anthropic API access.

    Supports three auth modes (in order of precedence):
    1. ``oauth_token`` — Bearer token from ``claude login``
    2. ``oauth_token_file`` — Path to file containing the token (auto-refreshed on 401)
    3. ``api_key`` — Classic ``x-api-key`` header
    """

    API_VERSION = "2023-06-01"

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        if not config.api_key and not config.oauth_token and not config.oauth_token_file:
            raise ValueError(
                f"Anthropic provider '{config.name}' requires api_key, oauth_token, "
                "or oauth_token_file"
            )
        self._base_url = config.base_url or "https://api.anthropic.com"
        self._client = self._build_client(config)

    def _build_client(self, config: ProviderConfig) -> httpx.AsyncClient:
        """Build the HTTP client with appropriate auth headers."""
        headers: dict[str, str] = {
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
        }
        # OAuth token takes priority over api_key
        token = config.oauth_token or self._read_token_file(config.oauth_token_file)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif config.api_key:
            headers["x-api-key"] = config.api_key
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=httpx.Timeout(300.0, connect=10.0),
        )

    @staticmethod
    def _read_token_file(path: str | None) -> str | None:
        """Read a token from a file path, returning None on any error."""
        if not path:
            return None
        try:
            from pathlib import Path

            text = Path(path).read_text().strip()
            return text or None
        except Exception:
            return None

    async def _refresh_client_from_file(self) -> None:
        """Re-read oauth_token_file and rebuild client (called on 401)."""
        if self._config.oauth_token_file:
            new_token = self._read_token_file(self._config.oauth_token_file)
            if new_token:
                await self._client.aclose()
                # Temporarily set oauth_token to the new value for client build
                old_token = self._config.oauth_token
                object.__setattr__(self._config, "oauth_token", new_token)
                self._client = self._build_client(self._config)
                object.__setattr__(self._config, "oauth_token", old_token)

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
            # For oauth_token_file, try refreshing the token once
            if self._config.oauth_token_file:
                await self._refresh_client_from_file()
                raise ProviderError("OAuth token expired — refreshed, retry", retryable=True, status_code=401)  # noqa: E501
            raise AuthenticationError("Invalid API key or OAuth token")
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
