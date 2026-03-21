"""Git workspace tracking for claw-forge.

Public API wraps git operations for safe concurrent access from the
dispatcher. Worktree-based methods (``create_worktree``, ``checkpoint``
with ``cwd``) are lock-free because each worktree has an independent
HEAD and index. Only ``merge()`` acquires the lock since it mutates
the shared main branch. When ``enabled=False``, all operations become
no-ops.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from claw_forge.git.branching import (
    branch_exists,
    create_feature_branch,
    create_worktree,
    current_branch,
    delete_branch,
    prune_worktrees,
    remove_worktree,
    switch_branch,
)
from claw_forge.git.commits import branch_commit_subjects, commit_checkpoint, task_history
from claw_forge.git.merge import squash_merge
from claw_forge.git.repo import ensure_gitignore, init_or_detect
from claw_forge.git.slug import make_branch_name, make_slug

__all__ = [
    "GitOps",
    "branch_commit_subjects",
    "branch_exists",
    "commit_checkpoint",
    "create_feature_branch",
    "create_worktree",
    "current_branch",
    "delete_branch",
    "ensure_gitignore",
    "init_or_detect",
    "make_branch_name",
    "make_slug",
    "prune_worktrees",
    "remove_worktree",
    "squash_merge",
    "switch_branch",
    "task_history",
]


class GitOps:
    """Async-safe wrapper around git operations.

    Worktree-based methods are lock-free — each worktree has its own
    HEAD and index.  Only ``merge()`` acquires the lock because it
    mutates the shared target branch.  ``create_branch()`` retains
    its lock for backward compatibility (shared-directory model).
    """

    def __init__(self, project_dir: Path, *, enabled: bool = True) -> None:
        self.project_dir = project_dir
        self.enabled = enabled
        self._lock = asyncio.Lock()

    async def init(self) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        async with self._lock:
            result = await asyncio.to_thread(init_or_detect, self.project_dir)
        pruned = await asyncio.to_thread(prune_worktrees, self.project_dir)
        if pruned:
            result["pruned_worktrees"] = pruned
        return result

    async def create_branch(
        self, task_id: str, slug: str, *, prefix: str = "feat"
    ) -> str | None:
        if not self.enabled:
            return None
        async with self._lock:
            return await asyncio.to_thread(
                create_feature_branch, self.project_dir, task_id, slug, prefix=prefix
            )

    async def create_worktree(
        self, task_id: str, slug: str, *, prefix: str = "feat"
    ) -> tuple[str, Path] | None:
        """Create an isolated worktree for a task — no lock needed."""
        if not self.enabled:
            return None
        return await asyncio.to_thread(
            create_worktree, self.project_dir, task_id, slug, prefix=prefix
        )

    async def remove_worktree(self, worktree_path: Path) -> None:
        """Remove a worktree — no lock needed."""
        if not self.enabled:
            return
        await asyncio.to_thread(remove_worktree, self.project_dir, worktree_path)

    async def checkpoint(
        self,
        *,
        message: str,
        task_id: str,
        plugin: str,
        phase: str,
        session_id: str,
        cwd: Path | None = None,
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        target_dir = cwd or self.project_dir
        return await asyncio.to_thread(
            commit_checkpoint,
            target_dir,
            message=message,
            task_id=task_id,
            plugin=plugin,
            phase=phase,
            session_id=session_id,
        )

    async def merge(
        self,
        branch: str,
        target: str = "main",
        *,
        title: str | None = None,
        steps: list[str] | None = None,
        task_id: str | None = None,
        session_id: str | None = None,
        worktree_path: Path | None = None,
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        async with self._lock:
            return await asyncio.to_thread(
                squash_merge,
                self.project_dir,
                branch,
                target,
                title=title,
                steps=steps,
                task_id=task_id,
                session_id=session_id,
                worktree_path=worktree_path,
            )

    async def history(
        self, *, task_id: str | None = None, limit: int = 20, cwd: Path | None = None
    ) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        target_dir = cwd or self.project_dir
        return await asyncio.to_thread(
            task_history, target_dir, task_id=task_id, limit=limit
        )
