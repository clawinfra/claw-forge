"""Agent middleware — composable hook factories for claw-forge agents."""
from __future__ import annotations

from claw_forge.agent.middleware.loop_detection import LoopContext, loop_detection_hook
from claw_forge.agent.middleware.pre_completion import (
    DEFAULT_CHECKLIST_PROMPT,
    PreCompletionState,
    pre_completion_checklist_hook,
)

__all__ = [
    "loop_detection_hook",
    "LoopContext",
    "DEFAULT_CHECKLIST_PROMPT",
    "PreCompletionState",
    "pre_completion_checklist_hook",
]
