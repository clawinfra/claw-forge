"""Tests for AgentSession — bidirectional ClaudeSDKClient wrapper."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import claude_agent_sdk
from claude_agent_sdk import ClaudeAgentOptions

from claw_forge.agent.session import AgentSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_options(**kwargs) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(model="claude-sonnet-4-5", **kwargs)


def _make_user_message(uuid_val: str) -> claude_agent_sdk.UserMessage:
    msg = MagicMock(spec=claude_agent_sdk.UserMessage)
    msg.uuid = uuid_val
    return msg


def _make_assistant_message(text: str = "hello") -> claude_agent_sdk.AssistantMessage:
    block = MagicMock(spec=claude_agent_sdk.TextBlock)
    block.text = text
    msg = MagicMock(spec=claude_agent_sdk.AssistantMessage)
    msg.content = [block]
    return msg


def _make_result_message(result: str = "done") -> claude_agent_sdk.ResultMessage:
    msg = MagicMock(spec=claude_agent_sdk.ResultMessage)
    msg.result = result
    return msg


class AsyncIterableList:
    """A reusable async iterable that yields items from a list."""
    def __init__(self, items):
        self._items = items

    def __aiter__(self):
        return self._async_iter()

    async def _async_iter(self):
        for item in self._items:
            yield item


# ---------------------------------------------------------------------------
# AgentSession lifecycle
# ---------------------------------------------------------------------------


class TestAgentSessionLifecycle:
    @pytest.mark.asyncio
    async def test_aenter_connects(self):
        """__aenter__ should create a ClaudeSDKClient and call connect()."""
        with patch("claw_forge.agent.session.ClaudeSDKClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client

            session = AgentSession(_make_options())
            entered = await session.__aenter__()

            assert entered is session
            mock_cls.assert_called_once()
            mock_client.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_aexit_disconnects(self):
        """__aexit__ should call disconnect() on the client."""
        with patch("claw_forge.agent.session.ClaudeSDKClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client

            session = AgentSession(_make_options())
            await session.__aenter__()
            await session.__aexit__(None, None, None)

            mock_client.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_aexit_sets_client_none(self):
        """After __aexit__, _client should be None."""
        with patch("claw_forge.agent.session.ClaudeSDKClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client

            session = AgentSession(_make_options())
            await session.__aenter__()
            await session.__aexit__(None, None, None)

            assert session._client is None

    @pytest.mark.asyncio
    async def test_aexit_noop_if_not_connected(self):
        """__aexit__ should be safe to call even if never connected."""
        session = AgentSession(_make_options())
        # Should not raise
        await session.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# run() 
# ---------------------------------------------------------------------------


class TestAgentSessionRun:
    @pytest.mark.asyncio
    async def test_run_yields_messages(self):
        """run() should yield all messages from receive_response()."""
        assistant = _make_assistant_message()
        result = _make_result_message()

        with patch("claw_forge.agent.session.ClaudeSDKClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            # receive_response is a non-awaited method returning an async iterator
            mock_client.receive_response = MagicMock(
                return_value=AsyncIterableList([assistant, result])
            )

            session = AgentSession(_make_options())
            await session.__aenter__()
            messages = [msg async for msg in session.run("test prompt")]
            await session.__aexit__(None, None, None)

        assert len(messages) == 2
        assert messages[0] is assistant
        assert messages[1] is result
        mock_client.query.assert_awaited_once_with("test prompt")

    @pytest.mark.asyncio
    async def test_run_records_checkpoints(self):
        """run() should track UserMessage UUIDs as checkpoints."""
        user1 = _make_user_message("uuid-1")
        user2 = _make_user_message("uuid-2")
        assistant = _make_assistant_message()

        with patch("claw_forge.agent.session.ClaudeSDKClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.receive_response = MagicMock(
                return_value=AsyncIterableList([user1, assistant, user2])
            )

            session = AgentSession(_make_options())
            await session.__aenter__()
            _ = [msg async for msg in session.run("prompt")]

        assert session._checkpoints == ["uuid-1", "uuid-2"]

    @pytest.mark.asyncio
    async def test_run_skips_messages_without_uuid(self):
        """UserMessages without a uuid should not create checkpoints."""
        user_no_uuid = MagicMock(spec=claude_agent_sdk.UserMessage)
        user_no_uuid.uuid = None

        with patch("claw_forge.agent.session.ClaudeSDKClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.receive_response = MagicMock(
                return_value=AsyncIterableList([user_no_uuid])
            )

            session = AgentSession(_make_options())
            await session.__aenter__()
            _ = [msg async for msg in session.run("prompt")]

        assert session._checkpoints == []


# ---------------------------------------------------------------------------
# follow_up()
# ---------------------------------------------------------------------------


class TestAgentSessionFollowUp:
    @pytest.mark.asyncio
    async def test_follow_up_sends_query(self):
        """follow_up() should send a new query on the same client."""
        result = _make_result_message("follow-up done")

        with patch("claw_forge.agent.session.ClaudeSDKClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.receive_response = MagicMock(
                return_value=AsyncIterableList([result])
            )

            session = AgentSession(_make_options())
            await session.__aenter__()
            messages = [msg async for msg in session.follow_up("add tests")]

        assert len(messages) == 1
        assert messages[0] is result
        mock_client.query.assert_awaited_with("add tests")


# ---------------------------------------------------------------------------
# rewind()
# ---------------------------------------------------------------------------


class TestAgentSessionRewind:
    @pytest.mark.asyncio
    async def test_rewind_calls_rewind_files_with_correct_checkpoint(self):
        """rewind() should call rewind_files with the Nth-from-last checkpoint."""
        with patch("claw_forge.agent.session.ClaudeSDKClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client

            session = AgentSession(_make_options())
            await session.__aenter__()
            session._checkpoints = ["uuid-a", "uuid-b", "uuid-c"]

            await session.rewind(steps_back=1)
            mock_client.rewind_files.assert_awaited_with("uuid-c")

    @pytest.mark.asyncio
    async def test_rewind_steps_back_2(self):
        with patch("claw_forge.agent.session.ClaudeSDKClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client

            session = AgentSession(_make_options())
            await session.__aenter__()
            session._checkpoints = ["uuid-a", "uuid-b", "uuid-c"]

            await session.rewind(steps_back=2)
            mock_client.rewind_files.assert_awaited_with("uuid-b")

    @pytest.mark.asyncio
    async def test_rewind_noop_if_insufficient_checkpoints(self):
        """rewind() should silently no-op if not enough checkpoints exist."""
        with patch("claw_forge.agent.session.ClaudeSDKClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client

            session = AgentSession(_make_options())
            await session.__aenter__()
            session._checkpoints = []

            await session.rewind(steps_back=1)
            mock_client.rewind_files.assert_not_awaited()


# ---------------------------------------------------------------------------
# mcp_health()
# ---------------------------------------------------------------------------


class TestAgentSessionMcpHealth:
    @pytest.mark.asyncio
    async def test_mcp_health_proxies_get_mcp_status(self):
        """mcp_health() should return whatever get_mcp_status() returns."""
        expected = {"features": {"status": "ok"}}

        with patch("claw_forge.agent.session.ClaudeSDKClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.get_mcp_status.return_value = expected

            session = AgentSession(_make_options())
            await session.__aenter__()
            result = await session.mcp_health()

        assert result == expected
        mock_client.get_mcp_status.assert_awaited_once()


# ---------------------------------------------------------------------------
# Control methods
# ---------------------------------------------------------------------------


class TestAgentSessionControl:
    @pytest.mark.asyncio
    async def test_interrupt(self):
        with patch("claw_forge.agent.session.ClaudeSDKClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client

            session = AgentSession(_make_options())
            await session.__aenter__()
            await session.interrupt()

            mock_client.interrupt.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_escalate_permissions(self):
        with patch("claw_forge.agent.session.ClaudeSDKClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client

            session = AgentSession(_make_options())
            await session.__aenter__()
            await session.escalate_permissions()

            mock_client.set_permission_mode.assert_awaited_once_with("bypassPermissions")

    @pytest.mark.asyncio
    async def test_switch_model(self):
        with patch("claw_forge.agent.session.ClaudeSDKClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client

            session = AgentSession(_make_options())
            await session.__aenter__()
            await session.switch_model("claude-opus-4-5")

            mock_client.set_model.assert_awaited_once_with("claude-opus-4-5")

    @pytest.mark.asyncio
    async def test_get_server_info(self):
        expected = {"version": "1.0.0"}
        with patch("claw_forge.agent.session.ClaudeSDKClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.get_server_info.return_value = expected

            session = AgentSession(_make_options())
            await session.__aenter__()
            result = await session.get_server_info()

        assert result == expected
