"""Feature branch lifecycle — create, switch, delete, worktrees."""

from __future__ import annotations

import shutil
from contextlib import suppress
from pathlib import Path

from claw_forge.git.repo import _run_git


def current_branch(project_dir: Path) -> str:
    result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], project_dir)
    return result.stdout.strip()


def branch_exists(project_dir: Path, name: str) -> bool:
    try:
        _run_git(["rev-parse", "--verify", f"refs/heads/{name}"], project_dir)
        return True
    except Exception:
        return False


def create_feature_branch(
    project_dir: Path,
    task_id: str,
    slug: str,
    *,
    prefix: str = "feat",
) -> str:
    branch_name = f"{prefix}/{slug}"
    if branch_exists(project_dir, branch_name):
        switch_branch(project_dir, branch_name)
    else:
        _run_git(["checkout", "-b", branch_name], project_dir)
    return branch_name


def switch_branch(project_dir: Path, name: str) -> None:
    _run_git(["checkout", name], project_dir)


def delete_branch(project_dir: Path, name: str, *, force: bool = False) -> None:
    if not branch_exists(project_dir, name):
        return
    flag = "-D" if force else "-d"
    with suppress(Exception):
        _run_git(["branch", flag, name], project_dir)


# ── Worktree operations ──────────────────────────────────────────────────────


def create_worktree(
    project_dir: Path,
    task_id: str,
    slug: str,
    *,
    prefix: str = "feat",
) -> tuple[str, Path]:
    """Create an isolated git worktree for a task.

    Each worktree gets its own working directory and HEAD, allowing
    concurrent agents to write files without interfering with each other.

    Returns ``(branch_name, worktree_path)``.
    """
    branch_name = f"{prefix}/{slug}"
    worktree_path = project_dir / ".claw-forge" / "worktrees" / slug
    # Remove stale directory from a prior crashed run
    if worktree_path.exists():
        shutil.rmtree(worktree_path)
        # Clean bookkeeping so git doesn't think the worktree still exists
        with suppress(Exception):
            _run_git(["worktree", "prune"], project_dir)

    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    if branch_exists(project_dir, branch_name):
        _run_git(
            ["worktree", "add", str(worktree_path), branch_name],
            project_dir,
        )
    else:
        _run_git(
            ["worktree", "add", "-b", branch_name, str(worktree_path)],
            project_dir,
        )
    return branch_name, worktree_path


def remove_worktree(project_dir: Path, worktree_path: Path) -> None:
    """Remove a worktree directory and its git bookkeeping."""
    with suppress(Exception):
        _run_git(
            ["worktree", "remove", "--force", str(worktree_path)],
            project_dir,
        )


def prune_worktrees(project_dir: Path) -> int:
    """Remove all worktrees under ``.claw-forge/worktrees/`` and prune bookkeeping.

    Called at startup to clean up stale worktrees from crashed runs.
    Returns the number of worktree directories removed.
    """
    worktrees_dir = project_dir / ".claw-forge" / "worktrees"
    if not worktrees_dir.is_dir():
        return 0
    count = 0
    for child in list(worktrees_dir.iterdir()):
        if child.is_dir():
            with suppress(Exception):
                _run_git(
                    ["worktree", "remove", "--force", str(child)],
                    project_dir,
                )
            # Fallback: if git worktree remove failed, force-delete
            if child.exists():
                shutil.rmtree(child, ignore_errors=True)
            count += 1
    with suppress(Exception):
        _run_git(["worktree", "prune"], project_dir)
    return count
