"""Context reset support for long-running builder agents.

Instead of relying on compaction (which preserves a degraded context and
can trigger "context anxiety"), this module provides a clean context reset
mechanism.  After N tool calls, the builder saves a structured HANDOFF.md
artifact and a fresh builder is spawned with it as context.

Key insight from Anthropic's research: compaction keeps the agent in a
degraded context where it may prematurely wrap up work.  A full reset
gives a clean slate, at the cost of the handoff artifact needing enough
state to pick up cleanly.
"""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path
from typing import Any

# Import HandoffArtifact from the standalone module.
# It was originally defined here; the standalone module is now canonical.
from claw_forge.harness.handoff import HandoffArtifact

logger = logging.getLogger(__name__)

# Re-export for backwards compatibility
__all__ = ["ContextResetManager", "HandoffArtifact", "DEFAULT_TOOL_CALL_THRESHOLD"]

# Default threshold for tool calls before triggering a context reset.
DEFAULT_TOOL_CALL_THRESHOLD = 80


class ContextResetManager:
    """Manages context resets for a builder agent session.

    Tracks tool call count and triggers a context reset when the
    threshold is reached.  The reset produces a HandoffArtifact
    that the next builder session uses as its initial context.

    Parameters
    ----------
    project_dir:
        Root directory of the project being built.
    threshold:
        Number of tool calls before triggering a reset.
    """

    def __init__(
        self,
        project_dir: str | Path,
        threshold: int = DEFAULT_TOOL_CALL_THRESHOLD,
    ) -> None:
        self._project_dir = Path(project_dir)
        self._threshold = max(10, threshold)  # minimum 10 to avoid thrashing
        self._tool_call_count = 0
        self._total_tool_calls = 0
        self._iteration = 0
        self._current_handoff: HandoffArtifact | None = None

    @property
    def tool_call_count(self) -> int:
        """Tool calls in the current iteration."""
        return self._tool_call_count

    @property
    def total_tool_calls(self) -> int:
        """Total tool calls across all iterations."""
        return self._total_tool_calls

    @property
    def iteration(self) -> int:
        """Current iteration number (0-indexed)."""
        return self._iteration

    @property
    def threshold(self) -> int:
        """Tool call threshold for triggering a reset."""
        return self._threshold

    @property
    def handoff_path(self) -> Path:
        """Path to the HANDOFF.md file in the project directory."""
        return self._project_dir / "HANDOFF.md"

    def record_tool_call(self) -> bool:
        """Record a tool call and return True if a reset is needed.

        Call this after each tool call in the builder agent loop.
        When True is returned, the caller should:
        1. Call ``save_handoff()`` with the current state
        2. Spawn a fresh builder with the handoff as context
        3. Stop the current builder session
        """
        self._tool_call_count += 1
        self._total_tool_calls += 1
        return self._tool_call_count >= self._threshold

    def save_handoff(self, handoff: HandoffArtifact) -> Path:
        """Save a handoff artifact to HANDOFF.md.

        Updates the artifact with iteration metadata and writes it
        to the project directory.  Returns the path to the written file.
        """
        self._iteration += 1
        handoff.iteration_number = self._iteration
        handoff.total_tool_calls = self._total_tool_calls
        self._current_handoff = handoff

        path = self.handoff_path
        path.write_text(handoff.to_markdown(), encoding="utf-8")
        logger.info(
            "Saved HANDOFF.md (iteration %d, %d tool calls)",
            self._iteration,
            self._total_tool_calls,
        )

        # Reset per-iteration counter
        self._tool_call_count = 0

        return path

    def load_handoff(self) -> HandoffArtifact | None:
        """Load the existing HANDOFF.md if it exists.

        Returns None if no handoff file is found.  The loaded artifact
        is also cached in ``_current_handoff``.
        """
        if not self.handoff_path.exists():
            return None

        text = self.handoff_path.read_text(encoding="utf-8")
        artifact = HandoffArtifact.from_markdown(text)
        self._current_handoff = artifact
        self._iteration = artifact.iteration_number
        self._total_tool_calls = artifact.total_tool_calls
        logger.info(
            "Loaded HANDOFF.md (iteration %d, %d prior tool calls)",
            self._iteration,
            self._total_tool_calls,
        )
        return artifact

    def build_reset_prompt(self, handoff: HandoffArtifact) -> str:
        """Build the prompt for a fresh builder session after a reset.

        The prompt includes the full handoff artifact and clear
        instructions to continue from where the previous builder
        left off.  This is the "clean slate" approach — the new
        builder gets no conversation history, only the structured
        handoff.
        """
        return textwrap.dedent(f"""\
            You are a builder agent resuming work after a context reset.

            The previous builder completed {len(handoff.completed)} items
            over {handoff.total_tool_calls} tool calls across
            {handoff.iteration_number} iteration(s).

            Read the HANDOFF.md file in the project root for full context,
            then continue with the next steps listed there.

            ## Key Rules
            - Do NOT revisit decisions already made (listed in HANDOFF.md)
            - Do NOT re-implement completed items
            - Start with the first item in "Next Steps"
            - Maintain the quality bar described in HANDOFF.md
            - Commit work incrementally with descriptive messages

            ## HANDOFF.md Content
            {handoff.to_markdown()}
        """)

    def get_status(self) -> dict[str, Any]:
        """Return current context reset status as a JSON-serializable dict."""
        return {
            "iteration": self._iteration,
            "tool_calls_current": self._tool_call_count,
            "tool_calls_total": self._total_tool_calls,
            "threshold": self._threshold,
            "needs_reset": self._tool_call_count >= self._threshold,
            "handoff_exists": self.handoff_path.exists(),
        }
