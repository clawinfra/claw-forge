"""Tests for hooks."""

import pytest

from claw_forge.orchestrator.hooks import PreToolUseHook, PreCompactHook, SecurityPolicy


class TestPreToolUseHook:
    @pytest.mark.asyncio
    async def test_allows_normal_tool(self):
        hook = PreToolUseHook()
        result = await hook.check("read_file", {"path": "/src/main.py"})
        assert result.allow

    @pytest.mark.asyncio
    async def test_blocks_dangerous_command(self):
        hook = PreToolUseHook()
        result = await hook.check("execute_command", {"command": "rm -rf /"})
        assert not result.allow

    @pytest.mark.asyncio
    async def test_blocks_sensitive_path(self):
        hook = PreToolUseHook()
        result = await hook.check("read_file", {"path": "/etc/shadow"})
        assert not result.allow

    @pytest.mark.asyncio
    async def test_command_length_limit(self):
        hook = PreToolUseHook(SecurityPolicy(max_command_length=10))
        result = await hook.check("execute_command", {"command": "x" * 100})
        assert not result.allow

    @pytest.mark.asyncio
    async def test_tool_allowlist(self):
        policy = SecurityPolicy(require_tool_allowlist=True, allowed_tools=["read_file"])
        hook = PreToolUseHook(policy)
        result = await hook.check("dangerous_tool", {})
        assert not result.allow


class TestPreCompactHook:
    @pytest.mark.asyncio
    async def test_flush_runs_handlers(self):
        hook = PreCompactHook()
        called = []

        async def handler():
            called.append(True)

        hook.add_flush_handler(handler)
        result = await hook.flush({"key": "value"})
        assert len(called) == 1
        assert "flushed" in result
