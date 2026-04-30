"""Per-hotspot apply lifecycle: branch → subagent → test → merge or revert.

Each hotspot is refactored on its own feature branch, gated by the
project's test command, and squash-merged into ``main`` only on green.
On a red gate, the worktree + branch are removed; ``main`` is never
touched.

Reuses claw-forge's existing git plumbing (``create_worktree``,
``squash_merge``, ``remove_worktree``) so this command inherits the
same merge-conflict handling, no-op detection, and worktree cleanup
that ``claw-forge run`` ships with.
"""
from __future__ import annotations

import asyncio
import logging
import shlex
import subprocess
from pathlib import Path
from typing import Any

from claw_forge.boundaries.refactor import run_refactor_subagent
from claw_forge.boundaries.scorer import Hotspot
from claw_forge.git.branching import create_worktree, remove_worktree
from claw_forge.git.merge import squash_merge
from claw_forge.git.slug import make_slug

_log = logging.getLogger("claw_forge.boundaries.apply")


def run_test_command(
    cmd: str, *, cwd: Path, timeout_seconds: float = 1800.0,
) -> bool:
    """Run *cmd* in *cwd*; return True iff it exits 0 within *timeout_seconds*."""
    try:
        result = subprocess.run(  # noqa: S603
            shlex.split(cmd),
            cwd=cwd,
            timeout=timeout_seconds,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return False
    except FileNotFoundError:
        return False
    return result.returncode == 0


def apply_hotspot(
    hotspot: Hotspot,
    *,
    project_dir: Path,
    test_command: str,
) -> dict[str, Any]:
    """Refactor one hotspot on a feature branch with test gating.

    Returns a dict with ``status`` ∈ ``{"merged", "reverted", "skipped"}``
    plus diagnostic detail in ``reason`` / ``commit_hash``.

    Lifecycle:
    1. ``create_worktree(project_dir, slug=...)`` produces an isolated
       branch + worktree under ``.claw-forge/worktrees/``.
    2. ``run_refactor_subagent(hotspot, project_dir=worktree_path)`` —
       agent edits files inside the worktree.
    3. ``git add -A && git commit --no-verify`` on the boundaries branch.
       If nothing was staged → ``skipped`` with reason "no changes".
    4. Test command runs *inside the worktree* so it sees the refactor.
    5. **Green** → ``squash_merge`` into ``project_dir``'s default branch;
       worktree + boundaries branch removed by the merge helper.
    6. **Red** → worktree + boundaries branch removed; main unchanged.
    """
    slug_seed = "boundaries-" + hotspot.path.replace("/", "-").replace(".", "-")
    slug = make_slug(slug_seed)
    create_result = create_worktree(
        project_dir, task_id=slug, slug=slug, prefix="boundaries",
    )
    branch_name, worktree_path = create_result
    try:
        # Run subagent inside the worktree
        try:
            agent_result = asyncio.run(
                run_refactor_subagent(hotspot, project_dir=worktree_path)
            )
        except Exception as exc:  # noqa: BLE001 — best-effort; cleanup + report
            _log.warning("subagent error on %s: %s", hotspot.path, exc)
            _cleanup_branch(project_dir, worktree_path, branch_name)
            return {"status": "skipped", "reason": f"subagent error: {exc}"}

        # Stage and commit whatever the subagent produced.
        subprocess.run(  # noqa: S603, S607
            ["git", "add", "-A"], cwd=worktree_path, check=True,
        )
        commit_proc = subprocess.run(  # noqa: S603, S607
            ["git", "commit", "--no-verify", "-m",
             f"boundaries({hotspot.path}): extract {hotspot.pattern or 'pattern'}"],
            cwd=worktree_path, capture_output=True, text=True,
        )
        if commit_proc.returncode != 0:
            # No changes to commit — subagent didn't actually edit anything.
            _cleanup_branch(project_dir, worktree_path, branch_name)
            return {
                "status": "skipped",
                "reason": "no changes",
                "agent_result": agent_result,
            }

        # Test gate runs in the worktree so it sees the refactored files.
        passed = run_test_command(test_command, cwd=worktree_path)
        if not passed:
            _cleanup_branch(project_dir, worktree_path, branch_name)
            return {"status": "reverted", "reason": "tests failed"}

        # Green → squash-merge to project_dir's default branch.
        merge = squash_merge(
            project_dir, branch_name,
            title=f"boundaries: refactor {hotspot.path} ({hotspot.pattern or 'pattern'})",
            worktree_path=worktree_path,
        )
        if not merge.get("merged"):
            return {
                "status": "skipped",
                "reason": f"merge failed: {merge.get('error', '')}",
            }
        return {
            "status": "merged",
            "commit_hash": merge.get("commit_hash", ""),
        }
    except Exception as exc:  # noqa: BLE001 — last-resort cleanup
        _cleanup_branch(project_dir, worktree_path, branch_name)
        return {"status": "skipped", "reason": f"unexpected error: {exc}"}


def _cleanup_branch(
    project_dir: Path, worktree_path: Path, branch_name: str,
) -> None:
    """Best-effort: remove the worktree + delete the branch."""
    try:
        remove_worktree(project_dir, worktree_path)
    except Exception:  # noqa: BLE001
        pass
    subprocess.run(  # noqa: S603, S607
        ["git", "branch", "-D", branch_name],
        cwd=project_dir, check=False, capture_output=True,
    )
