"""Tests for sub-agent hooks: counter tracking and soft-limit."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claw_forge.agent.hooks import make_subagent_hooks


class TestSubagentHooks:
    @pytest.mark.asyncio
    async def test_counter_increments_on_start(self) -> None:
        start_hook, stop_hook, state = make_subagent_hooks(max_subagents=5)
        await start_hook({"agent_id": "a1", "agent_type": "coding"}, None, {})
        assert state["total_spawned"] == 1
        assert state["active"] == 1

    @pytest.mark.asyncio
    async def test_counter_decrements_on_stop(self) -> None:
        start_hook, stop_hook, state = make_subagent_hooks(max_subagents=5)
        await start_hook({"agent_id": "a1", "agent_type": "coding"}, None, {})
        await stop_hook({"agent_id": "a1", "agent_type": "coding"}, None, {})
        assert state["active"] == 0
        assert state["total_spawned"] == 1

    @pytest.mark.asyncio
    async def test_soft_limit_warning(self) -> None:
        start_hook, stop_hook, state = make_subagent_hooks(max_subagents=2)
        await start_hook({"agent_id": "a1", "agent_type": "coding"}, None, {})
        await start_hook({"agent_id": "a2", "agent_type": "coding"}, None, {})
        result = await start_hook({"agent_id": "a3", "agent_type": "coding"}, None, {})
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "limit" in ctx.lower() or "sequentially" in ctx.lower()

    @pytest.mark.asyncio
    async def test_no_warning_below_limit(self) -> None:
        start_hook, stop_hook, state = make_subagent_hooks(max_subagents=5)
        result = await start_hook({"agent_id": "a1", "agent_type": "coding"}, None, {})
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "limit" not in ctx.lower()

    @pytest.mark.asyncio
    async def test_unlimited_when_zero(self) -> None:
        start_hook, stop_hook, state = make_subagent_hooks(max_subagents=0)
        for i in range(20):
            result = await start_hook({"agent_id": f"a{i}", "agent_type": "coding"}, None, {})
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "limit" not in ctx.lower()

    @pytest.mark.asyncio
    async def test_active_never_negative(self) -> None:
        start_hook, stop_hook, state = make_subagent_hooks(max_subagents=5)
        await stop_hook({"agent_id": "a1", "agent_type": "coding"}, None, {})
        assert state["active"] == 0

    @pytest.mark.asyncio
    async def test_stop_hook_returns_subagent_stop_event(self) -> None:
        start_hook, stop_hook, state = make_subagent_hooks(max_subagents=5)
        await start_hook({"agent_id": "a1", "agent_type": "coding"}, None, {})
        result = await stop_hook({"agent_id": "a1", "agent_type": "coding"}, None, {})
        assert result["hookSpecificOutput"]["hookEventName"] == "SubagentStop"

    @pytest.mark.asyncio
    async def test_patch_failure_does_not_block(self) -> None:
        # Use a port that is definitely not in use to trigger connection error
        start_hook, stop_hook, state = make_subagent_hooks(
            max_subagents=5, state_url="http://127.0.0.1:1",
        )
        # The hook should not raise — PATCH is best-effort
        await start_hook(
            {"agent_id": "a1", "agent_type": "coding", "task_id": "t1"}, None, {},
        )
        # Give fire-and-forget task time to attempt connection and fail
        await asyncio.sleep(0.5)
        assert state["active"] == 1  # counter still updated

    @pytest.mark.asyncio
    async def test_patch_success_path(self) -> None:
        """Exercise the httpx success path by calling _patch_subagent_count directly."""
        import httpx

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.patch = AsyncMock(return_value=MagicMock(status_code=200))

        start_hook, stop_hook, state = make_subagent_hooks(
            max_subagents=5, state_url="http://localhost:9999",
        )
        # Inject mock client into the shared client dict
        # The factory stores it in _shared_client["client"]
        # Access via closure: start_hook.__code__.co_consts won't work,
        # so we patch httpx.AsyncClient to return our mock
        with patch("httpx.AsyncClient", return_value=mock_client):
            await start_hook(
                {"agent_id": "a1", "agent_type": "coding", "task_id": "t1"},
                None, {},
            )
            await asyncio.sleep(0.1)  # let fire-and-forget task complete
            mock_client.patch.assert_called_once_with(
                "http://localhost:9999/tasks/t1",
                json={"active_subagents": 1},
            )

    @pytest.mark.asyncio
    async def test_patch_reuses_cached_client(self) -> None:
        """Second call reuses the lazily cached httpx client."""
        import httpx

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.patch = AsyncMock(return_value=MagicMock(status_code=200))

        with patch("httpx.AsyncClient", return_value=mock_client) as mock_cls:
            start_hook, stop_hook, state = make_subagent_hooks(
                max_subagents=5, state_url="http://localhost:9999",
            )
            # First call — creates client
            await start_hook(
                {"agent_id": "a1", "agent_type": "coding", "task_id": "t1"},
                None, {},
            )
            await asyncio.sleep(0.1)
            # Second call — should reuse cached client (branch 271->274)
            await start_hook(
                {"agent_id": "a2", "agent_type": "coding", "task_id": "t1"},
                None, {},
            )
            await asyncio.sleep(0.1)
            # AsyncClient constructor called only once (cached)
            mock_cls.assert_called_once()
            assert mock_client.patch.call_count == 2

    @pytest.mark.asyncio
    async def test_no_patch_without_task_id(self) -> None:
        """No PATCH when task_id is missing from input_data."""
        with patch("httpx.AsyncClient") as mock_cls:
            start_hook, stop_hook, state = make_subagent_hooks(
                max_subagents=5, state_url="http://localhost:8420",
            )
            await start_hook(
                {"agent_id": "a1", "agent_type": "coding"}, None, {},
            )
            await asyncio.sleep(0.05)
            mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_patch_without_state_url(self) -> None:
        """No PATCH when state_url is None."""
        with patch("httpx.AsyncClient") as mock_cls:
            start_hook, stop_hook, state = make_subagent_hooks(
                max_subagents=5, state_url=None,
            )
            await start_hook(
                {"agent_id": "a1", "agent_type": "coding", "task_id": "t1"},
                None, {},
            )
            await asyncio.sleep(0.05)
            mock_cls.assert_not_called()
