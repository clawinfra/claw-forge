"""Loop detection middleware for claw-forge agents.

Tracks per-file edit counts via PostToolUse hooks and injects a
"reconsider your approach" prompt when an agent appears stuck.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

# Same try/except guard pattern as hooks.py — SDK always installed in prod
try:
    from claude_agent_sdk.types import HookContext, HookInput, SyncHookJSONOutput
except ImportError:  # pragma: no cover
    HookContext = Any  # type: ignore[assignment,misc]
    HookInput = Any  # type: ignore[assignment,misc]
    SyncHookJSONOutput = Any  # type: ignore[assignment,misc]

_logger = logging.getLogger(__name__)

# Tool names that constitute a "file edit" for loop-detection purposes.
_EDIT_TOOLS: frozenset[str] = frozenset({"Edit", "Write", "MultiEdit"})

# Threshold raised automatically when hashline edit mode is active.
_HASHLINE_THRESHOLD_BOOST: int = 3  # base 5 → 8


@dataclass
class LoopContext:
    """Mutable state shared across all PostToolUse hook invocations for one agent run.

    Fields:
        edit_counts: Maps absolute file path (str) → number of edit-tool
            invocations targeting that path during this agent run.
        threshold: Maximum allowed edits to a single file before a warning
            is injected. Set at construction time; never mutated after that.
        injections: Running count of how many warning injections have been
            emitted so far. Informational — useful for tests and reporting.
    """

    edit_counts: dict[str, int] = field(default_factory=dict)
    threshold: int = 5
    injections: int = 0


def loop_detection_hook(
    threshold: int = 5,
    edit_mode: str = "str_replace",
) -> tuple[Callable[..., Any], LoopContext]:
    """Create a PostToolUse hook that detects and breaks agent doom loops.

    Tracks per-file edit counts. When an agent edits the same file more than
    ``threshold`` times in a single run, injects a context message prompting
    it to reconsider its approach.

    When ``edit_mode`` is ``"hashline"``, the effective threshold is raised by
    ``_HASHLINE_THRESHOLD_BOOST`` (default +3) because hashline editing
    naturally produces more edit calls for the same logical change.

    If ``threshold`` is 0, the hook is a no-op (loop detection disabled).
    Exceptions inside the hook are caught and logged; they never propagate.

    Args:
        threshold: Maximum edits to a single file before injecting a warning.
            Default 5. Set to 0 to disable. CLI flag: --loop-detect-threshold.
        edit_mode: Current edit mode ("str_replace" or "hashline"). Controls
            automatic threshold adjustment.

    Returns:
        A 2-tuple of:
        - hook_fn: Async callable compatible with HookMatcher hooks list.
        - ctx: The LoopContext instance shared across all invocations of hook_fn.
          Callers can inspect ctx.edit_counts and ctx.injections after the run.

    Example::

        hook_fn, ctx = loop_detection_hook(threshold=5)
        hooks = {
            "PostToolUse": [HookMatcher(hooks=[hook_fn])],
        }
        # After run: ctx.injections tells you how many warnings were injected.
    """
    effective_threshold = threshold
    if threshold > 0 and edit_mode == "hashline":
        effective_threshold = threshold + _HASHLINE_THRESHOLD_BOOST
        _logger.debug(
            "[LoopDetection] hashline mode active — threshold raised %d → %d",
            threshold,
            effective_threshold,
        )

    ctx = LoopContext(threshold=effective_threshold)

    async def _hook(
        input_data: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> SyncHookJSONOutput:
        """Inner async hook function returned by loop_detection_hook()."""
        try:
            # 1. Disabled check — fast path
            if ctx.threshold == 0:
                return _noop_output()

            # 2. Parse input_data safely
            if isinstance(input_data, dict):
                data: dict[str, Any] = cast(dict[str, Any], input_data)
            else:
                # Non-dict input: nothing to track
                return _noop_output()

            # 3. Check if this is an edit-type tool
            tool_name = str(data.get("tool_name", data.get("tool", "")))
            if tool_name not in _EDIT_TOOLS:
                return _noop_output()

            # 4. Extract file path
            tool_input = data.get("input", data.get("tool_input", {}))
            if not isinstance(tool_input, dict):
                return _noop_output()

            file_path = str(
                tool_input.get(
                    "file_path",
                    tool_input.get("path", tool_input.get("target", "")),
                )
            )
            if not file_path:
                return _noop_output()

            # 5. Increment counter
            ctx.edit_counts[file_path] = ctx.edit_counts.get(file_path, 0) + 1
            count = ctx.edit_counts[file_path]

            # 6. Threshold check
            if count < ctx.threshold:
                return _noop_output()

            # 7. Inject warning
            ctx.injections += 1
            warning = _build_warning(file_path, count, ctx.threshold)
            _logger.info(
                "[LoopDetection] %s edits to %s — injecting reconsider prompt",
                count,
                file_path,
            )

            return SyncHookJSONOutput(
                hookSpecificOutput={
                    "hookEventName": "PostToolUse",
                    "additionalContext": warning,
                }
            )
        except Exception as exc:  # noqa: BLE001
            # Graceful degrade: never crash the agent
            _logger.warning("[LoopDetection] Hook error (continuing): %s", exc)
            return _noop_output()

    return _hook, ctx


def _noop_output() -> SyncHookJSONOutput:
    """Return an empty PostToolUse output (no-op injection)."""
    return SyncHookJSONOutput(
        hookSpecificOutput={
            "hookEventName": "PostToolUse",
            "additionalContext": "",
        }
    )


def _build_warning(file_path: str, count: int, threshold: int) -> str:
    """Build the reconsider-approach warning message injected into agent context.

    Args:
        file_path: Path to the file being repeatedly edited.
        count: Current edit count for this file.
        threshold: The threshold that was crossed.

    Returns:
        Multi-line string ready for additionalContext injection.
    """
    return (
        f"⚠️  Loop detection: you have edited '{file_path}' {count} times "
        f"(threshold: {threshold}).\n"
        "Consider stepping back and reconsidering your approach:\n"
        "  • Re-read the original spec and requirements\n"
        "  • Check your test output carefully — what is the EXACT error?\n"
        "  • Try a fundamentally different strategy rather than incremental tweaks\n"
        "  • Consider if there's a simpler approach you've overlooked\n"
        "  • Read any related files you may have missed\n"
        "If you're confident the current approach is correct, continue — "
        "but make sure each edit is meaningfully different from the last."
    )
