"""Squash-merge feature branches to target branch."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any

from claw_forge.git.branching import (
    branch_exists,
    current_branch,
    delete_branch,
    remove_worktree,
    switch_branch,
)
from claw_forge.git.commits import branch_commit_subjects
from claw_forge.git.repo import _run_git


def _build_merge_message(
    branch: str,
    *,
    title: str | None = None,
    steps: list[str] | None = None,
    phases: list[str] | None = None,
    task_id: str | None = None,
    session_id: str | None = None,
) -> str:
    """Build a semantic squash-merge commit message."""
    if not title:
        return f"merge: {branch} (squash)"

    lines: list[str] = [title, ""]

    if steps:
        lines.append("Completed Steps:")
        for s in steps:
            lines.append(f"  - [x] {s}")
        lines.append("")

    if phases:
        lines.append("Completed Phases:")
        for p in phases:
            lines.append(f"  - {p}")
        lines.append("")

    if task_id:
        lines.append(f"Task-ID: {task_id}")
    if session_id:
        lines.append(f"Session: {session_id}")

    return "\n".join(lines)


def squash_merge(
    project_dir: Path,
    branch: str,
    target: str = "main",
    *,
    title: str | None = None,
    steps: list[str] | None = None,
    task_id: str | None = None,
    session_id: str | None = None,
    worktree_path: Path | None = None,
) -> dict[str, Any]:
    if not branch_exists(project_dir, branch):
        return {"merged": False, "error": f"branch {branch!r} not found"}

    # Collect branch commit subjects before switching branches
    phases = branch_commit_subjects(project_dir, branch, target)

    original_branch = current_branch(project_dir)
    try:
        switch_branch(project_dir, target)
        _run_git(["merge", "--squash", branch], project_dir)
        commit_msg = _build_merge_message(
            branch,
            title=title,
            steps=steps,
            phases=phases,
            task_id=task_id,
            session_id=session_id,
        )
        _run_git(["commit", "--no-verify", "-m", commit_msg], project_dir)
        short_hash = _run_git(
            ["rev-parse", "--short", "HEAD"], project_dir
        ).stdout.strip()
        if worktree_path is not None:
            remove_worktree(project_dir, worktree_path)
        delete_branch(project_dir, branch, force=True)
        return {"merged": True, "commit_hash": short_hash}
    except Exception as exc:
        # Clean up staged changes from the failed squash merge.
        # ``git merge --abort`` only works for real merge commits; a
        # squash merge stages changes without creating a merge state,
        # so we must ``reset --hard`` to restore the working tree.
        with suppress(Exception):
            _run_git(["merge", "--abort"], project_dir)
        with suppress(Exception):
            _run_git(["reset", "--hard", "HEAD"], project_dir)
        with suppress(Exception):
            switch_branch(project_dir, original_branch)
        return {"merged": False, "error": str(exc)}
