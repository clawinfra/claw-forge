"""Tests for AnthropicCompatProvider."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from claw_forge.pool.providers.anthropic_compat import AnthropicCompatProvider
from claw_forge.pool.providers.base import (
    AuthenticationError,
    ProviderConfig,
    ProviderError,
    ProviderType,
    RateLimitError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**kwargs: Any) -> ProviderConfig:
    defaults: dict[str, Any] = {
        "name": "test-proxy",
        "provider_type": ProviderType.ANTHROPIC_COMPAT,
        "base_url": "https://proxy.example.com/v1",
        "api_key": "sk-test-key",
    }
    defaults.update(kwargs)
    return ProviderConfig(**defaults)


def _make_response(status: int = 200, json_body: dict[str, Any] | None = None) -> Mock:
    resp = Mock(spec=httpx.Response)
    resp.status_code = status
    resp.text = ""
    resp.headers = {}
    resp.json = Mock(
        return_value=json_body
        or {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-6",
            "content": [{"type": "text", "text": "Hello!"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
    )
    return resp


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestAnthropicCompatProviderInit:
    def test_requires_base_url(self) -> None:
        cfg = _make_config(base_url=None)
        with pytest.raises(ValueError, match="requires base_url"):
            AnthropicCompatProvider(cfg)

    def test_sets_x_api_key_header(self) -> None:
        cfg = _make_config(api_key="sk-secret")
        provider = AnthropicCompatProvider(cfg)
        headers = dict(provider._client.headers)
        assert headers.get("x-api-key") == "sk-secret"

    def test_sets_anthropic_version_header(self) -> None:
        cfg = _make_config()
        provider = AnthropicCompatProvider(cfg)
        headers = dict(provider._client.headers)
        assert headers.get("anthropic-version") == "2023-06-01"

    def test_no_bearer_auth_header(self) -> None:
        """Must use x-api-key, NOT Authorization: Bearer."""
        cfg = _make_config(api_key="sk-foo")
        provider = AnthropicCompatProvider(cfg)
        headers = dict(provider._client.headers)
        assert "authorization" not in headers

    def test_null_api_key_skips_auth_header(self) -> None:
        """Proxies without auth (api_key=None) should receive no x-api-key."""
        cfg = _make_config(api_key=None)
        provider = AnthropicCompatProvider(cfg)
        headers = dict(provider._client.headers)
        assert "x-api-key" not in headers

    def test_base_url_trailing_slash_stripped(self) -> None:
        cfg = _make_config(base_url="https://proxy.example.com/v1/")
        provider = AnthropicCompatProvider(cfg)
        assert str(provider._client.base_url).rstrip("/") == "https://proxy.example.com/v1"


# ---------------------------------------------------------------------------
# execute — happy path
# ---------------------------------------------------------------------------


class TestAnthropicCompatExecute:
    @pytest.mark.asyncio
    async def test_posts_to_messages_endpoint(self) -> None:
        cfg = _make_config()
        provider = AnthropicCompatProvider(cfg)

        mock_resp = _make_response()
        provider._client.post = AsyncMock(return_value=mock_resp)

        await provider.execute(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "Hi"}],
        )

        call_args = provider._client.post.call_args
        assert call_args[0][0] == "/v1/messages"

    @pytest.mark.asyncio
    async def test_not_chat_completions(self) -> None:
        """Must hit /v1/messages, NOT /v1/chat/completions."""
        cfg = _make_config()
        provider = AnthropicCompatProvider(cfg)
        provider._client.post = AsyncMock(return_value=_make_response())

        await provider.execute(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "Hi"}],
        )

        path = provider._client.post.call_args[0][0]
        assert "chat/completions" not in path

    @pytest.mark.asyncio
    async def test_model_map_renames_model(self) -> None:
        cfg = _make_config(
            model_map={"claude-sonnet-4-6": "proxy-internal-sonnet"}
        )
        provider = AnthropicCompatProvider(cfg)
        provider._client.post = AsyncMock(return_value=_make_response())

        await provider.execute(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "Hi"}],
        )

        body = provider._client.post.call_args[1]["json"]
        assert body["model"] == "proxy-internal-sonnet"

    @pytest.mark.asyncio
    async def test_unknown_model_passes_through(self) -> None:
        cfg = _make_config(model_map={"a": "b"})
        provider = AnthropicCompatProvider(cfg)
        provider._client.post = AsyncMock(return_value=_make_response())

        await provider.execute(
            model="claude-opus-4-5",
            messages=[{"role": "user", "content": "Hi"}],
        )

        body = provider._client.post.call_args[1]["json"]
        assert body["model"] == "claude-opus-4-5"

    @pytest.mark.asyncio
    async def test_returns_provider_response(self) -> None:
        cfg = _make_config()
        provider = AnthropicCompatProvider(cfg)
        provider._client.post = AsyncMock(return_value=_make_response())

        result = await provider.execute(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "Hi"}],
        )

        assert result.content == "Hello!"
        assert result.provider_name == "test-proxy"
        assert result.input_tokens == 10
        assert result.output_tokens == 5

    @pytest.mark.asyncio
    async def test_passes_system_prompt(self) -> None:
        cfg = _make_config()
        provider = AnthropicCompatProvider(cfg)
        provider._client.post = AsyncMock(return_value=_make_response())

        await provider.execute(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "Hi"}],
            system="You are helpful.",
        )

        body = provider._client.post.call_args[1]["json"]
        assert body.get("system") == "You are helpful."


# ---------------------------------------------------------------------------
# execute — error handling
# ---------------------------------------------------------------------------


class TestAnthropicCompatErrors:
    @pytest.mark.asyncio
    async def test_rate_limit_raises_rate_limit_error(self) -> None:
        cfg = _make_config()
        provider = AnthropicCompatProvider(cfg)
        resp = _make_response(status=429)
        resp.headers = {"retry-after": "5"}
        provider._client.post = AsyncMock(return_value=resp)

        with pytest.raises(RateLimitError) as exc_info:
            await provider.execute("claude-sonnet-4-6", [{"role": "user", "content": "Hi"}])

        assert exc_info.value.retry_after == 5.0

    @pytest.mark.asyncio
    async def test_overload_529_raises_rate_limit_error(self) -> None:
        cfg = _make_config()
        provider = AnthropicCompatProvider(cfg)
        resp = _make_response(status=529)
        resp.headers = {}
        provider._client.post = AsyncMock(return_value=resp)

        with pytest.raises(RateLimitError):
            await provider.execute("claude-sonnet-4-6", [{"role": "user", "content": "Hi"}])

    @pytest.mark.asyncio
    async def test_401_raises_authentication_error(self) -> None:
        cfg = _make_config()
        provider = AnthropicCompatProvider(cfg)
        resp = _make_response(status=401)
        resp.headers = {}
        provider._client.post = AsyncMock(return_value=resp)

        with pytest.raises(AuthenticationError):
            await provider.execute("claude-sonnet-4-6", [{"role": "user", "content": "Hi"}])

    @pytest.mark.asyncio
    async def test_500_raises_retryable_provider_error(self) -> None:
        cfg = _make_config()
        provider = AnthropicCompatProvider(cfg)
        resp = _make_response(status=500)
        resp.headers = {}
        provider._client.post = AsyncMock(return_value=resp)

        with pytest.raises(ProviderError) as exc_info:
            await provider.execute("claude-sonnet-4-6", [{"role": "user", "content": "Hi"}])

        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_400_raises_non_retryable_provider_error(self) -> None:
        cfg = _make_config()
        provider = AnthropicCompatProvider(cfg)
        resp = _make_response(status=400)
        resp.headers = {}
        provider._client.post = AsyncMock(return_value=resp)

        with pytest.raises(ProviderError) as exc_info:
            await provider.execute("claude-sonnet-4-6", [{"role": "user", "content": "Hi"}])

        assert exc_info.value.retryable is False

    @pytest.mark.asyncio
    async def test_timeout_raises_retryable_error(self) -> None:
        cfg = _make_config()
        provider = AnthropicCompatProvider(cfg)
        provider._client.post = AsyncMock(
            side_effect=httpx.TimeoutException("timed out")
        )

        with pytest.raises(ProviderError) as exc_info:
            await provider.execute("claude-sonnet-4-6", [{"role": "user", "content": "Hi"}])

        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_null_api_key_no_x_api_key_sent(self) -> None:
        """When api_key is None, no x-api-key header should be sent."""
        cfg = _make_config(api_key=None)
        provider = AnthropicCompatProvider(cfg)
        provider._client.post = AsyncMock(return_value=_make_response())

        await provider.execute(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "Hi"}],
        )
        # Passes without error — proxy accepted the keyless request
        provider._client.post.assert_awaited_once()
