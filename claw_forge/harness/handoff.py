"""Standalone HANDOFF.md schema for structured agent context handoffs.

This module provides the ``HandoffArtifact`` dataclass — the canonical
schema for carrying state across context resets in long-running builder
agent sessions.

The handoff artifact is the bridge between agent sessions.  It must
contain enough information for the next agent to pick up work cleanly
without having to rediscover state.

Schema modelled on Anthropic's harness design recommendations:
- What was completed (with evidence like commit hashes)
- Current state of the codebase
- Ordered next steps
- Decisions already made (to avoid revisiting)
- Quality bar (current score, what needs to improve)

Usage::

    from claw_forge.harness.handoff import HandoffArtifact

    # Create and serialise
    artifact = HandoffArtifact(
        completed=["feat: auth module (abc123)"],
        next_steps=["Implement rate limiting"],
        quality_bar="6.5/10 — needs error handling",
    )
    artifact.save("HANDOFF.md")

    # Load and parse
    loaded = HandoffArtifact.load("HANDOFF.md")
    assert loaded.completed == ["feat: auth module (abc123)"]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Section headers used in the HANDOFF.md schema
_SECTION_HEADERS = {
    "## Completed": "completed",
    "## State": "state",
    "## Next Steps": "next_steps",
    "## Decisions Made": "decisions_made",
    "## Quality Bar": "quality_bar",
}

# Placeholder values that should be ignored when parsing
_PLACEHOLDER_VALUES = frozenset(
    {
        "(none yet)",
        "(initial state)",
        "(review plan and begin implementation)",
        "(no decisions recorded yet)",
    }
)

# Pattern for stripping bullet/number markers
_BULLET_RE = re.compile(r"^[-*]\s*")
_NUMBER_RE = re.compile(r"^\d+\.\s*")


@dataclass
class HandoffArtifact:
    """Structured artifact that carries state across context resets.

    This is the bridge between agent sessions — it must contain enough
    information for the next agent to pick up work cleanly without
    having to rediscover state.

    Attributes
    ----------
    completed:
        Items that have been completed, with evidence (e.g. commit hashes).
    state:
        Current state of the codebase / workspace.
    next_steps:
        Ordered list of what to do next.
    decisions_made:
        Decisions already made (to avoid revisiting).
    quality_bar:
        Current quality assessment (score, what needs improvement).
    iteration_number:
        Which iteration produced this artifact.
    total_tool_calls:
        Cumulative tool calls across all iterations.
    """

    completed: list[str] = field(default_factory=list)
    state: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    decisions_made: list[str] = field(default_factory=list)
    quality_bar: str = ""
    iteration_number: int = 0
    total_tool_calls: int = 0

    def to_markdown(self) -> str:
        """Render the handoff artifact as a HANDOFF.md file."""
        sections: list[str] = ["# HANDOFF.md — Builder Context Reset\n"]

        sections.append(f"**Iteration:** {self.iteration_number}")
        sections.append(f"**Total Tool Calls:** {self.total_tool_calls}\n")

        sections.append("## Completed")
        if self.completed:
            for item in self.completed:
                sections.append(f"- {item}")
        else:
            sections.append("- (none yet)")

        sections.append("\n## State")
        if self.state:
            for item in self.state:
                sections.append(f"- {item}")
        else:
            sections.append("- (initial state)")

        sections.append("\n## Next Steps")
        if self.next_steps:
            for i, step in enumerate(self.next_steps, 1):
                sections.append(f"{i}. {step}")
        else:
            sections.append("1. (review plan and begin implementation)")

        sections.append("\n## Decisions Made")
        if self.decisions_made:
            for item in self.decisions_made:
                sections.append(f"- {item}")
        else:
            sections.append("- (no decisions recorded yet)")

        sections.append("\n## Quality Bar")
        sections.append(self.quality_bar or "- Not yet evaluated")

        return "\n".join(sections) + "\n"

    @classmethod
    def from_markdown(cls, text: str) -> HandoffArtifact:
        """Parse a HANDOFF.md file back into a HandoffArtifact.

        This is a best-effort parser — it looks for the known section
        headers and extracts bullet items under each.  Handles
        malformed input gracefully (returns empty fields).

        Parameters
        ----------
        text:
            The raw markdown text of a HANDOFF.md file.
        """
        artifact = cls()

        current_section: str | None = None

        for line in text.splitlines():
            stripped = line.strip()

            # Parse iteration metadata: **Iteration:** 2
            if stripped.startswith("**Iteration:**"):
                try:
                    val = stripped.replace("**Iteration:**", "").strip()
                    artifact.iteration_number = int(val)
                except (ValueError, IndexError):
                    pass
                continue

            # Parse tool call metadata: **Total Tool Calls:** 160
            if stripped.startswith("**Total Tool Calls:**"):
                try:
                    val = stripped.replace("**Total Tool Calls:**", "").strip()
                    artifact.total_tool_calls = int(val)
                except (ValueError, IndexError):
                    pass
                continue

            # Detect section headers
            matched_header = False
            for header, field_name in _SECTION_HEADERS.items():
                if stripped == header:
                    current_section = field_name
                    matched_header = True
                    break

            if matched_header or not current_section or not stripped:
                continue

            # Quality bar: preserve raw text (may contain "7/10 — solid")
            if current_section == "quality_bar":
                content = stripped.lstrip("- ").strip()
                if content and content != "Not yet evaluated":
                    artifact.quality_bar = (artifact.quality_bar + " " + content).strip()
            else:
                # Strip bullet/number markers for list sections
                content = _BULLET_RE.sub("", stripped)
                content = _NUMBER_RE.sub("", content).strip()
                if content and content not in _PLACEHOLDER_VALUES:
                    getattr(artifact, current_section).append(content)

        return artifact

    def save(self, path: str | Path) -> Path:
        """Write the handoff artifact to a file.

        Creates parent directories if needed.

        Parameters
        ----------
        path:
            File path to write to.

        Returns
        -------
        Path:
            The resolved path that was written.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_markdown(), encoding="utf-8")
        return p

    @classmethod
    def load(cls, path: str | Path) -> HandoffArtifact:
        """Load a HandoffArtifact from a HANDOFF.md file.

        Parameters
        ----------
        path:
            File path to read from.

        Returns
        -------
        HandoffArtifact:
            The parsed artifact.

        Raises
        ------
        FileNotFoundError:
            If the file does not exist.
        """
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        return cls.from_markdown(text)
