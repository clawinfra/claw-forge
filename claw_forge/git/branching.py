"""Feature branch lifecycle — create, switch, delete."""

from __future__ import annotations

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
