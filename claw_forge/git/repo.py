"""Git repository initialization and detection."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

_GITIGNORE_ENTRIES = [
    ".claw-forge/state.log",
    ".claw-forge/state.db",
    ".claw-forge/state.db-journal",
]


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603, S607
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _detect_default_branch(cwd: Path) -> str:
    try:
        result = _run_git(["symbolic-ref", "--short", "HEAD"], cwd)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "main"


def ensure_gitignore(project_dir: Path) -> None:
    gitignore = project_dir / ".gitignore"
    existing = gitignore.read_text() if gitignore.exists() else ""
    lines = existing.splitlines()
    added = []
    for entry in _GITIGNORE_ENTRIES:
        if entry not in lines:
            added.append(entry)
    if added:
        suffix = "\n".join(added) + "\n"
        if existing and not existing.endswith("\n"):
            suffix = "\n" + suffix
        gitignore.write_text(existing + suffix)


def init_or_detect(project_dir: Path) -> dict[str, Any]:
    initialized = False
    if not (project_dir / ".git").is_dir():
        _run_git(["init"], project_dir)
        initialized = True
    ensure_gitignore(project_dir)
    default_branch = _detect_default_branch(project_dir)
    return {
        "initialized": initialized,
        "default_branch": default_branch,
    }
