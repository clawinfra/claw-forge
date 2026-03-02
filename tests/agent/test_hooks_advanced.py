"""Tests for advanced SDK hooks — PostToolUse, Stop, Notification, SubagentStart, etc."""
from __future__ import annotations

import asyncio

import pytest

from claw_forge.agent.hooks import (
    get_default_hooks,
    make_notification_hook,
    make_prompt_enrichment_hook,
    make_stop_hook,
    post_tool_failure_hook,
    post_tool_hook,
    subagent_start_hook,
    subagent_stop_hook,
)

# ---------------------------------------------------------------------------
# post_tool_hook
# ---------------------------------------------------------------------------


class TestPostToolHook:
    @pytest.mark.asyncio
    async def test_returns_post_tool_use_event(self):
        result = await post_tool_hook({"tool_name": "Bash"}, "tool-1", {})
        assert result["hookSpecificOutput"]["hookEventName"] == "PostToolUse"

    @pytest.mark.asyncio
    async def test_handles_non_dict_input(self):
        result = await post_tool_hook("raw-string", None, {})
        assert result["hookSpecificOutput"]["hookEventName"] == "PostToolUse"


# ---------------------------------------------------------------------------
# post_tool_failure_hook
# ---------------------------------------------------------------------------


class TestPostToolFailureHook:
    @pytest.mark.asyncio
    async def test_returns_failure_event(self):
        result = await post_tool_failure_hook(
            {"error": "file not found", "tool_name": "Read"}, "tool-2", {}
        )
        assert result["hookSpecificOutput"]["hookEventName"] == "PostToolUseFailure"

    @pytest.mark.asyncio
    async def test_includes_tool_name_in_context(self):
        result = await post_tool_failure_hook(
            {"error": "timeout", "tool_name": "Bash"}, None, {}
        )
        assert "Bash" in result["hookSpecificOutput"]["additionalContext"]

    @pytest.mark.asyncio
    async def test_logs_error(self, capsys):
        await post_tool_failure_hook(
            {"error": "connection refused", "tool_name": "MCP"}, None, {}
        )
        captured = capsys.readouterr()
        assert "[Tool failure] MCP: connection refused" in captured.out

    @pytest.mark.asyncio
    async def test_truncates_long_errors(self, capsys):
        long_error = "x" * 500
        await post_tool_failure_hook(
            {"error": long_error, "tool_name": "Bash"}, None, {}
        )
        captured = capsys.readouterr()
        # Should truncate to 200 chars in the log line
        log_line = captured.out.strip()
        error_part = log_line.split(": ", 1)[1]
        assert len(error_part) <= 200

    @pytest.mark.asyncio
    async def test_handles_empty_input(self):
        result = await post_tool_failure_hook({}, None, {})
        assert result["hookSpecificOutput"]["hookEventName"] == "PostToolUseFailure"


# ---------------------------------------------------------------------------
# make_prompt_enrichment_hook
# ---------------------------------------------------------------------------


class TestPromptEnrichmentHook:
    @pytest.mark.asyncio
    async def test_injects_callable_result(self):
        hook = make_prompt_enrichment_hook(lambda: "features: 5 pending")
        result = await hook({}, None, {})
        assert result["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
        assert result["hookSpecificOutput"]["additionalContext"] == "features: 5 pending"

    @pytest.mark.asyncio
    async def test_injects_static_string(self):
        hook = make_prompt_enrichment_hook("static context")
        result = await hook({}, None, {})
        assert result["hookSpecificOutput"]["additionalContext"] == "static context"

    @pytest.mark.asyncio
    async def test_callable_called_each_invocation(self):
        counter = {"n": 0}

        def count_fn():
            counter["n"] += 1
            return f"call-{counter['n']}"

        hook = make_prompt_enrichment_hook(count_fn)
        r1 = await hook({}, None, {})
        r2 = await hook({}, None, {})
        assert r1["hookSpecificOutput"]["additionalContext"] == "call-1"
        assert r2["hookSpecificOutput"]["additionalContext"] == "call-2"

    @pytest.mark.asyncio
    async def test_non_string_non_callable_coerced(self):
        hook = make_prompt_enrichment_hook(42)  # type: ignore[arg-type]
        result = await hook({}, None, {})
        assert result["hookSpecificOutput"]["additionalContext"] == "42"


# ---------------------------------------------------------------------------
# make_stop_hook
# ---------------------------------------------------------------------------


class TestStopHook:
    @pytest.mark.asyncio
    async def test_continues_when_should_continue(self):
        hook = make_stop_hook(lambda: True)
        result = await hook({"stop_hook_active": True}, None, {})
        assert result["continue_"] is True
        assert "Continue working" in result["hookSpecificOutput"]["additionalContext"]

    @pytest.mark.asyncio
    async def test_stops_when_should_not_continue(self):
        hook = make_stop_hook(lambda: False)
        result = await hook({"stop_hook_active": True}, None, {})
        assert result["continue_"] is False

    @pytest.mark.asyncio
    async def test_stops_when_hook_not_active(self):
        hook = make_stop_hook(lambda: True)
        result = await hook({}, None, {})
        assert result["continue_"] is False

    @pytest.mark.asyncio
    async def test_dynamic_should_continue(self):
        """should_continue_fn is checked on each invocation."""
        state = {"continue": True}
        hook = make_stop_hook(lambda: state["continue"])

        r1 = await hook({"stop_hook_active": True}, None, {})
        assert r1["continue_"] is True

        state["continue"] = False
        r2 = await hook({"stop_hook_active": True}, None, {})
        assert r2["continue_"] is False


# ---------------------------------------------------------------------------
# make_notification_hook
# ---------------------------------------------------------------------------


class TestNotificationHook:
    @pytest.mark.asyncio
    async def test_prints_message(self, capsys):
        hook = make_notification_hook()
        await hook({"title": "Build", "message": "Feature X done"}, None, {})
        captured = capsys.readouterr()
        assert "[Build] Feature X done" in captured.out

    @pytest.mark.asyncio
    async def test_calls_broadcast_fn(self):
        received_payload = {}

        async def mock_broadcast(payload):
            received_payload.update(payload)

        hook = make_notification_hook(broadcast_fn=mock_broadcast)
        await hook({"title": "Agent", "message": "hello"}, None, {})

        # Wait for the background task to complete
        await asyncio.sleep(0.05)
        assert received_payload.get("type") == "agent_notification"
        assert received_payload.get("title") == "Agent"
        assert received_payload.get("message") == "hello"

    @pytest.mark.asyncio
    async def test_returns_notification_event(self):
        hook = make_notification_hook()
        result = await hook({"title": "T", "message": "M"}, None, {})
        assert result["hookSpecificOutput"]["hookEventName"] == "Notification"

    @pytest.mark.asyncio
    async def test_default_title(self, capsys):
        hook = make_notification_hook()
        await hook({"message": "no title"}, None, {})
        captured = capsys.readouterr()
        assert "[Agent]" in captured.out


# ---------------------------------------------------------------------------
# subagent_start_hook
# ---------------------------------------------------------------------------


class TestSubagentStartHook:
    @pytest.mark.asyncio
    async def test_returns_subagent_start_event(self):
        result = await subagent_start_hook(
            {"agent_id": "a-123", "agent_type": "coding"}, None, {}
        )
        assert result["hookSpecificOutput"]["hookEventName"] == "SubagentStart"

    @pytest.mark.asyncio
    async def test_includes_agent_type_in_context(self):
        result = await subagent_start_hook(
            {"agent_id": "a-456", "agent_type": "reviewer"}, None, {}
        )
        assert "reviewer" in result["hookSpecificOutput"]["additionalContext"]

    @pytest.mark.asyncio
    async def test_logs_subagent_start(self, capsys):
        await subagent_start_hook(
            {"agent_id": "a-789", "agent_type": "testing"}, None, {}
        )
        captured = capsys.readouterr()
        assert "[SubAgent] Starting: testing (a-789)" in captured.out


# ---------------------------------------------------------------------------
# subagent_stop_hook
# ---------------------------------------------------------------------------


class TestSubagentStopHook:
    @pytest.mark.asyncio
    async def test_returns_subagent_stop_event(self):
        result = await subagent_stop_hook(
            {"agent_id": "a-123", "agent_type": "coding"}, None, {}
        )
        assert result["hookSpecificOutput"]["hookEventName"] == "SubagentStop"

    @pytest.mark.asyncio
    async def test_logs_subagent_stop(self, capsys):
        await subagent_stop_hook(
            {"agent_id": "a-123", "agent_type": "coding"}, None, {}
        )
        captured = capsys.readouterr()
        assert "[SubAgent] Stopped: coding (a-123)" in captured.out


# ---------------------------------------------------------------------------
# get_default_hooks includes new hooks
# ---------------------------------------------------------------------------


class TestDefaultHooksIncludesNewHooks:
    def test_has_post_tool_use(self):
        hooks = get_default_hooks()
        assert "PostToolUse" in hooks

    def test_has_post_tool_use_failure(self):
        hooks = get_default_hooks()
        assert "PostToolUseFailure" in hooks

    def test_has_subagent_start(self):
        hooks = get_default_hooks()
        assert "SubagentStart" in hooks

    def test_has_subagent_stop(self):
        hooks = get_default_hooks()
        assert "SubagentStop" in hooks

    def test_still_has_pre_tool_use(self):
        hooks = get_default_hooks()
        assert "PreToolUse" in hooks

    def test_still_has_pre_compact(self):
        hooks = get_default_hooks()
        assert "PreCompact" in hooks
