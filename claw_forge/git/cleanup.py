"""Smart-mode worktree cleanup at ``claw-forge run`` startup.

When ``git.cleanup_orphan_worktrees: smart`` is set in ``claw-forge.yaml``,
the startup hook walks every directory under ``.claw-forge/worktrees/`` and
decides — based on the corresponding task's state in the DB — whether to
preserve, salvage, or remove it.  This bridges the gap left by the legacy
gate (``orphans_reset > 0``), which only fires for tasks killed mid-run and
ignores residue from terminally-failed tasks and from ``completed`` tasks
whose squash-merge itself failed (the v0.5.35 bug class).

Decision matrix (``decide_action``):

================  ============  ===============================================
task.status       has_commits   action      rationale
================  ============  ===============================================
``pending``       True          preserve    resume substrate for prefer_resumable
``pending``       False         remove      empty branch; nothing to keep
``running``       any           preserve    handled by orphans_reset path
``failed``        True          salvage     terminal — no auto-retry across runs
``failed``        False         remove      empty branch; nothing to keep
``completed``     True          salvage     squash failed previously (v0.5.35)
``completed``     False         remove      bookkeeping; merge already happened
no matching task  True          salvage     orphan from prior session
no matching task  False         remove      no value, no owner
================  ============  ===============================================

Conflicts during salvage preserve the worktree + branch and surface a
report to the user.  When ``git.llm_conflict_proposals: true`` is also set,
``draft_conflict_proposal`` is invoked to write a ``CONFLICT_PROPOSAL.md``
inside the preserved worktree the user can read, edit, and apply.
"""

from __future__ import annotations

import shutil
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from claw_forge.git.branching import (
    branch_exists,
    branch_has_commits_ahead,
)
from claw_forge.git.merge import squash_merge
from claw_forge.git.repo import _run_git
from claw_forge.git.slug import make_branch_name

Action = Literal["preserve", "salvage", "remove"]


@dataclass
class CleanupOutcome:
    slug: str
    branch: str
    action: Action
    task_status: str | None
    success: bool = False
    commit_hash: str | None = None
    error: str | None = None
    proposal_path: str | None = None
    conflicts: list[str] = field(default_factory=list)


class ConflictAdvisor(Protocol):
    """Pluggable hook for drafting CONFLICT_PROPOSAL.md on salvage failure.

    Kept as a Protocol so ``cleanup.py`` doesn't import the agent runner
    transitively — callers wire in ``draft_conflict_proposal`` from
    ``conflict_advisor.py`` only when the config flag is on.
    """

    def __call__(
        self,
        project_dir: Path,
        worktree_path: Path,
        branch: str,
        target: str,
        task: dict[str, Any] | None,
    ) -> Path | None:
        ...


def decide_action(task_status: str | None, has_commits: bool) -> Action:
    """Pick preserve/salvage/remove based on task state and committed work.

    No external dependencies — pure logic — so it's trivially unit-testable.
    """
    if not has_commits:
        return "remove"
    if task_status in ("pending", "running"):
        # Pending: keep as resume substrate for prefer_resumable.
        # Running: orphans_reset will reset it shortly; let that path own it.
        return "preserve"
    # ``failed``, ``completed``, or no matching task → salvage.
    return "salvage"


def _build_slug_to_task_map(
    tasks: list[dict[str, Any]], *, prefix: str,
) -> dict[str, dict[str, Any]]:
    """Map worktree slug → task dict by reproducing the branch-name slug.

    The dispatcher's ``create_worktree`` derives the slug from
    ``make_branch_name(description, category, plugin)``; we replay the same
    derivation here to find each worktree directory's owning task.
    """
    out: dict[str, dict[str, Any]] = {}
    for t in tasks:
        branch = make_branch_name(
            t.get("description"),
            t.get("category"),
            t.get("plugin_name") or prefix,
            prefix=prefix,
        )
        slug = branch.removeprefix(f"{prefix}/")
        out[slug] = t
    return out


def smart_cleanup_worktrees(
    project_dir: Path,
    tasks: list[dict[str, Any]],
    *,
    prefix: str = "feat",
    target: str = "main",
    advisor: ConflictAdvisor | None = None,
    title_for_salvage: str | None = None,
) -> list[CleanupOutcome]:
    """Walk ``.claw-forge/worktrees/`` and act per-slug per the decision matrix.

    *tasks* is the session's task list as returned by the state service
    (``init_data["tasks"]``).  Each task dict must include at least
    ``description``, ``category``, ``plugin_name``, and ``status``.

    Returns a list of :class:`CleanupOutcome` records the caller can render.
    """
    worktrees_dir = project_dir / ".claw-forge" / "worktrees"
    if not worktrees_dir.is_dir():
        return []

    slug_to_task = _build_slug_to_task_map(tasks, prefix=prefix)
    outcomes: list[CleanupOutcome] = []

    for child in sorted(worktrees_dir.iterdir()):
        if not child.is_dir():
            continue
        slug = child.name
        branch = f"{prefix}/{slug}"
        task = slug_to_task.get(slug)
        task_status = task.get("status") if task else None
        has_commits = (
            branch_exists(project_dir, branch)
            and branch_has_commits_ahead(project_dir, branch, target)
        )
        action = decide_action(task_status, has_commits)
        outcome = CleanupOutcome(
            slug=slug, branch=branch, action=action, task_status=task_status,
        )

        if action == "preserve":
            outcome.success = True
            outcomes.append(outcome)
            continue

        if action == "remove":
            with suppress(Exception):
                _run_git(
                    ["worktree", "remove", "--force", str(child)],
                    project_dir,
                )
            if child.exists():
                shutil.rmtree(child, ignore_errors=True)
            # If the branch has no commits ahead it's safe to delete too —
            # but be defensive and only delete when branch_exists confirms it.
            if branch_exists(project_dir, branch):
                with suppress(Exception):
                    _run_git(
                        ["branch", "-D", branch], project_dir,
                    )
            outcome.success = True
            outcomes.append(outcome)
            continue

        # action == "salvage"
        result = squash_merge(
            project_dir, branch, target,
            title=title_for_salvage or f"salvage: {branch}",
            worktree_path=child,
        )
        if result.get("merged"):
            outcome.success = True
            outcome.commit_hash = result.get("commit_hash")
        else:
            outcome.success = False
            outcome.error = result.get("error")
            # Conflict — invoke advisor if provided.  Defensively swallow
            # advisor failures: they must not break the cleanup loop.
            if advisor is not None:
                with suppress(Exception):
                    proposal = advisor(project_dir, child, branch, target, task)
                    if proposal is not None:
                        outcome.proposal_path = str(proposal)
        outcomes.append(outcome)

    # Final bookkeeping sweep — drop stale entries in .git/worktrees/ for
    # directories we just removed.
    with suppress(Exception):
        _run_git(["worktree", "prune"], project_dir)

    return outcomes


__all__ = [
    "Action",
    "CleanupOutcome",
    "ConflictAdvisor",
    "decide_action",
    "smart_cleanup_worktrees",
]
