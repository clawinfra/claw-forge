"""Thinking configuration presets for different task types.

Provides ready-made ThinkingConfig instances and a helper that maps task
types to the appropriate config. Use with ``run_agent(thinking=...)`` or
pass directly to ``ClaudeAgentOptions``.

Usage::

    from claw_forge.agent.thinking import thinking_for_task

    # Deep thinking for architecture decisions
    options = ClaudeAgentOptions(
        thinking=thinking_for_task("architecture"),
        ...
    )

    # No thinking overhead for fast monitoring tasks
    options = ClaudeAgentOptions(
        thinking=thinking_for_task("monitoring"),
        ...
    )
"""
from __future__ import annotations

from claude_agent_sdk import ThinkingConfigAdaptive, ThinkingConfigDisabled, ThinkingConfigEnabled

# ThinkingConfig types are TypedDicts (dicts), constructed via dict literal syntax.

# For complex architectural decisions — maximise reasoning depth
DEEP_THINKING: ThinkingConfigEnabled = {"type": "enabled", "budget_tokens": 20_000}

# For standard coding tasks — let the model decide whether to think
ADAPTIVE_THINKING: ThinkingConfigAdaptive = {"type": "adaptive"}

# For simple / fast tasks — skip thinking overhead entirely
NO_THINKING: ThinkingConfigDisabled = {"type": "disabled"}

# Union type for convenience
ThinkingConfig = ThinkingConfigEnabled | ThinkingConfigAdaptive | ThinkingConfigDisabled

# ── Task-type mapping ─────────────────────────────────────────────────────────

_TASK_MAP: dict[str, ThinkingConfig] = {
    "planning": DEEP_THINKING,
    "architecture": DEEP_THINKING,
    "review": ADAPTIVE_THINKING,
    "coding": ADAPTIVE_THINKING,
    "testing": NO_THINKING,
    "monitoring": NO_THINKING,
}


def thinking_for_task(task_type: str) -> ThinkingConfig:
    """Return the appropriate ThinkingConfig for the given task type.

    Args:
        task_type: One of ``"planning"``, ``"architecture"``, ``"review"``,
            ``"coding"``, ``"testing"``, ``"monitoring"``. Falls back to
            ``ADAPTIVE_THINKING`` for unknown types.

    Returns:
        A ThinkingConfig dict suitable for passing to ``ClaudeAgentOptions``.

    Examples::

        thinking_for_task("architecture")  # → DEEP_THINKING (20k tokens)
        thinking_for_task("testing")       # → NO_THINKING
        thinking_for_task("coding")        # → ADAPTIVE_THINKING
        thinking_for_task("unknown")       # → ADAPTIVE_THINKING (fallback)
    """
    return _TASK_MAP.get(task_type, ADAPTIVE_THINKING)
