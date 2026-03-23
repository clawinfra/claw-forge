"""Tests for cloud provider implementations: Azure, Bedrock, OpenAI-compat, Vertex."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from claw_forge.pool.providers.base import (
    AuthenticationError,
    ProviderConfig,
    ProviderError,
    ProviderType,
    RateLimitError,
)

# ── helpers ────────────────────────────────────────────────────────────────────


def _cfg(**kwargs: Any) -> ProviderConfig:
    defaults = dict(
        name="test",
        provider_type=ProviderType.OPENAI_COMPAT,
        model_map={},
        priority=1,
        enabled=True,
        cost_per_mtok_input=0.0,
        cost_per_mtok_output=0.0,
    )
    defaults.update(kwargs)
    return ProviderConfig(**defaults)


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


# ── AzureProvider ──────────────────────────────────────────────────────────────


class TestAzureProvider:
    def _provider(self, **kw: Any) -> Any:
        from claw_forge.pool.providers.azure import AzureProvider

        cfg = _cfg(
            provider_type=ProviderType.AZURE,
            endpoint="https://my-az.openai.azure.com",
            api_key="azure-key",
            **kw,
        )
        return AzureProvider(cfg)

    def test_constructor_succeeds(self) -> None:
        p = self._provider()
        assert p.name == "test"

    def test_constructor_missing_endpoint_raises(self) -> None:
        from claw_forge.pool.providers.azure import AzureProvider

        cfg = _cfg(provider_type=ProviderType.AZURE, api_key="k", endpoint=None)
        with pytest.raises(ValueError, match="endpoint"):
            AzureProvider(cfg)

    def test_constructor_missing_api_key_raises(self) -> None:
        from claw_forge.pool.providers.azure import AzureProvider

        cfg = _cfg(
            provider_type=ProviderType.AZURE,
            endpoint="https://foo.openai.azure.com",
            api_key=None,
        )
        with pytest.raises(ValueError, match="api_key"):
            AzureProvider(cfg)

    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:
        from claw_forge.pool.providers.azure import AzureProvider

        cfg = _cfg(
            provider_type=ProviderType.AZURE,
            endpoint="https://my-az.openai.azure.com",
            api_key="key",
        )
        provider = AzureProvider(cfg)

        response_data = {
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "model": "gpt-4",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = response_data

        provider._client.post = AsyncMock(return_value=mock_resp)

        result = await provider.execute(
            "gpt-4",
            [{"role": "user", "content": "hi"}],
        )
        assert result.content == "hello"
        assert result.provider_name == "test"

    @pytest.mark.asyncio
    async def test_execute_rate_limit(self) -> None:
        from claw_forge.pool.providers.azure import AzureProvider

        cfg = _cfg(
            provider_type=ProviderType.AZURE,
            endpoint="https://my-az.openai.azure.com",
            api_key="key",
        )
        provider = AzureProvider(cfg)
        mock_resp = Mock()
        mock_resp.status_code = 429
        mock_resp.headers = {"retry-after": "2.0"}
        provider._client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(RateLimitError):
            await provider.execute("gpt-4", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_execute_auth_error(self) -> None:
        from claw_forge.pool.providers.azure import AzureProvider

        cfg = _cfg(
            provider_type=ProviderType.AZURE,
            endpoint="https://my-az.openai.azure.com",
            api_key="key",
        )
        provider = AzureProvider(cfg)
        mock_resp = Mock()
        mock_resp.status_code = 401
        provider._client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(AuthenticationError):
            await provider.execute("gpt-4", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_execute_server_error(self) -> None:
        from claw_forge.pool.providers.azure import AzureProvider

        cfg = _cfg(
            provider_type=ProviderType.AZURE,
            endpoint="https://my-az.openai.azure.com",
            api_key="key",
        )
        provider = AzureProvider(cfg)
        mock_resp = Mock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal server error"
        provider._client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(ProviderError):
            await provider.execute("gpt-4", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_execute_timeout(self) -> None:
        from claw_forge.pool.providers.azure import AzureProvider

        cfg = _cfg(
            provider_type=ProviderType.AZURE,
            endpoint="https://my-az.openai.azure.com",
            api_key="key",
        )
        provider = AzureProvider(cfg)
        provider._client.post = AsyncMock(
            side_effect=httpx.TimeoutException("timed out")
        )

        with pytest.raises(ProviderError, match="Timeout"):
            await provider.execute("gpt-4", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_health_check_failure(self) -> None:
        from claw_forge.pool.providers.azure import AzureProvider

        cfg = _cfg(
            provider_type=ProviderType.AZURE,
            endpoint="https://my-az.openai.azure.com",
            api_key="key",
        )
        provider = AzureProvider(cfg)
        provider._client.post = AsyncMock(side_effect=RuntimeError("connection refused"))
        result = await provider.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_execute_with_system_and_tools(self) -> None:
        from claw_forge.pool.providers.azure import AzureProvider

        cfg = _cfg(
            provider_type=ProviderType.AZURE,
            endpoint="https://my-az.openai.azure.com",
            api_key="key",
        )
        provider = AzureProvider(cfg)

        response_data = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "model": "gpt-4",
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        }
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = response_data
        provider._client.post = AsyncMock(return_value=mock_resp)

        result = await provider.execute(
            "gpt-4",
            [{"role": "user", "content": "hi"}],
            system="you are helpful",
            tools=[{"name": "search", "description": "search", "parameters": {}}],
        )
        assert result.content == "ok"


# ── BedrockProvider ────────────────────────────────────────────────────────────


class TestBedrockProvider:
    def _provider(self, **kw: Any) -> Any:
        from claw_forge.pool.providers.bedrock import BedrockProvider

        cfg = _cfg(provider_type=ProviderType.BEDROCK, region="us-east-1", **kw)
        return BedrockProvider(cfg)

    def test_constructor_succeeds(self) -> None:
        p = self._provider()
        assert p.name == "test"

    def test_get_client_missing_sdk(self) -> None:
        provider = self._provider()
        with (
            patch.dict("sys.modules", {"anthropic": None}),
            pytest.raises(ProviderError, match="bedrock"),
        ):
            provider._get_client()

    def test_get_client_import_error(self) -> None:
        provider = self._provider()
        with (
            patch("builtins.__import__", side_effect=ImportError("no module")),
            pytest.raises((ProviderError, ImportError)),
        ):
            provider._get_client()

    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:
        from claw_forge.pool.providers.bedrock import BedrockProvider

        cfg = _cfg(provider_type=ProviderType.BEDROCK)
        provider = BedrockProvider(cfg)

        mock_block = Mock()
        mock_block.text = "bedrock response"
        mock_response = Mock()
        mock_response.content = [mock_block]
        mock_response.model = "claude-3"
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5
        mock_response.stop_reason = "end_turn"

        mock_client = Mock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.execute(
            "claude-3", [{"role": "user", "content": "hi"}]
        )
        assert result.content == "bedrock response"
        assert result.provider_name == "test"

    @pytest.mark.asyncio
    async def test_execute_rate_limit_error(self) -> None:
        from claw_forge.pool.providers.bedrock import BedrockProvider

        cfg = _cfg(provider_type=ProviderType.BEDROCK)
        provider = BedrockProvider(cfg)

        mock_client = Mock()
        mock_client.messages.create = AsyncMock(
            side_effect=Exception("ThrottlingException: rate limit exceeded")
        )
        provider._client = mock_client

        with pytest.raises(RateLimitError):
            await provider.execute("claude-3", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_execute_generic_error(self) -> None:
        from claw_forge.pool.providers.bedrock import BedrockProvider

        cfg = _cfg(provider_type=ProviderType.BEDROCK)
        provider = BedrockProvider(cfg)

        mock_client = Mock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("connection error"))
        provider._client = mock_client

        with pytest.raises(ProviderError):
            await provider.execute("claude-3", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_execute_with_system(self) -> None:
        from claw_forge.pool.providers.bedrock import BedrockProvider

        cfg = _cfg(provider_type=ProviderType.BEDROCK)
        provider = BedrockProvider(cfg)

        mock_block = Mock()
        mock_block.text = "ok"
        mock_response = Mock()
        mock_response.content = [mock_block]
        mock_response.model = "claude-3"
        mock_response.usage.input_tokens = 5
        mock_response.usage.output_tokens = 2
        mock_response.stop_reason = "end_turn"

        mock_client = Mock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.execute(
            "claude-3",
            [{"role": "user", "content": "hi"}],
            system="you are helpful",
            tools=[{"name": "fn", "description": "d", "input_schema": {}}],
        )
        assert result.content == "ok"
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["system"] == "you are helpful"

    @pytest.mark.asyncio
    async def test_health_check_failure(self) -> None:
        from claw_forge.pool.providers.bedrock import BedrockProvider

        cfg = _cfg(provider_type=ProviderType.BEDROCK)
        provider = BedrockProvider(cfg)
        provider._client = Mock()
        provider._client.messages.create = AsyncMock(side_effect=RuntimeError("error"))
        result = await provider.health_check()
        assert result is False


# ── OpenAICompatProvider ───────────────────────────────────────────────────────


class TestOpenAICompatProvider:
    def _provider(self, **kw: Any) -> Any:
        from claw_forge.pool.providers.openai_compat import OpenAICompatProvider

        cfg = _cfg(
            provider_type=ProviderType.OPENAI_COMPAT,
            base_url="http://localhost:11434",
            **kw,
        )
        return OpenAICompatProvider(cfg)

    def test_constructor_succeeds(self) -> None:
        p = self._provider()
        assert p.name == "test"

    def test_constructor_missing_base_url_raises(self) -> None:
        from claw_forge.pool.providers.openai_compat import OpenAICompatProvider

        cfg = _cfg(provider_type=ProviderType.OPENAI_COMPAT, base_url=None)
        with pytest.raises(ValueError, match="base_url"):
            OpenAICompatProvider(cfg)

    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:
        from claw_forge.pool.providers.openai_compat import OpenAICompatProvider

        cfg = _cfg(
            provider_type=ProviderType.OPENAI_COMPAT,
            base_url="http://localhost:11434",
        )
        provider = OpenAICompatProvider(cfg)

        response_data = {
            "choices": [{"message": {"content": "compat response"}, "finish_reason": "stop"}],
            "model": "llama3",
            "usage": {"prompt_tokens": 8, "completion_tokens": 4},
        }
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = response_data
        provider._client.post = AsyncMock(return_value=mock_resp)

        result = await provider.execute("llama3", [{"role": "user", "content": "hi"}])
        assert result.content == "compat response"

    @pytest.mark.asyncio
    async def test_execute_rate_limit(self) -> None:
        from claw_forge.pool.providers.openai_compat import OpenAICompatProvider

        cfg = _cfg(
            provider_type=ProviderType.OPENAI_COMPAT,
            base_url="http://localhost:11434",
        )
        provider = OpenAICompatProvider(cfg)
        mock_resp = Mock()
        mock_resp.status_code = 429
        mock_resp.headers = {}
        provider._client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(RateLimitError):
            await provider.execute("llama3", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_execute_auth_error(self) -> None:
        from claw_forge.pool.providers.openai_compat import OpenAICompatProvider

        cfg = _cfg(
            provider_type=ProviderType.OPENAI_COMPAT,
            base_url="http://localhost:11434",
        )
        provider = OpenAICompatProvider(cfg)
        mock_resp = Mock()
        mock_resp.status_code = 403
        provider._client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(AuthenticationError):
            await provider.execute("llama3", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_execute_timeout(self) -> None:
        from claw_forge.pool.providers.openai_compat import OpenAICompatProvider

        cfg = _cfg(
            provider_type=ProviderType.OPENAI_COMPAT,
            base_url="http://localhost:11434",
        )
        provider = OpenAICompatProvider(cfg)
        provider._client.post = AsyncMock(
            side_effect=httpx.TimeoutException("timed out")
        )

        with pytest.raises(ProviderError, match="Timeout"):
            await provider.execute("llama3", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_execute_server_error(self) -> None:
        from claw_forge.pool.providers.openai_compat import OpenAICompatProvider

        cfg = _cfg(
            provider_type=ProviderType.OPENAI_COMPAT,
            base_url="http://localhost:11434",
        )
        provider = OpenAICompatProvider(cfg)
        mock_resp = Mock()
        mock_resp.status_code = 503
        mock_resp.text = "Service Unavailable"
        provider._client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(ProviderError):
            await provider.execute("llama3", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_execute_with_api_key(self) -> None:
        from claw_forge.pool.providers.openai_compat import OpenAICompatProvider

        cfg = _cfg(
            provider_type=ProviderType.OPENAI_COMPAT,
            base_url="http://localhost:11434",
            api_key="bearer-key",
        )
        provider = OpenAICompatProvider(cfg)

        response_data = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "model": "llama3",
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        }
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = response_data
        provider._client.post = AsyncMock(return_value=mock_resp)

        result = await provider.execute("llama3", [{"role": "user", "content": "hi"}])
        assert result.content == "ok"

    @pytest.mark.asyncio
    async def test_execute_with_system_and_tools(self) -> None:
        from claw_forge.pool.providers.openai_compat import OpenAICompatProvider

        cfg = _cfg(
            provider_type=ProviderType.OPENAI_COMPAT,
            base_url="http://localhost:11434",
        )
        provider = OpenAICompatProvider(cfg)

        response_data = {
            "choices": [{"message": {"content": "with system"}, "finish_reason": "stop"}],
            "model": "llama3",
            "usage": {},
        }
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = response_data
        provider._client.post = AsyncMock(return_value=mock_resp)

        result = await provider.execute(
            "llama3",
            [{"role": "user", "content": "hi"}],
            system="be helpful",
            tools=[{"name": "search", "description": "d", "parameters": {}}],
        )
        assert result.content == "with system"

    @pytest.mark.asyncio
    async def test_health_check_failure(self) -> None:
        from claw_forge.pool.providers.openai_compat import OpenAICompatProvider

        cfg = _cfg(
            provider_type=ProviderType.OPENAI_COMPAT,
            base_url="http://localhost:11434",
        )
        provider = OpenAICompatProvider(cfg)
        provider._client.post = AsyncMock(side_effect=RuntimeError("error"))
        result = await provider.health_check()
        assert result is False


# ── VertexProvider ─────────────────────────────────────────────────────────────


class TestVertexProvider:
    def _provider(self, **kw: Any) -> Any:
        from claw_forge.pool.providers.vertex import VertexProvider

        cfg = _cfg(
            provider_type=ProviderType.VERTEX,
            project_id="my-gcp-project",
            region="us-east5",
            **kw,
        )
        return VertexProvider(cfg)

    def test_constructor_succeeds(self) -> None:
        p = self._provider()
        assert p.name == "test"

    def test_constructor_missing_project_id_raises(self) -> None:
        from claw_forge.pool.providers.vertex import VertexProvider

        cfg = _cfg(provider_type=ProviderType.VERTEX, project_id=None)
        with pytest.raises(ValueError, match="project_id"):
            VertexProvider(cfg)

    def test_get_client_missing_sdk(self) -> None:
        provider = self._provider()
        with (
            patch.dict("sys.modules", {"anthropic": None}),
            pytest.raises(ProviderError, match="vertex"),
        ):
            provider._get_client()

    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:
        from claw_forge.pool.providers.vertex import VertexProvider

        cfg = _cfg(provider_type=ProviderType.VERTEX, project_id="proj")
        provider = VertexProvider(cfg)

        mock_block = Mock()
        mock_block.text = "vertex response"
        mock_response = Mock()
        mock_response.content = [mock_block]
        mock_response.model = "claude-3"
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5
        mock_response.stop_reason = "end_turn"

        mock_client = Mock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.execute("claude-3", [{"role": "user", "content": "hi"}])
        assert result.content == "vertex response"

    @pytest.mark.asyncio
    async def test_execute_rate_limit(self) -> None:
        from claw_forge.pool.providers.vertex import VertexProvider

        cfg = _cfg(provider_type=ProviderType.VERTEX, project_id="proj")
        provider = VertexProvider(cfg)

        mock_client = Mock()
        mock_client.messages.create = AsyncMock(
            side_effect=Exception("quota exceeded: 429")
        )
        provider._client = mock_client

        with pytest.raises(RateLimitError):
            await provider.execute("claude-3", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_execute_generic_error(self) -> None:
        from claw_forge.pool.providers.vertex import VertexProvider

        cfg = _cfg(provider_type=ProviderType.VERTEX, project_id="proj")
        provider = VertexProvider(cfg)

        mock_client = Mock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("generic error"))
        provider._client = mock_client

        with pytest.raises(ProviderError):
            await provider.execute("claude-3", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_execute_with_system_and_tools(self) -> None:
        from claw_forge.pool.providers.vertex import VertexProvider

        cfg = _cfg(provider_type=ProviderType.VERTEX, project_id="proj")
        provider = VertexProvider(cfg)

        mock_block = Mock()
        mock_block.text = "ok"
        mock_response = Mock()
        mock_response.content = [mock_block]
        mock_response.model = "claude-3"
        mock_response.usage.input_tokens = 5
        mock_response.usage.output_tokens = 2
        mock_response.stop_reason = "end_turn"

        mock_client = Mock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.execute(
            "claude-3",
            [{"role": "user", "content": "hi"}],
            system="you are helpful",
            tools=[{"name": "fn", "description": "d", "input_schema": {}}],
        )
        assert result.content == "ok"
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["system"] == "you are helpful"

    @pytest.mark.asyncio
    async def test_health_check_failure(self) -> None:
        from claw_forge.pool.providers.vertex import VertexProvider

        cfg = _cfg(provider_type=ProviderType.VERTEX, project_id="proj")
        provider = VertexProvider(cfg)
        provider._client = Mock()
        provider._client.messages.create = AsyncMock(side_effect=RuntimeError("error"))
        result = await provider.health_check()
        assert result is False

    def test_default_region(self) -> None:
        from claw_forge.pool.providers.vertex import VertexProvider

        cfg = _cfg(provider_type=ProviderType.VERTEX, project_id="proj", region=None)
        provider = VertexProvider(cfg)
        assert provider._region == "us-east5"
