"""Squash-merge feature branches to target branch."""

from __future__ import annotations

import subprocess
from contextlib import suppress
from datetime import datetime
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

_ORPHAN_OVERWRITE_MARKER = "untracked working tree files would be overwritten by merge"


def _extract_orphan_files(stderr: str) -> list[str]:
    """Parse git's "untracked working tree files would be overwritten" error
    message and return the list of offending paths.

    Git's output for this case looks like::

        error: The following untracked working tree files would be overwritten by merge:
                examples/strategies/eth_momentum_v0.dsl
                tests/test_executor_price_window.py
        Please move or remove them before you merge.
        Aborting

    Each blocking file is on its own tab-indented line between the marker
    and the "Please" / "Aborting" terminator.
    """
    if _ORPHAN_OVERWRITE_MARKER not in stderr:
        return []
    files: list[str] = []
    in_block = False
    for raw in stderr.splitlines():
        if _ORPHAN_OVERWRITE_MARKER in raw:
            in_block = True
            continue
        if not in_block:
            continue
        line = raw.rstrip()
        if not line:
            break
        stripped = line.lstrip()
        if stripped.startswith(("Please move", "Aborting", "error:", "fatal:")):
            break
        # File lines are tab- or space-indented; the path is what's after.
        if line[0] in (" ", "\t"):
            files.append(stripped)
        else:
            # Reached non-indented non-blank content — end of block.
            break
    return files


def _sideline_orphans(project_dir: Path, files: list[str]) -> Path | None:
    """Move *files* (relative paths from *project_dir*) into
    ``.claw-forge/orphans/<timestamp>/`` so a subsequent ``git merge --squash``
    isn't blocked.  Returns the archive directory, or ``None`` if no files
    were actually moved (because none existed on disk).

    The archive preserves the original directory structure so a user can
    recover with a recursive copy.
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_dir = project_dir / ".claw-forge" / "orphans" / timestamp
    moved = 0
    for rel in files:
        src = project_dir / rel
        if not src.exists():
            continue
        dst = archive_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        moved += 1
    return archive_dir if moved > 0 else None


def sync_worktree_with_target(
    worktree_path: Path,
    target: str = "main",
) -> dict[str, Any]:
    """Bring the branch checked out in *worktree_path* up to date with *target*.

    Runs ``git merge --no-verify --no-edit <target>`` inside the worktree.
    Three outcomes are possible:

    - **No-op**: ``target`` is already an ancestor of the branch.  Return
      ``{"synced": True, "no_op": True, "merged_count": 0}``.
    - **Clean merge**: ``target`` had unseen commits and they merged
      without conflict.  Return ``{"synced": True, "merged_count": N}``.
    - **Conflict**: overlapping changes on one or more files.  The merge
      is aborted (``git merge --abort``) so the worktree is left in the
      same state it had before the call.  Return
      ``{"synced": False, "conflicts": [...]}``.

    A precondition: the worktree must have no uncommitted changes.  If
    it does, return ``{"synced": False, "dirty_worktree": True}`` and do
    nothing — merging on top of dirty state risks losing the user's edits.
    Callers that want to dispatch an agent into this worktree should treat
    that as a hard failure, same as a conflict.
    """
    # Refuse on dirty worktree — never overwrite uncommitted edits.
    status = _run_git(
        ["status", "--porcelain"], worktree_path,
    ).stdout.strip()
    if status:
        return {"synced": False, "dirty_worktree": True}

    # Count how many target commits are unseen by the branch.  If zero,
    # the merge will be a no-op.
    behind_count = 0
    try:
        behind_count = int(
            _run_git(
                ["rev-list", "--count", f"HEAD..{target}"], worktree_path,
            ).stdout.strip()
        )
    except Exception:
        # Cannot measure distance — assume there is work to pull and attempt
        # the merge.  If the target ref is bogus, the merge call below will
        # raise CalledProcessError and surface the real error as a conflict
        # rather than silently reporting no_op.
        behind_count = 1

    if behind_count == 0:
        return {"synced": True, "no_op": True, "merged_count": 0}

    try:
        _run_git(
            ["merge", "--no-verify", "--no-edit", target], worktree_path,
        )
        return {"synced": True, "merged_count": behind_count}
    except subprocess.CalledProcessError:
        # Conflict — collect the conflicted paths from the index, then abort.
        conflicts: list[str] = []
        try:
            conflicts = sorted(
                _run_git(
                    ["diff", "--name-only", "--diff-filter=U"], worktree_path,
                ).stdout.splitlines()
            )
        except Exception:
            conflicts = []
        with suppress(Exception):
            _run_git(["merge", "--abort"], worktree_path)
        with suppress(Exception):
            _run_git(["reset", "--hard", "HEAD"], worktree_path)
        return {"synced": False, "conflicts": conflicts}


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
        try:
            _run_git(["merge", "--squash", branch], project_dir)
        except subprocess.CalledProcessError as exc:
            # Two recovery paths share this handler.  They must be a single
            # ``except`` (not two siblings): ``CalledProcessError`` is a
            # subclass of ``Exception`` so two clauses would never fall
            # through — the first match wins and a ``raise`` from inside it
            # skips the second handler entirely.
            stderr = exc.stderr or ""
            recovered = False

            # 1. Orphan-debris case: project_dir's working tree contains
            # untracked files at paths the squash would overwrite.  Sideline
            # them and retry the squash directly.  On success, recovery is
            # done; on failure, fall through to the catch-up rebase.
            if _ORPHAN_OVERWRITE_MARKER in stderr:
                orphan_files = _extract_orphan_files(stderr)
                _sideline_orphans(project_dir, orphan_files)
                try:
                    _run_git(["merge", "--squash", branch], project_dir)
                    recovered = True
                except subprocess.CalledProcessError:
                    recovered = False

            # 2. Catch-up rebase: squash failed because target moved since
            # the feature branch was created.  Reset, merge target into the
            # feature branch (inside the worktree — the branch is checked
            # out there, so ``git checkout <branch>`` from project_dir would
            # fail with "already used by worktree" exit 128), then retry.
            if not recovered:
                with suppress(Exception):
                    _run_git(["reset", "--hard", "HEAD"], project_dir)
                if worktree_path is not None:
                    try:
                        _run_git(
                            ["merge", "--no-verify", "--no-edit", target],
                            worktree_path,
                        )
                    except Exception:
                        with suppress(Exception):
                            _run_git(["merge", "--abort"], worktree_path)
                        with suppress(Exception):
                            _run_git(["reset", "--hard", "HEAD"], worktree_path)
                        raise
                else:
                    switch_branch(project_dir, branch)
                    _run_git(["merge", "--no-verify", "--no-edit", target], project_dir)
                    switch_branch(project_dir, target)
                _run_git(["merge", "--squash", branch], project_dir)
        # If the squash produced no staged changes, the branch's content is
        # already reachable from target (e.g. another concurrent task squashed
        # identical content first, or the agent's commits were no-ops).  The
        # subsequent ``git commit --no-verify`` would fail with ``nothing to
        # commit``; recognise this as a no-op success instead of reporting a
        # phantom 'Merge failed'.  Use ``diff --cached`` rather than
        # ``status --porcelain`` so we only consider what the squash itself
        # staged, ignoring untracked entries (.claw-forge/ etc.) in
        # project_dir's working tree.
        staged_paths = _run_git(
            ["diff", "--cached", "--name-only"], project_dir
        ).stdout.strip()
        if not staged_paths:
            short_hash = _run_git(
                ["rev-parse", "--short", "HEAD"], project_dir
            ).stdout.strip()
            if worktree_path is not None:
                remove_worktree(project_dir, worktree_path)
            delete_branch(project_dir, branch, force=True)
            return {
                "merged": True,
                "commit_hash": short_hash,
                "no_op": True,
            }
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
