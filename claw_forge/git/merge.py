"""Squash-merge feature branches to target branch."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any

from claw_forge.git.branching import branch_exists, current_branch, delete_branch, switch_branch
from claw_forge.git.repo import _run_git


def squash_merge(
    project_dir: Path,
    branch: str,
    target: str = "main",
) -> dict[str, Any]:
    if not branch_exists(project_dir, branch):
        return {"merged": False, "error": f"branch {branch!r} not found"}

    original_branch = current_branch(project_dir)
    try:
        switch_branch(project_dir, target)
        _run_git(["merge", "--squash", branch], project_dir)
        _run_git(["commit", "-m", f"merge: {branch} (squash)"], project_dir)
        short_hash = _run_git(
            ["rev-parse", "--short", "HEAD"], project_dir
        ).stdout.strip()
        delete_branch(project_dir, branch, force=True)
        return {"merged": True, "commit_hash": short_hash}
    except Exception as exc:
        # Abort merge if in progress, restore original branch
        with suppress(Exception):
            _run_git(["merge", "--abort"], project_dir)
        with suppress(Exception):
            switch_branch(project_dir, original_branch)
        return {"merged": False, "error": str(exc)}
