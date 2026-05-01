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
            # Specific case: untracked debris in project_dir's working tree
            # (left over from earlier failed runs) collides with files the
            # squash would create.  Git aborts before staging anything; the
            # existing catch-up-merge recovery doesn't help (the issue is
            # debris in *target*, not branch divergence).  Sideline the
            # offending files and retry the squash directly.
            stderr = exc.stderr or ""
            if _ORPHAN_OVERWRITE_MARKER in stderr:
                orphan_files = _extract_orphan_files(stderr)
                _sideline_orphans(project_dir, orphan_files)
                _run_git(["merge", "--squash", branch], project_dir)
            else:
                raise
        except Exception:
            # Squash merge failed — likely conflicts because other branches
            # merged to target since this branch was created.  Reset, catch
            # the feature branch up to target, then retry.
            #
            # The catch-up merge MUST run inside the worktree when one is
            # passed: the feature branch is already checked out there, so
            # ``git checkout <branch>`` from project_dir would fail with
            # "fatal: '<branch>' is already used by worktree at ..." (exit
            # 128).  Without a worktree (e.g. legacy callers/tests), fall
            # back to toggling HEAD in project_dir.
            with suppress(Exception):
                _run_git(["reset", "--hard", "HEAD"], project_dir)
            if worktree_path is not None:
                try:
                    _run_git(
                        ["merge", "--no-verify", "--no-edit", target],
                        worktree_path,
                    )
                except Exception:
                    # Catch-up merge had a true conflict — clean the worktree
                    # so a later retry doesn't inherit conflict markers.
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
