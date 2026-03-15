"""Git workspace tracking for claw-forge.

Public API wraps all git operations behind an asyncio.Lock for safe
concurrent access from the dispatcher. When ``enabled=False``, all
operations become no-ops.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from claw_forge.git.branching import (
    branch_exists,
    create_feature_branch,
    current_branch,
    delete_branch,
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
    "current_branch",
    "delete_branch",
    "ensure_gitignore",
    "init_or_detect",
    "make_branch_name",
    "make_slug",
    "squash_merge",
    "switch_branch",
    "task_history",
]


class GitOps:
    """Async-safe wrapper around git operations.

    All mutating operations are serialized behind an ``asyncio.Lock``
    to prevent concurrent branch switching from the parallel dispatcher.
    """

    def __init__(self, project_dir: Path, *, enabled: bool = True) -> None:
        self.project_dir = project_dir
        self.enabled = enabled
        self._lock = asyncio.Lock()

    async def init(self) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        async with self._lock:
            return await asyncio.to_thread(init_or_detect, self.project_dir)

    async def create_branch(
        self, task_id: str, slug: str, *, prefix: str = "feat"
    ) -> str | None:
        if not self.enabled:
            return None
        async with self._lock:
            return await asyncio.to_thread(
                create_feature_branch, self.project_dir, task_id, slug, prefix=prefix
            )

    async def checkpoint(
        self,
        *,
        message: str,
        task_id: str,
        plugin: str,
        phase: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        async with self._lock:
            return await asyncio.to_thread(
                commit_checkpoint,
                self.project_dir,
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
            )

    async def history(
        self, *, task_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        return await asyncio.to_thread(
            task_history, self.project_dir, task_id=task_id, limit=limit
        )
