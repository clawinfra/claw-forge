"""Feature branch lifecycle — create, switch, delete, worktrees."""

from __future__ import annotations

import logging
import shutil
from contextlib import suppress
from pathlib import Path

from claw_forge.git.repo import _run_git

logger = logging.getLogger(__name__)


def current_branch(project_dir: Path) -> str:
    result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], project_dir)
    return result.stdout.strip()


def branch_exists(project_dir: Path, name: str) -> bool:
    try:
        _run_git(["rev-parse", "--verify", f"refs/heads/{name}"], project_dir)
        return True
    except Exception:
        return False


def branch_has_commits_ahead(project_dir: Path, branch: str, base: str = "main") -> bool:
    """Return True if *branch* has at least one commit not reachable from *base*."""
    try:
        result = _run_git(
            ["rev-list", "--count", f"{base}..{branch}"], project_dir
        )
        return int(result.stdout.strip()) > 0
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
    base_branch: str = "main",
) -> tuple[str, Path]:
    """Create (or resume) an isolated git worktree for a task.

    On a fresh run a new worktree + branch are created.

    On **resume after interrupt**: if the branch already has commits ahead of
    *base_branch*, the existing worktree directory is reused rather than
    nuked — preserving any partial work the agent committed before the
    process was killed.  If the directory is missing but the branch exists
    (worktree pruned by OS), the worktree is re-linked to the existing
    branch so the agent can continue from its last commit.

    Returns ``(branch_name, worktree_path)``.
    """
    branch_name = f"{prefix}/{slug}"
    worktree_path = project_dir / ".claw-forge" / "worktrees" / slug

    # ── Resume path: branch has partial commits → preserve them ─────────────
    if branch_exists(project_dir, branch_name) and branch_has_commits_ahead(
        project_dir, branch_name, base_branch
    ):
        if worktree_path.exists():
            # Worktree still on disk — reuse as-is.
            logger.info(
                "Resuming worktree %s (branch %s has partial commits)",
                worktree_path,
                branch_name,
            )
            return branch_name, worktree_path
        # Branch exists but worktree dir was pruned — re-link it.
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        with suppress(Exception):
            _run_git(["worktree", "prune"], project_dir)
        _run_git(
            ["worktree", "add", str(worktree_path), branch_name],
            project_dir,
        )
        logger.info(
            "Re-linked worktree %s to existing branch %s",
            worktree_path,
            branch_name,
        )
        return branch_name, worktree_path

    # ── Fresh path: remove stale empty branch/directory and start clean ──────
    if worktree_path.exists():
        with suppress(Exception):
            _run_git(
                ["worktree", "remove", "--force", str(worktree_path)],
                project_dir,
            )
        if worktree_path.exists():
            shutil.rmtree(worktree_path)
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


def merge_orphaned_worktrees(
    project_dir: Path,
    *,
    prefix: str = "feat",
    target: str = "main",
) -> list[str]:
    """Scan for orphaned worktree branches with commits and squash-merge them.

    Called at startup (before orphan task reset) so that any work a killed
    agent committed to a feature branch is not lost on resume.

    Returns a list of branch names that were merged.
    """
    from claw_forge.git.merge import squash_merge  # local import to avoid cycles

    worktrees_dir = project_dir / ".claw-forge" / "worktrees"
    merged: list[str] = []
    if not worktrees_dir.is_dir():
        return merged

    for child in list(worktrees_dir.iterdir()):
        if not child.is_dir():
            continue
        slug = child.name
        branch_name = f"{prefix}/{slug}"
        if not branch_exists(project_dir, branch_name):
            continue
        if not branch_has_commits_ahead(project_dir, branch_name, target):
            # Empty branch — nothing to salvage.
            continue
        logger.info(
            "Orphaned worktree branch %s has commits — salvage-merging to %s",
            branch_name,
            target,
        )
        result = squash_merge(
            project_dir,
            branch_name,
            target,
            title=f"salvage: {branch_name} (recovered after interrupt)",
            worktree_path=child,
        )
        if result.get("merged"):
            logger.info(
                "Salvage-merged %s → %s (%s)",
                branch_name,
                target,
                result.get("commit_hash", ""),
            )
            merged.append(branch_name)
        else:
            logger.warning(
                "Salvage-merge failed for %s: %s",
                branch_name,
                result.get("error", "unknown"),
            )

    return merged


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
