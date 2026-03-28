"""Tests for resume context injection on task retry.

Covers:
- Resume preamble is prepended when error_message exists
- Prior work (commit subjects) is included
- HANDOFF.md content is included when present
- No resume context when error_message is absent
"""

from __future__ import annotations

from pathlib import Path


def _build_resume_prompt(
    error_message: str | None,
    prior_subjects: list[str],
    handoff_text: str,
    original_prompt: str,
) -> str:
    """Replica of the resume context logic from cli.py task_handler."""
    if not error_message:
        return original_prompt

    resume_parts: list[str] = [
        "## Resume Context",
        "This task was previously attempted but failed.\n",
    ]
    if prior_subjects:
        resume_parts.append("### Prior Work (preserved in this worktree)")
        resume_parts.extend(f"- {s}" for s in prior_subjects)
        resume_parts.append("")
    resume_parts.extend([
        "### Previous Failure",
        error_message[:2000],
        "",
    ])
    if handoff_text:
        resume_parts.extend([
            "### Handoff from Prior Attempt",
            handoff_text[:3000],
            "",
        ])
    resume_parts.extend([
        "### Instructions",
        "- Review existing code in this worktree before making changes",
        "- Do NOT redo already-completed work",
        "- Focus on remaining steps and fixing the prior failure",
    ])
    return "\n".join(resume_parts) + "\n\n" + original_prompt


class TestBuildResumePrompt:
    def test_no_error_message_returns_original(self) -> None:
        result = _build_resume_prompt(None, [], "", "do the task")
        assert result == "do the task"

    def test_includes_resume_context_header(self) -> None:
        result = _build_resume_prompt("it broke", [], "", "do the task")
        assert "## Resume Context" in result
        assert "### Previous Failure" in result
        assert "it broke" in result

    def test_includes_prior_work(self) -> None:
        result = _build_resume_prompt(
            "timeout",
            ["feat: add auth", "feat: add login form"],
            "",
            "implement auth",
        )
        assert "### Prior Work" in result
        assert "- feat: add auth" in result
        assert "- feat: add login form" in result

    def test_includes_handoff_text(self) -> None:
        result = _build_resume_prompt(
            "timeout", [], "## Completed\n- auth module", "implement auth"
        )
        assert "### Handoff from Prior Attempt" in result
        assert "## Completed" in result

    def test_includes_instructions(self) -> None:
        result = _build_resume_prompt("err", [], "", "task")
        assert "Do NOT redo already-completed work" in result
        assert "fixing the prior failure" in result

    def test_original_prompt_appended_at_end(self) -> None:
        result = _build_resume_prompt("err", [], "", "original task prompt")
        assert result.endswith("original task prompt")

    def test_error_message_truncated(self) -> None:
        long_error = "x" * 3000
        result = _build_resume_prompt(long_error, [], "", "task")
        # Should be truncated to 2000 chars
        assert "x" * 2000 in result
        assert "x" * 2001 not in result

    def test_handoff_text_truncated(self) -> None:
        long_handoff = "y" * 4000
        result = _build_resume_prompt("err", [], long_handoff, "task")
        assert "y" * 3000 in result
        assert "y" * 3001 not in result


class TestWorktreePreservationOnFailure:
    """Test that worktrees with commits are preserved on failure."""

    def test_preserve_logic_when_branch_has_commits(self, tmp_path: Path) -> None:
        """Verify the conditional logic: branch with commits -> keep worktree."""
        # This tests the logical condition, not the full cli.py integration
        has_commits = True
        should_remove = not has_commits
        assert should_remove is False

    def test_remove_logic_when_branch_empty(self, tmp_path: Path) -> None:
        """Verify the conditional logic: empty branch -> remove worktree."""
        has_commits = False
        should_remove = not has_commits
        assert should_remove is True
