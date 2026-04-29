"""Checkpoint commits with structured trailers and history parsing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from claw_forge.git.branching import current_branch
from claw_forge.git.repo import _run_git

_TRAILER_PATTERN = re.compile(r"^(Task-ID|Plugin|Phase|Session):\s*(.+)$", re.MULTILINE)


def commit_checkpoint(
    project_dir: Path,
    *,
    message: str,
    task_id: str,
    plugin: str,
    phase: str,
    session_id: str,
) -> dict[str, Any] | None:
    # Stage all changes
    _run_git(["add", "-A"], project_dir)

    # Check if there's anything to commit
    try:
        _run_git(["diff", "--cached", "--quiet"], project_dir)
        return None  # no staged changes
    except Exception:
        pass  # there ARE staged changes — proceed

    body = (
        f"{message}\n\n"
        f"Task-ID: {task_id}\n"
        f"Plugin: {plugin}\n"
        f"Phase: {phase}\n"
        f"Session: {session_id}"
    )
    try:
        _run_git(["commit", "--no-verify", "-m", body], project_dir)
    except Exception:  # noqa: BLE001
        # Commit can fail due to pre-commit hooks, signing errors, or
        # race conditions — a checkpoint failure should not crash the task.
        return None

    short_hash = _run_git(
        ["rev-parse", "--short", "HEAD"], project_dir
    ).stdout.strip()
    branch = current_branch(project_dir)

    return {"commit_hash": short_hash, "branch": branch}


def emergency_commit(project_dir: Path, *, task_id: str = "unknown") -> bool:
    """Best-effort emergency commit of all dirty files.  Synchronous, fast.

    Designed to be called from signal handlers (SIGTERM/SIGINT) where the
    event loop may not be available.  Returns ``True`` if a commit was made.
    """
    try:
        _run_git(["add", "-A"], project_dir)
    except Exception:  # noqa: BLE001
        return False
    # Check if there are staged changes
    try:
        _run_git(["diff", "--cached", "--quiet"], project_dir)
        return False  # nothing staged
    except Exception:
        pass  # staged changes exist — proceed
    try:
        _run_git(
            ["commit", "--no-verify", "-m",
             f"emergency: auto-save before shutdown (task {task_id})"],
            project_dir,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def push_to_remote(
    project_dir: Path,
    *,
    remote: str = "origin",
    branch: str | None = None,
) -> dict[str, Any]:
    """Push current branch to remote.

    Args:
        project_dir: Path to the git repository.
        remote: Remote name (default: "origin").
        branch: Branch to push. If None, uses current branch.

    Returns:
        Dict with keys: remote, branch, success, error (if failed).
    """
    if branch is None:
        branch = current_branch(project_dir)

    try:
        _run_git(["push", remote, branch], project_dir)
        return {"remote": remote, "branch": branch, "success": True, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"remote": remote, "branch": branch, "success": False, "error": str(exc)}


def has_remote(project_dir: Path, remote: str = "origin") -> bool:
    """Return True if the given remote exists in the repository."""
    try:
        result = _run_git(["remote"], project_dir)
        return remote in result.stdout.strip().splitlines()
    except Exception:  # noqa: BLE001
        return False


def branch_commit_subjects(
    project_dir: Path,
    branch: str,
    target: str = "main",
) -> list[str]:
    """Return subject lines of commits on *branch* not yet in *target*."""
    try:
        result = _run_git(
            ["log", "--format=%s", f"{target}..{branch}"],
            project_dir,
        )
        return [
            s.strip()
            for s in result.stdout.strip().splitlines()
            if s.strip()
        ]
    except Exception:  # noqa: BLE001
        return []


def task_history(
    project_dir: Path,
    *,
    task_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    # Use a delimiter to parse commits
    sep = "---COMMIT-SEP---"
    fmt = f"%H{sep}%s{sep}%aI{sep}%B{sep}"
    try:
        result = _run_git(
            ["log", f"--format={fmt}", f"-n{limit * 3 if task_id else limit}"],
            project_dir,
        )
    except Exception:
        return []

    commits: list[dict[str, Any]] = []
    raw_commits = result.stdout.strip().split(f"{sep}\n")

    for raw in raw_commits:
        parts = raw.split(sep)
        if len(parts) < 4:
            continue
        full_hash, subject, timestamp, body = (
            parts[0].strip(),
            parts[1].strip(),
            parts[2].strip(),
            parts[3].strip(),
        )
        if not full_hash:
            continue

        trailers: dict[str, str] = {}
        for match in _TRAILER_PATTERN.finditer(body):
            key = match.group(1).lower().replace("-", "_")
            trailers[key] = match.group(2).strip()

        if task_id and trailers.get("task_id") != task_id:
            continue

        commits.append({
            "hash": full_hash[:10],
            "message": subject,
            "timestamp": timestamp,
            "trailers": trailers,
        })

        if len(commits) >= limit:
            break

    return commits
