"""Tests for hooks."""

import pytest

from claw_forge.orchestrator.hooks import PreCompactHook, PreToolUseHook, SecurityPolicy


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


    @pytest.mark.asyncio
    async def test_custom_handler_blocks(self):
        hook = PreToolUseHook()

        async def blocking_handler(ctx):
            return {"allow": False, "reason": "custom block"}

        hook.add_handler(blocking_handler)
        result = await hook.check("some_tool", {})
        assert not result.allow
        assert "custom block" in result.reason

    @pytest.mark.asyncio
    async def test_custom_handler_allows(self):
        hook = PreToolUseHook()

        async def allowing_handler(ctx):
            return {"allow": True}

        hook.add_handler(allowing_handler)
        result = await hook.check("read_file", {"path": "/src/main.py"})
        assert result.allow

    @pytest.mark.asyncio
    async def test_blocked_path_in_file_path_key(self):
        hook = PreToolUseHook()
        result = await hook.check("write_file", {"file_path": "/etc/shadow"})
        assert not result.allow

    @pytest.mark.asyncio
    async def test_blocked_path_in_target_key(self):
        hook = PreToolUseHook()
        result = await hook.check("move_file", {"target": "/etc/passwd"})
        assert not result.allow

    @pytest.mark.asyncio
    async def test_safe_execute_command_exhausts_blocked_list(self):
        """Safe command that doesn't match any blocked pattern → loop exhausts (75->80, 76->75)."""
        hook = PreToolUseHook()
        result = await hook.check("execute_command", {"command": "echo hello"})
        assert result.allow


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

    @pytest.mark.asyncio
    async def test_flush_handles_exception(self):
        hook = PreCompactHook()

        async def bad_handler():
            msg = "boom"
            raise RuntimeError(msg)

        hook.add_flush_handler(bad_handler)
        # Should not raise; exception is swallowed
        result = await hook.flush({})
        assert result["flushed"] == []

    @pytest.mark.asyncio
    async def test_flush_no_handlers(self):
        hook = PreCompactHook()
        result = await hook.flush({"a": 1, "b": 2})
        assert result["flushed"] == []
        assert set(result["context_keys"]) == {"a", "b"}
