"""Tests for sub-agent hooks: counter tracking and soft-limit."""
from __future__ import annotations

import asyncio

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
        start_hook, stop_hook, state = make_subagent_hooks(
            max_subagents=5, state_url="http://localhost:8420",
        )
        # Even with a bad URL (nothing listening), the hook should not raise
        await start_hook(
            {"agent_id": "a1", "agent_type": "coding", "task_id": "t1"}, None, {},
        )
        await asyncio.sleep(0.1)  # let fire-and-forget task complete
        assert state["active"] == 1  # counter still updated
