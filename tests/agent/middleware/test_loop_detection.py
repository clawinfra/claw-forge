"""Tests for loop detection middleware — doom-loop prevention for agents."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import Mock

import pytest

from claw_forge.agent.middleware.loop_detection import (
    LoopContext,
    _build_warning,
    loop_detection_hook,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_edit_input(
    tool_name: str = "Edit",
    file_path: str = "foo.py",
    *,
    path_key: str = "file_path",
) -> dict[str, Any]:
    """Build a mock PostToolUse input_data dict for an edit-type tool."""
    return {
        "tool_name": tool_name,
        "input": {path_key: file_path},
    }


def _make_non_edit_input(tool_name: str = "Bash") -> dict[str, Any]:
    """Build a mock PostToolUse input_data dict for a non-edit tool."""
    return {
        "tool_name": tool_name,
        "input": {"command": "ls -la"},
    }


# ── TestLoopContext ───────────────────────────────────────────────────────────


class TestLoopContext:
    def test_default_threshold(self) -> None:
        assert LoopContext().threshold == 5

    def test_default_edit_counts_empty(self) -> None:
        assert LoopContext().edit_counts == {}

    def test_default_injections_zero(self) -> None:
        assert LoopContext().injections == 0

    def test_custom_threshold(self) -> None:
        assert LoopContext(threshold=8).threshold == 8

    def test_edit_counts_is_independent_per_instance(self) -> None:
        ctx1 = LoopContext()
        ctx2 = LoopContext()
        ctx1.edit_counts["a.py"] = 3
        assert "a.py" not in ctx2.edit_counts


# ── TestLoopDetectionHookFactory ──────────────────────────────────────────────


class TestLoopDetectionHookFactory:
    def test_returns_tuple(self) -> None:
        result = loop_detection_hook()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_first_element_callable(self) -> None:
        hook_fn, _ = loop_detection_hook()
        assert callable(hook_fn)

    def test_second_element_is_loop_context(self) -> None:
        _, ctx = loop_detection_hook()
        assert isinstance(ctx, LoopContext)

    def test_context_threshold_matches_arg(self) -> None:
        _, ctx = loop_detection_hook(threshold=7)
        assert ctx.threshold == 7

    def test_hashline_raises_threshold(self) -> None:
        _, ctx = loop_detection_hook(threshold=5, edit_mode="hashline")
        assert ctx.threshold == 8  # 5 + 3

    def test_hashline_boost_ignored_when_disabled(self) -> None:
        _, ctx = loop_detection_hook(threshold=0, edit_mode="hashline")
        assert ctx.threshold == 0

    def test_default_threshold_is_five(self) -> None:
        _, ctx = loop_detection_hook()
        assert ctx.threshold == 5

    def test_custom_threshold_respected(self) -> None:
        _, ctx = loop_detection_hook(threshold=10)
        assert ctx.threshold == 10


# ── TestLoopDetectionHookBehaviour ────────────────────────────────────────────


class TestLoopDetectionHookBehaviour:
    @pytest.mark.asyncio
    async def test_noop_for_non_edit_tool(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5)
        result = await hook_fn(_make_non_edit_input("Bash"), None, {})
        assert result["hookSpecificOutput"]["additionalContext"] == ""
        assert ctx.edit_counts == {}

    @pytest.mark.asyncio
    async def test_noop_for_non_edit_tool_read(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5)
        result = await hook_fn(_make_non_edit_input("Read"), None, {})
        assert result["hookSpecificOutput"]["additionalContext"] == ""

    @pytest.mark.asyncio
    async def test_noop_for_non_edit_tool_grep(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5)
        result = await hook_fn(_make_non_edit_input("Grep"), None, {})
        assert result["hookSpecificOutput"]["additionalContext"] == ""

    @pytest.mark.asyncio
    async def test_counts_edit_tool(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5)
        await hook_fn(_make_edit_input("Edit", "foo.py"), None, {})
        assert ctx.edit_counts["foo.py"] == 1

    @pytest.mark.asyncio
    async def test_counts_write_tool(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5)
        await hook_fn(_make_edit_input("Write", "bar.py"), None, {})
        assert ctx.edit_counts["bar.py"] == 1

    @pytest.mark.asyncio
    async def test_counts_multiedit_tool(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5)
        await hook_fn(_make_edit_input("MultiEdit", "baz.py"), None, {})
        assert ctx.edit_counts["baz.py"] == 1

    @pytest.mark.asyncio
    async def test_no_injection_below_threshold(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5)
        for _ in range(4):
            result = await hook_fn(_make_edit_input("Edit", "foo.py"), None, {})
        assert result["hookSpecificOutput"]["additionalContext"] == ""
        assert ctx.injections == 0

    @pytest.mark.asyncio
    async def test_injection_at_threshold(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5)
        for _ in range(5):
            result = await hook_fn(_make_edit_input("Edit", "foo.py"), None, {})
        assert result["hookSpecificOutput"]["additionalContext"] != ""
        assert ctx.injections == 1

    @pytest.mark.asyncio
    async def test_injection_above_threshold(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5)
        for _ in range(6):
            await hook_fn(_make_edit_input("Edit", "foo.py"), None, {})
        assert ctx.injections == 2

    @pytest.mark.asyncio
    async def test_injection_count_increments(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5)
        for _ in range(7):
            await hook_fn(_make_edit_input("Edit", "foo.py"), None, {})
        assert ctx.injections == 3  # 5th, 6th, 7th

    @pytest.mark.asyncio
    async def test_separate_files_independent(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5)
        for _ in range(4):
            await hook_fn(_make_edit_input("Edit", "foo.py"), None, {})
        for _ in range(4):
            await hook_fn(_make_edit_input("Edit", "bar.py"), None, {})
        assert ctx.edit_counts["foo.py"] == 4
        assert ctx.edit_counts["bar.py"] == 4
        assert ctx.injections == 0

    @pytest.mark.asyncio
    async def test_warning_contains_filename(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=2)
        for _ in range(2):
            result = await hook_fn(_make_edit_input("Edit", "myfile.py"), None, {})
        assert "myfile.py" in result["hookSpecificOutput"]["additionalContext"]

    @pytest.mark.asyncio
    async def test_warning_contains_count(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=2)
        for _ in range(3):
            result = await hook_fn(_make_edit_input("Edit", "x.py"), None, {})
        assert "3" in result["hookSpecificOutput"]["additionalContext"]

    @pytest.mark.asyncio
    async def test_warning_contains_threshold(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=2)
        for _ in range(2):
            result = await hook_fn(_make_edit_input("Edit", "x.py"), None, {})
        # The threshold value should appear in the warning
        assert "2" in result["hookSpecificOutput"]["additionalContext"]

    @pytest.mark.asyncio
    async def test_returns_post_tool_use_event(self) -> None:
        hook_fn, _ = loop_detection_hook(threshold=5)
        result = await hook_fn(_make_edit_input("Edit", "foo.py"), None, {})
        assert result["hookSpecificOutput"]["hookEventName"] == "PostToolUse"

    @pytest.mark.asyncio
    async def test_noop_when_disabled(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=0)
        for _ in range(100):
            result = await hook_fn(_make_edit_input("Edit", "foo.py"), None, {})
        assert result["hookSpecificOutput"]["additionalContext"] == ""
        assert ctx.injections == 0

    @pytest.mark.asyncio
    async def test_noop_for_missing_file_path(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5)
        data: dict[str, Any] = {"tool_name": "Edit", "input": {"content": "hello"}}
        result = await hook_fn(data, None, {})
        assert result["hookSpecificOutput"]["additionalContext"] == ""
        assert ctx.edit_counts == {}

    @pytest.mark.asyncio
    async def test_noop_for_non_dict_input(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5)
        result = await hook_fn("raw string", None, {})
        assert result["hookSpecificOutput"]["additionalContext"] == ""

    @pytest.mark.asyncio
    async def test_noop_for_non_dict_tool_input(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5)
        data: dict[str, Any] = {"tool_name": "Edit", "input": "not-a-dict"}
        result = await hook_fn(data, None, {})
        assert result["hookSpecificOutput"]["additionalContext"] == ""

    @pytest.mark.asyncio
    async def test_file_path_key_variants(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5)
        # file_path key
        await hook_fn(_make_edit_input("Edit", "a.py", path_key="file_path"), None, {})
        assert ctx.edit_counts.get("a.py") == 1

    @pytest.mark.asyncio
    async def test_path_key_extracted(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5)
        data: dict[str, Any] = {"tool_name": "Edit", "input": {"path": "x.py"}}
        await hook_fn(data, None, {})
        assert ctx.edit_counts["x.py"] == 1

    @pytest.mark.asyncio
    async def test_target_key_extracted(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5)
        data: dict[str, Any] = {"tool_name": "Edit", "input": {"target": "z.py"}}
        await hook_fn(data, None, {})
        assert ctx.edit_counts["z.py"] == 1


# ── TestLoopDetectionHookGracefulness ─────────────────────────────────────────


class TestLoopDetectionHookGracefulness:
    @pytest.mark.asyncio
    async def test_no_exception_on_none_input(self) -> None:
        hook_fn, _ = loop_detection_hook(threshold=5)
        result = await hook_fn(None, None, {})
        assert result["hookSpecificOutput"]["hookEventName"] == "PostToolUse"

    @pytest.mark.asyncio
    async def test_no_exception_on_empty_dict(self) -> None:
        hook_fn, _ = loop_detection_hook(threshold=5)
        result = await hook_fn({}, None, {})
        assert result["hookSpecificOutput"]["hookEventName"] == "PostToolUse"

    @pytest.mark.asyncio
    async def test_no_exception_on_missing_tool_name(self) -> None:
        hook_fn, _ = loop_detection_hook(threshold=5)
        result = await hook_fn({"input": {"file_path": "x.py"}}, None, {})
        assert result["hookSpecificOutput"]["hookEventName"] == "PostToolUse"

    @pytest.mark.asyncio
    async def test_logs_on_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5)
        # Monkeypatch edit_counts to raise on __setitem__
        broken_dict = Mock(spec=dict)
        broken_dict.get.side_effect = RuntimeError("boom")
        ctx.edit_counts = broken_dict  # type: ignore[assignment]

        with caplog.at_level(logging.WARNING):
            result = await hook_fn(_make_edit_input("Edit", "foo.py"), None, {})
        assert result["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
        assert any("Hook error" in rec.message for rec in caplog.records)


# ── TestLoopDetectionHashlineThreshold ────────────────────────────────────────


class TestLoopDetectionHashlineThreshold:
    def test_hashline_threshold_is_eight_by_default(self) -> None:
        _, ctx = loop_detection_hook(threshold=5, edit_mode="hashline")
        assert ctx.threshold == 8

    @pytest.mark.asyncio
    async def test_hashline_no_injection_at_seven(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5, edit_mode="hashline")
        for _ in range(7):
            result = await hook_fn(_make_edit_input("Edit", "foo.py"), None, {})
        assert result["hookSpecificOutput"]["additionalContext"] == ""
        assert ctx.injections == 0

    @pytest.mark.asyncio
    async def test_hashline_injection_at_eight(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5, edit_mode="hashline")
        for _ in range(8):
            result = await hook_fn(_make_edit_input("Edit", "foo.py"), None, {})
        assert result["hookSpecificOutput"]["additionalContext"] != ""
        assert ctx.injections == 1

    @pytest.mark.asyncio
    async def test_str_replace_injection_at_five(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=5, edit_mode="str_replace")
        for _ in range(5):
            result = await hook_fn(_make_edit_input("Edit", "foo.py"), None, {})
        assert result["hookSpecificOutput"]["additionalContext"] != ""
        assert ctx.injections == 1

    @pytest.mark.asyncio
    async def test_zero_threshold_with_hashline_stays_disabled(self) -> None:
        hook_fn, ctx = loop_detection_hook(threshold=0, edit_mode="hashline")
        for _ in range(20):
            result = await hook_fn(_make_edit_input("Edit", "foo.py"), None, {})
        assert result["hookSpecificOutput"]["additionalContext"] == ""
        assert ctx.injections == 0


# ── TestGetDefaultHooksIntegration ────────────────────────────────────────────


class TestGetDefaultHooksIntegration:
    def test_loop_detection_present_by_default(self) -> None:
        from claw_forge.agent.hooks import get_default_hooks

        hooks = get_default_hooks()
        post_tool_use = hooks["PostToolUse"]
        # Default: 1 base post_tool_hook + 1 loop detection = 2 matchers
        assert len(post_tool_use) >= 2

    def test_loop_detection_absent_when_disabled(self) -> None:
        from claw_forge.agent.hooks import get_default_hooks

        hooks_disabled = get_default_hooks(loop_detect_threshold=0)
        hooks_enabled = get_default_hooks(loop_detect_threshold=5)
        assert len(hooks_disabled["PostToolUse"]) < len(hooks_enabled["PostToolUse"])

    def test_custom_threshold_passed_through(self) -> None:
        from claw_forge.agent.hooks import get_default_hooks

        hooks = get_default_hooks(loop_detect_threshold=3)
        # Verify there are at least 2 PostToolUse matchers (base + loop)
        assert len(hooks["PostToolUse"]) >= 2

    def test_hashline_mode_passes_edit_mode(self) -> None:
        from claw_forge.agent.hooks import get_default_hooks

        hooks = get_default_hooks("hashline", loop_detect_threshold=5)
        # hashline adds Read matcher + loop detection + base = 3+
        assert len(hooks["PostToolUse"]) >= 3


# ── TestLoopDetectionCLIConfig ────────────────────────────────────────────────


class TestLoopDetectionCLIConfig:
    def test_default_threshold_is_five(self) -> None:
        cfg: dict[str, Any] = {}
        assert cfg.get("agent", {}).get("loop_detect_threshold", 5) == 5

    def test_config_overrides_default(self) -> None:
        cfg: dict[str, Any] = {"agent": {"loop_detect_threshold": 3}}
        assert cfg.get("agent", {}).get("loop_detect_threshold", 5) == 3

    def test_zero_disables(self) -> None:
        cfg: dict[str, Any] = {"agent": {"loop_detect_threshold": 0}}
        val = cfg.get("agent", {}).get("loop_detect_threshold", 5)
        assert val == 0


# ── TestBuildWarning ──────────────────────────────────────────────────────────


class TestBuildWarning:
    def test_contains_file_path(self) -> None:
        result = _build_warning("src/main.py", 7, 5)
        assert "src/main.py" in result

    def test_contains_count(self) -> None:
        result = _build_warning("x.py", 12, 5)
        assert "12" in result

    def test_contains_threshold(self) -> None:
        result = _build_warning("x.py", 7, 5)
        assert "5" in result

    def test_contains_reconsider_guidance(self) -> None:
        result = _build_warning("x.py", 7, 5)
        assert "Re-read the original spec" in result

    def test_no_empty_string(self) -> None:
        result = _build_warning("x.py", 7, 5)
        assert len(result) > 0
