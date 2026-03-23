"""Tests for the Ollama local provider."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from claw_forge.pool.providers.base import ProviderConfig, ProviderError, ProviderType
from claw_forge.pool.providers.ollama import _DEFAULT_MODEL, OllamaProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**kwargs: Any) -> ProviderConfig:
    defaults = dict(name="test-ollama", provider_type=ProviderType.OLLAMA)
    defaults.update(kwargs)
    return ProviderConfig(**defaults)


def _chat_response(
    content: str = "Hello from Ollama",
    model: str = "llama3.2",
) -> dict[str, Any]:
    """Minimal OpenAI-compat chat completion response."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }


def _mock_response(
    status_code: int = 200,
    body: dict[str, Any] | None = None,
) -> Mock:
    resp = Mock(spec=httpx.Response)
    resp.status_code = status_code
    if body is not None:
        resp.json.return_value = body
        resp.text = json.dumps(body)
    resp.raise_for_status = Mock()
    return resp


# ---------------------------------------------------------------------------
# execute() — successful completion
# ---------------------------------------------------------------------------


class TestOllamaProviderExecute:
    @pytest.mark.asyncio
    async def test_successful_completion(self) -> None:
        cfg = _make_config()
        provider = OllamaProvider(cfg)

        response_body = _chat_response("Hi there!")
        mock_resp = _mock_response(200, response_body)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("claw_forge.pool.providers.ollama.httpx.AsyncClient", return_value=mock_client):
            result = await provider.execute(
                model="llama3.2",
                messages=[{"role": "user", "content": "hello"}],
            )

        assert result.content == "Hi there!"
        assert result.model == "llama3.2"
        assert result.provider_name == "test-ollama"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert result.stop_reason == "stop"

    @pytest.mark.asyncio
    async def test_uses_config_model_as_default(self) -> None:
        """When the caller passes an empty-string model, fall back to config.model."""
        cfg = _make_config(model="mistral")
        provider = OllamaProvider(cfg)

        response_body = _chat_response(model="mistral")
        mock_resp = _mock_response(200, response_body)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        captured_body: dict[str, Any] = {}

        async def capture_post(url: str, **kwargs: Any) -> Mock:
            captured_body.update(kwargs.get("json", {}))
            return mock_resp

        mock_client.post = capture_post

        with patch("claw_forge.pool.providers.ollama.httpx.AsyncClient", return_value=mock_client):
            await provider.execute(
                model="mistral",
                messages=[{"role": "user", "content": "hi"}],
            )

        assert captured_body.get("model") == "mistral"

    @pytest.mark.asyncio
    async def test_uses_default_model_when_none_configured(self) -> None:
        """Falls back to _DEFAULT_MODEL when config has no model."""
        cfg = _make_config()  # no model
        provider = OllamaProvider(cfg)

        response_body = _chat_response(model=_DEFAULT_MODEL)
        mock_resp = _mock_response(200, response_body)

        captured_body: dict[str, Any] = {}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        async def capture_post(url: str, **kwargs: Any) -> Mock:
            captured_body.update(kwargs.get("json", {}))
            return mock_resp

        mock_client.post = capture_post

        with patch("claw_forge.pool.providers.ollama.httpx.AsyncClient", return_value=mock_client):
            await provider.execute(
                model=_DEFAULT_MODEL,
                messages=[{"role": "user", "content": "hi"}],
            )

        assert captured_body.get("model") == _DEFAULT_MODEL

    @pytest.mark.asyncio
    async def test_system_prompt_prepended(self) -> None:
        cfg = _make_config()
        provider = OllamaProvider(cfg)

        mock_resp = _mock_response(200, _chat_response())
        captured_body: dict[str, Any] = {}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        async def capture_post(url: str, **kwargs: Any) -> Mock:
            captured_body.update(kwargs.get("json", {}))
            return mock_resp

        mock_client.post = capture_post

        with patch("claw_forge.pool.providers.ollama.httpx.AsyncClient", return_value=mock_client):
            await provider.execute(
                model="llama3.2",
                messages=[{"role": "user", "content": "hi"}],
                system="You are helpful.",
            )

        msgs = captured_body.get("messages", [])
        assert msgs[0] == {"role": "system", "content": "You are helpful."}
        assert msgs[1] == {"role": "user", "content": "hi"}

    @pytest.mark.asyncio
    async def test_bearer_auth_when_api_key_set(self) -> None:
        cfg = _make_config(api_key="test-key-123")
        provider = OllamaProvider(cfg)

        mock_resp = _mock_response(200, _chat_response())
        captured_headers: dict[str, str] = {}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        async def capture_post(url: str, **kwargs: Any) -> Mock:
            captured_headers.update(kwargs.get("headers", {}))
            return mock_resp

        mock_client.post = capture_post

        with patch("claw_forge.pool.providers.ollama.httpx.AsyncClient", return_value=mock_client):
            await provider.execute(
                model="llama3.2",
                messages=[{"role": "user", "content": "hi"}],
            )

        assert captured_headers.get("Authorization") == "Bearer test-key-123"

    @pytest.mark.asyncio
    async def test_no_auth_header_without_api_key(self) -> None:
        cfg = _make_config()  # no api_key
        provider = OllamaProvider(cfg)

        mock_resp = _mock_response(200, _chat_response())
        captured_headers: dict[str, str] = {}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        async def capture_post(url: str, **kwargs: Any) -> Mock:
            captured_headers.update(kwargs.get("headers", {}))
            return mock_resp

        mock_client.post = capture_post

        with patch("claw_forge.pool.providers.ollama.httpx.AsyncClient", return_value=mock_client):
            await provider.execute(
                model="llama3.2",
                messages=[{"role": "user", "content": "hi"}],
            )

        assert "Authorization" not in captured_headers


# ---------------------------------------------------------------------------
# execute() — error handling
# ---------------------------------------------------------------------------


class TestOllamaProviderErrors:
    @pytest.mark.asyncio
    async def test_404_model_not_found(self) -> None:
        cfg = _make_config()
        provider = OllamaProvider(cfg)

        mock_resp = _mock_response(404)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("claw_forge.pool.providers.ollama.httpx.AsyncClient", return_value=mock_client):  # noqa: SIM117
            with pytest.raises(ProviderError) as exc_info:  # noqa: SIM117
                await provider.execute(
                    model="unknown-model",
                    messages=[{"role": "user", "content": "hi"}],
                )

        err = exc_info.value
        assert "not found in Ollama" in str(err)
        assert "ollama pull" in str(err)
        assert err.retryable is False

    @pytest.mark.asyncio
    async def test_500_server_error(self) -> None:
        cfg = _make_config()
        provider = OllamaProvider(cfg)

        mock_resp = _mock_response(500)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("claw_forge.pool.providers.ollama.httpx.AsyncClient", return_value=mock_client):  # noqa: SIM117
            with pytest.raises(ProviderError) as exc_info:  # noqa: SIM117
                await provider.execute(
                    model="llama3.2",
                    messages=[{"role": "user", "content": "hi"}],
                )

        assert exc_info.value.retryable is True
        assert "500" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_connect_error(self) -> None:
        cfg = _make_config()
        provider = OllamaProvider(cfg)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with patch("claw_forge.pool.providers.ollama.httpx.AsyncClient", return_value=mock_client):  # noqa: SIM117
            with pytest.raises(ProviderError) as exc_info:  # noqa: SIM117
                await provider.execute(
                    model="llama3.2",
                    messages=[{"role": "user", "content": "hi"}],
                )

        err = exc_info.value
        assert "Cannot connect to Ollama" in str(err)
        assert "ollama serve" in str(err)
        assert err.retryable is True

    @pytest.mark.asyncio
    async def test_timeout_error(self) -> None:
        cfg = _make_config()
        provider = OllamaProvider(cfg)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=httpx.TimeoutException("Request timed out")
        )

        with patch("claw_forge.pool.providers.ollama.httpx.AsyncClient", return_value=mock_client):  # noqa: SIM117
            with pytest.raises(ProviderError) as exc_info:  # noqa: SIM117
                await provider.execute(
                    model="llama3.2",
                    messages=[{"role": "user", "content": "hi"}],
                )

        err = exc_info.value
        assert "timed out" in str(err)
        assert err.retryable is True


# ---------------------------------------------------------------------------
# list_models()
# ---------------------------------------------------------------------------


class TestOllamaListModels:
    @pytest.mark.asyncio
    async def test_list_models_returns_names(self) -> None:
        cfg = _make_config()
        provider = OllamaProvider(cfg)

        tags_response = Mock(spec=httpx.Response)
        tags_response.status_code = 200
        tags_response.json.return_value = {
            "models": [
                {"name": "llama3.2:latest"},
                {"name": "mistral:latest"},
                {"name": "codellama:7b"},
            ]
        }
        tags_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=tags_response)

        with patch("claw_forge.pool.providers.ollama.httpx.AsyncClient", return_value=mock_client):
            models = await provider.list_models()

        assert models == ["llama3.2:latest", "mistral:latest", "codellama:7b"]

    @pytest.mark.asyncio
    async def test_list_models_empty(self) -> None:
        cfg = _make_config()
        provider = OllamaProvider(cfg)

        tags_response = Mock(spec=httpx.Response)
        tags_response.status_code = 200
        tags_response.json.return_value = {"models": []}
        tags_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=tags_response)

        with patch("claw_forge.pool.providers.ollama.httpx.AsyncClient", return_value=mock_client):
            models = await provider.list_models()

        assert models == []


# ---------------------------------------------------------------------------
# health_check()
# ---------------------------------------------------------------------------


class TestOllamaHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_true_when_ok(self) -> None:
        cfg = _make_config()
        provider = OllamaProvider(cfg)

        ok_resp = Mock(spec=httpx.Response)
        ok_resp.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=ok_resp)

        with patch("claw_forge.pool.providers.ollama.httpx.AsyncClient", return_value=mock_client):
            result = await provider.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_connect_error(self) -> None:
        cfg = _make_config()
        provider = OllamaProvider(cfg)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("claw_forge.pool.providers.ollama.httpx.AsyncClient", return_value=mock_client):
            result = await provider.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_any_exception(self) -> None:
        cfg = _make_config()
        provider = OllamaProvider(cfg)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("unexpected"))

        with patch("claw_forge.pool.providers.ollama.httpx.AsyncClient", return_value=mock_client):
            result = await provider.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_non_200(self) -> None:
        cfg = _make_config()
        provider = OllamaProvider(cfg)

        bad_resp = Mock(spec=httpx.Response)
        bad_resp.status_code = 503

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=bad_resp)

        with patch("claw_forge.pool.providers.ollama.httpx.AsyncClient", return_value=mock_client):
            result = await provider.health_check()

        assert result is False


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


class TestOllamaRegistry:
    def test_ollama_type_in_registry(self) -> None:
        from claw_forge.pool.providers.registry import _PROVIDER_CLASSES

        assert ProviderType.OLLAMA in _PROVIDER_CLASSES

    def test_create_provider_returns_ollama_instance(self) -> None:
        from claw_forge.pool.providers.registry import create_provider

        cfg = _make_config(base_url="http://localhost:11434")
        provider = create_provider(cfg)
        assert isinstance(provider, OllamaProvider)

    def test_ollama_base_url_respected(self) -> None:
        cfg = _make_config(base_url="http://my-ollama:8888")
        provider = OllamaProvider(cfg)
        assert provider.base_url == "http://my-ollama:8888"

    def test_ollama_base_url_trailing_slash_stripped(self) -> None:
        cfg = _make_config(base_url="http://localhost:11434/")
        provider = OllamaProvider(cfg)
        assert provider.base_url == "http://localhost:11434"

    def test_ollama_default_base_url_used_when_not_set(self) -> None:
        cfg = _make_config()
        provider = OllamaProvider(cfg)
        assert provider.base_url == OllamaProvider.DEFAULT_BASE_URL
