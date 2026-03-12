"""PreCompletionChecklistMiddleware — force verification before agent exit.

Intercepts Stop events and injects a structured checklist that forces the
agent to re-read the task spec, run tests, and verify correctness before
it is allowed to exit.

Reference: LangChain deepagents research (Terminal Bench 2.0, 2026-03-12)
Issue: https://github.com/clawinfra/claw-forge/issues/4
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

try:
    from claude_agent_sdk.types import HookContext, HookInput, SyncHookJSONOutput
except ImportError:  # pragma: no cover
    HookContext = Any  # type: ignore[assignment,misc]
    HookInput = Any  # type: ignore[assignment,misc]
    SyncHookJSONOutput = Any  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

DEFAULT_CHECKLIST_PROMPT: str = """\
Before you finish, complete this checklist:

1. TASK SPEC: Re-read the original task description. Do NOT read your own \
code — read the spec.
2. TESTS: Run the test suite now. Read the full output, not just the \
pass/fail summary.
3. VERIFY: Does your output match what the spec asked for exactly? Check \
edge cases.
4. FIX: If anything fails, fix it now. Do not exit with failing tests.

Only exit when: all tests pass AND output matches the original specification.\
"""


@dataclass
class PreCompletionState:
    """Mutable state container for one agent session's verification counter.

    Attributes:
        verification_count: Number of times the checklist has been injected
            for the current session. Reset by calling reset().
        max_verifications: Maximum times the checklist may be injected before
            the hook degrades and allows the agent to stop unconditionally.
    """

    verification_count: int = field(default=0)
    max_verifications: int = field(default=3)

    def should_verify(self) -> bool:
        """Return True if verification_count is below max_verifications."""
        return self.verification_count < self.max_verifications

    def increment(self) -> None:
        """Increment verification_count by 1."""
        self.verification_count += 1

    def reset(self) -> None:
        """Reset verification_count to 0."""
        self.verification_count = 0


def pre_completion_checklist_hook(
    checklist_prompt: str | None = None,
    max_verifications: int = 3,
) -> Callable[..., Any]:
    """Factory that returns a Stop-event hook injecting a pre-completion checklist.

    The returned hook intercepts Stop events and forces the agent to verify
    correctness before exiting. After max_verifications activations within
    a single agent session, the hook steps aside and allows the stop.

    State is kept in a closure-local PreCompletionState instance, so each
    call to pre_completion_checklist_hook() creates an independent counter.
    This means each get_default_hooks() call (= each agent task execution)
    gets its own verification counter — no cross-task state leakage.

    Args:
        checklist_prompt: Custom verification prompt to inject. If None,
            DEFAULT_CHECKLIST_PROMPT is used.
        max_verifications: Maximum number of times the checklist is injected
            before the hook degrades (allows stop unconditionally). Must be >= 1.
            Default: 3.

    Returns:
        Async hook function with signature:
            async def hook(
                input_data: HookInput,
                tool_use_id: str | None,
                context: HookContext,
            ) -> SyncHookJSONOutput

    Raises:
        ValueError: If max_verifications < 1.

    Example::

        from claw_forge.agent.middleware.pre_completion import (
            pre_completion_checklist_hook,
        )

        stop_hook = pre_completion_checklist_hook(max_verifications=3)
        hooks = {
            "Stop": [HookMatcher(hooks=[stop_hook])],
        }
    """
    if max_verifications < 1:
        msg = f"max_verifications must be >= 1, got {max_verifications}"
        raise ValueError(msg)

    state = PreCompletionState(max_verifications=max_verifications)
    _prompt = checklist_prompt or DEFAULT_CHECKLIST_PROMPT

    async def hook(
        input_data: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> SyncHookJSONOutput:
        try:
            if state.should_verify():
                state.increment()
                return SyncHookJSONOutput(
                    continue_=True,
                    hookSpecificOutput={  # type: ignore[typeddict-item,misc]
                        "hookEventName": "Stop",
                        "additionalContext": _prompt,
                    },
                )
            # Exhausted — allow stop and reset for potential reuse
            logger.info(
                "[PreCompletionChecklist] max_verifications reached — allowing stop"
            )
            state.reset()
            return SyncHookJSONOutput(
                continue_=False,
                hookSpecificOutput={  # type: ignore[typeddict-item,misc]
                    "hookEventName": "Stop",
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PreCompletionChecklist] hook error (degrading): %s", exc)
            return SyncHookJSONOutput(
                continue_=False,
                hookSpecificOutput={  # type: ignore[typeddict-item,misc]
                    "hookEventName": "Stop",
                },
            )

    return hook
