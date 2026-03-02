"""Tests for claw_forge.agent.runner — wraps claude-agent-sdk query()."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import claude_agent_sdk
import pytest

from claw_forge.agent.runner import collect_result, run_agent
from claw_forge.pool.providers.base import ProviderConfig, ProviderType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_assistant_message(text: str) -> claude_agent_sdk.AssistantMessage:
    block = MagicMock(spec=claude_agent_sdk.TextBlock)
    block.text = text
    msg = MagicMock(spec=claude_agent_sdk.AssistantMessage)
    msg.content = [block]
    return msg


def _make_result_message(result: str) -> claude_agent_sdk.ResultMessage:
    msg = MagicMock(spec=claude_agent_sdk.ResultMessage)
    msg.result = result
    msg.total_cost_usd = 0.001
    return msg


async def _async_gen(*items):
    """Yield items one by one as an async generator."""
    for item in items:
        yield item


# ---------------------------------------------------------------------------
# run_agent tests
# ---------------------------------------------------------------------------


class TestRunAgent:
    @pytest.mark.asyncio
    async def test_yields_messages_from_query(self):
        assistant = _make_assistant_message("hello")
        result_msg = _make_result_message("done")

        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen(assistant, result_msg)

            messages = []
            async for msg in run_agent("test prompt"):
                messages.append(msg)

        assert len(messages) == 2
        assert messages[0] is assistant
        assert messages[1] is result_msg

    @pytest.mark.asyncio
    async def test_passes_model_to_options(self):
        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen()

            async for _ in run_agent("prompt", model="claude-opus-4-5"):
                pass

        _, kwargs = mock_query.call_args
        assert kwargs["options"].model == "claude-opus-4-5"

    @pytest.mark.asyncio
    async def test_passes_max_turns_to_options(self):
        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen()

            async for _ in run_agent("prompt", max_turns=10):
                pass

        _, kwargs = mock_query.call_args
        assert kwargs["options"].max_turns == 10

    @pytest.mark.asyncio
    async def test_passes_cwd_as_string(self):
        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen()

            async for _ in run_agent("prompt", cwd=Path("/some/path")):
                pass

        _, kwargs = mock_query.call_args
        assert kwargs["options"].cwd == "/some/path"

    @pytest.mark.asyncio
    async def test_cwd_none_passes_none(self):
        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen()

            async for _ in run_agent("prompt", cwd=None):
                pass

        _, kwargs = mock_query.call_args
        assert kwargs["options"].cwd is None

    @pytest.mark.asyncio
    async def test_passes_allowed_tools(self):
        tools = ["Read", "Write", "Bash"]
        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen()

            async for _ in run_agent("prompt", allowed_tools=tools):
                pass

        _, kwargs = mock_query.call_args
        assert kwargs["options"].allowed_tools == tools

    @pytest.mark.asyncio
    async def test_default_tools_when_none(self):
        """When allowed_tools=None, the agent_type default tools are used."""
        from claw_forge.agent.tools import get_tools_for_agent
        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen()

            async for _ in run_agent("prompt", allowed_tools=None):
                pass

        _, kwargs = mock_query.call_args
        # Default agent_type is "coding", so we expect the coding tool list
        assert kwargs["options"].allowed_tools == get_tools_for_agent("coding")

    @pytest.mark.asyncio
    async def test_mcp_servers_passed_through(self):
        servers = {"my-server": {"command": "npx", "args": ["-y", "my-mcp-server"]}}
        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen()

            async for _ in run_agent("prompt", mcp_servers=servers):
                pass

        _, kwargs = mock_query.call_args
        assert kwargs["options"].mcp_servers == servers

    @pytest.mark.asyncio
    async def test_empty_mcp_servers_when_none(self):
        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen()

            async for _ in run_agent("prompt", mcp_servers=None):
                pass

        _, kwargs = mock_query.call_args
        assert kwargs["options"].mcp_servers == {}

    @pytest.mark.asyncio
    async def test_system_prompt_passed(self):
        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen()

            async for _ in run_agent("prompt", system_prompt="Be helpful"):
                pass

        _, kwargs = mock_query.call_args
        assert kwargs["options"].system_prompt == "Be helpful"

    @pytest.mark.asyncio
    async def test_permission_mode_passed(self):
        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen()

            async for _ in run_agent("prompt", permission_mode="bypassPermissions"):
                pass

        _, kwargs = mock_query.call_args
        assert kwargs["options"].permission_mode == "bypassPermissions"

    @pytest.mark.asyncio
    async def test_provider_config_api_key_sets_env(self):
        config = ProviderConfig(
            name="test",
            provider_type=ProviderType.ANTHROPIC,
            api_key="sk-test-key",
        )
        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen()

            async for _ in run_agent("prompt", provider_config=config):
                pass

        _, kwargs = mock_query.call_args
        assert kwargs["options"].env.get("ANTHROPIC_API_KEY") == "sk-test-key"

    @pytest.mark.asyncio
    async def test_provider_config_base_url_sets_env(self):
        config = ProviderConfig(
            name="test",
            provider_type=ProviderType.ANTHROPIC_COMPAT,
            base_url="https://proxy.example.com/v1",
        )
        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen()

            async for _ in run_agent("prompt", provider_config=config):
                pass

        _, kwargs = mock_query.call_args
        assert kwargs["options"].env.get("ANTHROPIC_BASE_URL") == "https://proxy.example.com/v1"

    @pytest.mark.asyncio
    async def test_provider_config_oauth_token_sets_env(self):
        config = ProviderConfig(
            name="test",
            provider_type=ProviderType.ANTHROPIC_OAUTH,
            oauth_token="tok_abc123",
        )
        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen()

            async for _ in run_agent("prompt", provider_config=config):
                pass

        _, kwargs = mock_query.call_args
        assert kwargs["options"].env.get("CLAUDE_OAUTH_TOKEN") == "tok_abc123"

    @pytest.mark.asyncio
    async def test_no_provider_config_empty_env(self):
        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen()

            async for _ in run_agent("prompt", provider_config=None):
                pass

        _, kwargs = mock_query.call_args
        assert kwargs["options"].env == {}

    @pytest.mark.asyncio
    async def test_provider_config_no_api_key_no_env_var(self):
        """Provider with no api_key should not set ANTHROPIC_API_KEY in env."""
        config = ProviderConfig(
            name="test",
            provider_type=ProviderType.ANTHROPIC,
            api_key=None,
        )
        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen()

            async for _ in run_agent("prompt", provider_config=config):
                pass

        _, kwargs = mock_query.call_args
        assert "ANTHROPIC_API_KEY" not in kwargs["options"].env

    @pytest.mark.asyncio
    async def test_prompt_passed_to_query(self):
        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen()

            async for _ in run_agent("my special prompt"):
                pass

        _, kwargs = mock_query.call_args
        assert kwargs["prompt"] == "my special prompt"


# ---------------------------------------------------------------------------
# collect_result tests
# ---------------------------------------------------------------------------


class TestCollectResult:
    @pytest.mark.asyncio
    async def test_returns_result_message_text(self):
        result_msg = _make_result_message("task completed successfully")

        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen(result_msg)
            output = await collect_result("prompt")

        assert output == "task completed successfully"

    @pytest.mark.asyncio
    async def test_ignores_non_result_messages(self):
        assistant = _make_assistant_message("I am working on it...")
        result_msg = _make_result_message("final answer")

        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen(assistant, result_msg)
            output = await collect_result("prompt")

        assert output == "final answer"

    @pytest.mark.asyncio
    async def test_returns_empty_string_when_no_result_message(self):
        assistant = _make_assistant_message("no result message here")

        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen(assistant)
            output = await collect_result("prompt")

        assert output == ""

    @pytest.mark.asyncio
    async def test_returns_empty_string_on_no_messages(self):
        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen()
            output = await collect_result("prompt")

        assert output == ""

    @pytest.mark.asyncio
    async def test_result_none_becomes_empty_string(self):
        result_msg = _make_result_message(None)  # type: ignore[arg-type]
        result_msg.result = None

        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen(result_msg)
            output = await collect_result("prompt")

        assert output == ""

    @pytest.mark.asyncio
    async def test_passes_kwargs_to_run_agent(self):
        """collect_result forwards kwargs (model, cwd, etc.) to run_agent."""
        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen()
            await collect_result("prompt", model="claude-haiku-4-5", max_turns=5)

        _, kwargs = mock_query.call_args
        assert kwargs["options"].model == "claude-haiku-4-5"
        assert kwargs["options"].max_turns == 5

    @pytest.mark.asyncio
    async def test_uses_last_result_message_when_multiple(self):
        """If multiple ResultMessages appear, the last one wins."""
        first = _make_result_message("first result")
        second = _make_result_message("second result")

        with patch("claw_forge.agent.runner.query") as mock_query:
            mock_query.return_value = _async_gen(first, second)
            output = await collect_result("prompt")

        assert output == "second result"
