"""Tests for PreCompletionChecklistMiddleware."""
from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from claw_forge.agent.middleware.pre_completion import (
    DEFAULT_CHECKLIST_PROMPT,
    PreCompletionState,
    pre_completion_checklist_hook,
)

# ---------------------------------------------------------------------------
# TestPreCompletionState
# ---------------------------------------------------------------------------


class TestPreCompletionState:
    def test_initial_state(self) -> None:
        state = PreCompletionState()
        assert state.verification_count == 0
        assert state.max_verifications == 3

    def test_should_verify_when_below_max(self) -> None:
        state = PreCompletionState(max_verifications=3)
        assert state.should_verify() is True

    def test_should_verify_false_at_max(self) -> None:
        state = PreCompletionState(verification_count=3, max_verifications=3)
        assert state.should_verify() is False

    def test_should_verify_false_above_max(self) -> None:
        state = PreCompletionState(verification_count=5, max_verifications=3)
        assert state.should_verify() is False

    def test_increment_increases_count(self) -> None:
        state = PreCompletionState()
        state.increment()
        assert state.verification_count == 1

    def test_increment_multiple_times(self) -> None:
        state = PreCompletionState()
        state.increment()
        state.increment()
        state.increment()
        assert state.verification_count == 3

    def test_reset_zeroes_count(self) -> None:
        state = PreCompletionState()
        state.increment()
        state.increment()
        state.increment()
        assert state.verification_count == 3
        state.reset()
        assert state.verification_count == 0

    def test_custom_max_verifications(self) -> None:
        state = PreCompletionState(max_verifications=1)
        assert state.should_verify() is True
        state.increment()
        assert state.should_verify() is False


# ---------------------------------------------------------------------------
# TestPreCompletionChecklistHookFactory
# ---------------------------------------------------------------------------


class TestPreCompletionChecklistHookFactory:
    def test_returns_callable(self) -> None:
        hook = pre_completion_checklist_hook()
        assert callable(hook)

    def test_raises_on_zero_max_verifications(self) -> None:
        with pytest.raises(ValueError, match="max_verifications must be >= 1"):
            pre_completion_checklist_hook(max_verifications=0)

    def test_raises_on_negative_max_verifications(self) -> None:
        with pytest.raises(ValueError, match="max_verifications must be >= 1"):
            pre_completion_checklist_hook(max_verifications=-1)

    def test_default_prompt_not_empty(self) -> None:
        assert isinstance(DEFAULT_CHECKLIST_PROMPT, str)
        assert len(DEFAULT_CHECKLIST_PROMPT) > 0

    @pytest.mark.asyncio
    async def test_custom_prompt_accepted(self) -> None:
        hook = pre_completion_checklist_hook(checklist_prompt="custom check")
        result = await hook({}, None, {})
        assert result["hookSpecificOutput"]["additionalContext"] == "custom check"

    @pytest.mark.asyncio
    async def test_each_call_creates_independent_state(self) -> None:
        hook1 = pre_completion_checklist_hook(max_verifications=1)
        hook2 = pre_completion_checklist_hook(max_verifications=1)

        # Exhaust hook1
        r1 = await hook1({}, None, {})
        assert r1["continue_"] is True
        r1b = await hook1({}, None, {})
        assert r1b["continue_"] is False

        # hook2 should still be fresh
        r2 = await hook2({}, None, {})
        assert r2["continue_"] is True


# ---------------------------------------------------------------------------
# TestPreCompletionChecklistHookBehaviour
# ---------------------------------------------------------------------------


class TestPreCompletionChecklistHookBehaviour:
    @pytest.mark.asyncio
    async def test_injects_checklist_on_first_stop(self) -> None:
        hook = pre_completion_checklist_hook()
        result = await hook({"stop_hook_active": True}, None, {})
        assert result["continue_"] is True
        assert "additionalContext" in result["hookSpecificOutput"]

    @pytest.mark.asyncio
    async def test_checklist_event_name_is_stop(self) -> None:
        hook = pre_completion_checklist_hook()
        result = await hook({}, None, {})
        assert result["hookSpecificOutput"]["hookEventName"] == "Stop"

    @pytest.mark.asyncio
    async def test_injects_custom_prompt(self) -> None:
        hook = pre_completion_checklist_hook(checklist_prompt="my checklist")
        result = await hook({}, None, {})
        assert result["hookSpecificOutput"]["additionalContext"] == "my checklist"

    @pytest.mark.asyncio
    async def test_injects_default_prompt_when_none(self) -> None:
        hook = pre_completion_checklist_hook(checklist_prompt=None)
        result = await hook({}, None, {})
        assert result["hookSpecificOutput"]["additionalContext"] == DEFAULT_CHECKLIST_PROMPT

    @pytest.mark.asyncio
    async def test_increments_counter_on_inject(self) -> None:
        hook = pre_completion_checklist_hook(max_verifications=3)
        await hook({}, None, {})
        # Call again to check counter was incremented (second call still works)
        r2 = await hook({}, None, {})
        assert r2["continue_"] is True  # 2nd of 3

    @pytest.mark.asyncio
    async def test_allows_stop_after_max_verifications(self) -> None:
        hook = pre_completion_checklist_hook(max_verifications=2)
        # Exhaust the 2 allowed verifications
        await hook({}, None, {})
        await hook({}, None, {})
        # 3rd call should allow stop
        result = await hook({}, None, {})
        assert result["continue_"] is False

    @pytest.mark.asyncio
    async def test_counter_reaches_max_and_stops(self) -> None:
        hook = pre_completion_checklist_hook(max_verifications=3)
        results = []
        for _ in range(4):
            results.append(await hook({}, None, {}))
        assert results[0]["continue_"] is True
        assert results[1]["continue_"] is True
        assert results[2]["continue_"] is True
        assert results[3]["continue_"] is False

    @pytest.mark.asyncio
    async def test_resets_counter_on_exhaustion(self) -> None:
        hook = pre_completion_checklist_hook(max_verifications=1)
        r1 = await hook({}, None, {})
        assert r1["continue_"] is True
        r2 = await hook({}, None, {})
        assert r2["continue_"] is False
        # After reset, the hook should fire again
        r3 = await hook({}, None, {})
        assert r3["continue_"] is True

    @pytest.mark.asyncio
    async def test_max_verifications_one(self) -> None:
        hook = pre_completion_checklist_hook(max_verifications=1)
        r1 = await hook({}, None, {})
        assert r1["continue_"] is True
        r2 = await hook({}, None, {})
        assert r2["continue_"] is False

    @pytest.mark.asyncio
    async def test_non_dict_input_degrades_gracefully(self) -> None:
        hook = pre_completion_checklist_hook()
        result = await hook("not a dict", None, {})  # type: ignore[arg-type]
        assert result is not None
        assert "hookSpecificOutput" in result

    @pytest.mark.asyncio
    async def test_empty_dict_input(self) -> None:
        hook = pre_completion_checklist_hook()
        result = await hook({}, None, {})
        assert result["continue_"] is True

    @pytest.mark.asyncio
    async def test_stop_hook_inactive_still_injects(self) -> None:
        hook = pre_completion_checklist_hook()
        result = await hook({"stop_hook_active": False}, None, {})
        assert result["continue_"] is True

    @pytest.mark.asyncio
    async def test_context_can_be_empty_dict(self) -> None:
        hook = pre_completion_checklist_hook()
        result = await hook({}, None, {})
        assert result is not None

    @pytest.mark.asyncio
    async def test_context_can_be_none_like(self) -> None:
        hook = pre_completion_checklist_hook()
        result = await hook({}, None, None)  # type: ignore[arg-type]
        assert result is not None


# ---------------------------------------------------------------------------
# TestPreCompletionChecklistHookErrorHandling
# ---------------------------------------------------------------------------


class TestPreCompletionChecklistHookErrorHandling:
    @pytest.mark.asyncio
    async def test_degrades_on_internal_exception(self) -> None:
        hook = pre_completion_checklist_hook()
        with patch.object(
            PreCompletionState,
            "should_verify",
            side_effect=RuntimeError("boom"),
        ):
            result = await hook({}, None, {})
        assert result["continue_"] is False

    @pytest.mark.asyncio
    async def test_logs_warning_on_error(self, caplog: pytest.LogCaptureFixture) -> None:
        hook = pre_completion_checklist_hook()
        with (
            patch.object(
                PreCompletionState,
                "should_verify",
                side_effect=RuntimeError("test error"),
            ),
            caplog.at_level(logging.WARNING),
        ):
            await hook({}, None, {})
        assert any("hook error (degrading)" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_does_not_crash_agent(self) -> None:
        hook = pre_completion_checklist_hook()
        with patch.object(
            PreCompletionState,
            "should_verify",
            side_effect=RuntimeError("crash"),
        ):
            result = await hook({}, None, {})
        assert result is not None
        assert result["continue_"] is False


# ---------------------------------------------------------------------------
# TestPreCompletionIntegrationWithGetDefaultHooks
# ---------------------------------------------------------------------------


class TestPreCompletionIntegrationWithGetDefaultHooks:
    def test_stop_hook_present_by_default(self) -> None:
        from claw_forge.agent.hooks import get_default_hooks

        hooks = get_default_hooks()
        assert "Stop" in hooks

    def test_stop_hook_absent_when_disabled(self) -> None:
        from claw_forge.agent.hooks import get_default_hooks

        hooks = get_default_hooks(verify_on_exit=False)
        assert "Stop" not in hooks

    def test_stop_hook_is_hook_matcher_list(self) -> None:
        from claw_forge.agent.hooks import get_default_hooks

        hooks = get_default_hooks()
        assert isinstance(hooks["Stop"], list)
        assert len(hooks["Stop"]) > 0

    def test_stop_hook_contains_callable(self) -> None:
        from claw_forge.agent.hooks import get_default_hooks

        hooks = get_default_hooks()
        matcher = hooks["Stop"][0]
        # HookMatcher has a .hooks attribute which is a list of callables
        hook_list = getattr(matcher, "hooks", None)
        assert hook_list is not None
        assert len(hook_list) > 0
        assert callable(hook_list[0])

    def test_existing_hooks_unaffected(self) -> None:
        from claw_forge.agent.hooks import get_default_hooks

        hooks = get_default_hooks(verify_on_exit=True)
        assert "PreToolUse" in hooks
        assert "PreCompact" in hooks
        assert "PostToolUse" in hooks
        assert "PostToolUseFailure" in hooks
        assert "SubagentStart" in hooks
        assert "SubagentStop" in hooks

    @pytest.mark.asyncio
    async def test_each_get_default_hooks_call_independent(self) -> None:
        from claw_forge.agent.hooks import get_default_hooks

        hooks1 = get_default_hooks(verify_on_exit=True)
        hooks2 = get_default_hooks(verify_on_exit=True)

        hook1 = hooks1["Stop"][0].hooks[0]
        hook2 = hooks2["Stop"][0].hooks[0]

        # Exhaust hook1 (max_verifications=3 default)
        for _ in range(3):
            await hook1({}, None, {})
        r1 = await hook1({}, None, {})
        assert r1["continue_"] is False

        # hook2 should still be fresh
        r2 = await hook2({}, None, {})
        assert r2["continue_"] is True

    def test_hashline_and_verify_on_exit_combine(self) -> None:
        from claw_forge.agent.hooks import get_default_hooks

        hooks = get_default_hooks(edit_mode="hashline", verify_on_exit=True)
        assert "PostToolUse" in hooks
        assert "Stop" in hooks


# ---------------------------------------------------------------------------
# TestPreCompletionChecklistHookCLIIntegration
# ---------------------------------------------------------------------------


class TestPreCompletionChecklistHookCLIIntegration:
    def test_verify_on_exit_flag_accepted(self) -> None:
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["run", "--help"])
        assert "--verify-on-exit" in result.output
        assert "--no-verify-on-exit" in result.output

    def test_no_verify_on_exit_flag_accepted(self) -> None:
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        # Just check the flag is parsed without BadParameter error
        # (the command won't run without config, but it should get past flag parsing)
        result = runner.invoke(app, ["run", "--no-verify-on-exit", "--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# TestDefaultChecklistPrompt
# ---------------------------------------------------------------------------


class TestDefaultChecklistPrompt:
    def test_prompt_is_non_empty_string(self) -> None:
        assert isinstance(DEFAULT_CHECKLIST_PROMPT, str)
        assert len(DEFAULT_CHECKLIST_PROMPT) > 0

    def test_prompt_mentions_task_spec(self) -> None:
        assert "TASK SPEC" in DEFAULT_CHECKLIST_PROMPT

    def test_prompt_mentions_tests(self) -> None:
        assert "TESTS" in DEFAULT_CHECKLIST_PROMPT

    def test_prompt_mentions_verify(self) -> None:
        assert "VERIFY" in DEFAULT_CHECKLIST_PROMPT

    def test_prompt_mentions_fix(self) -> None:
        assert "FIX" in DEFAULT_CHECKLIST_PROMPT


# ---------------------------------------------------------------------------
# TestModuleExports
# ---------------------------------------------------------------------------


class TestModuleExports:
    def test_exports_pre_completion_checklist_hook(self) -> None:
        from claw_forge.agent.middleware import pre_completion_checklist_hook as fn

        assert callable(fn)

    def test_exports_pre_completion_state(self) -> None:
        from claw_forge.agent.middleware import PreCompletionState as cls

        assert cls is not None

    def test_exports_default_checklist_prompt(self) -> None:
        from claw_forge.agent.middleware import DEFAULT_CHECKLIST_PROMPT as prompt

        assert isinstance(prompt, str)
