"""Data models for GitHub integration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GitHubContext:
    """Context passed through the claw-forge pipeline when in --github-mode."""

    owner: str
    repo: str
    issue_number: int
    token: str
    branch_name: str  # e.g., "feat/github-123"


@dataclass
class IssueSpec:
    """Parsed GitHub issue, converted to claw-forge spec format."""

    title: str
    description: str
    comments: list[str]
    author: str
    number: int
    labels: list[str] = field(default_factory=list)

    def to_xml(self) -> str:
        """Convert issue to a minimal app_spec XML format.

        Generates a minimal XML spec with the issue title as project name
        and description as the feature description.
        """
        # Escape special XML characters in user-supplied text
        def _escape(text: str) -> str:
            return (
                text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
            )

        title_esc = _escape(self.title)
        desc_esc = _escape(self.description or "No description provided.")

        return f"""\
<project_specification mode="greenfield">
  <project_name>{title_esc}</project_name>

  <overview>
    {desc_esc}
  </overview>

  <core_features>
    <category name="GitHub Issue #{self.number}">
      {desc_esc}
    </category>
  </core_features>

</project_specification>
"""

    def to_markdown_spec(self) -> str:
        """Convert issue to plain text spec format (alternative to XML).

        Falls back to markdown if XML parsing fails.
        """
        lines = [
            f"Project: {self.title}",
            "",
            self.description or "No description provided.",
            "",
            "## Context",
            f"Source: GitHub issue #{self.number}",
            f"Author: {self.author}",
        ]

        if self.labels:
            lines.append(f"Labels: {', '.join(self.labels)}")

        # Include comments if they add useful context
        if self.comments:
            lines.extend(
                [
                    "",
                    "## Issue Comments",
                    *self.comments,
                ]
            )

        return "\n".join(lines)
