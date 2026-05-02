"""Typer subapp for ``claw-forge worktrees [list|prune]``.

Manual cleanup for the feature-branch worktrees claw-forge creates under
``.claw-forge/worktrees/``.  Worktrees from terminally-failed tasks (where
no further retry will land) and from completed tasks whose squash-merge
itself failed are not auto-salvaged at startup — the existing salvage path
fires only when ``orphans_reset > 0`` (interrupted-run recovery).  This
subapp gives users an explicit knob to inspect and clear them.
"""

from __future__ import annotations

import shutil
from contextlib import suppress
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from claw_forge.git.branching import (
    branch_exists,
    delete_branch,
    merge_orphaned_worktrees,
    prune_worktrees,
    scan_orphaned_branches,
)
from claw_forge.git.repo import _run_git, detect_default_branch

worktrees_app = typer.Typer(
    help=(
        "Manage feature-branch worktrees under .claw-forge/worktrees/. "
        "Use 'list' to inspect or 'prune' to clean up."
    ),
    no_args_is_help=True,
)

console = Console()


def _resolve_project_and_target(project: str, target: str | None) -> tuple[Path, str]:
    project_path = Path(project).resolve()
    target_branch: str = target if target else detect_default_branch(project_path)
    return project_path, target_branch


def _list_all_worktree_dirs(
    project_dir: Path,
    *,
    prefix: str,
    target: str,
) -> list[dict[str, Any]]:
    """Walk ``.claw-forge/worktrees/`` and return all directories — including
    empty branches that ``scan_orphaned_branches`` filters out — so the user
    sees the complete state.
    """
    by_branch_with_commits = {
        e["branch"]: e for e in scan_orphaned_branches(
            project_dir, prefix=prefix, target=target,
        )
    }

    worktrees_dir = project_dir / ".claw-forge" / "worktrees"
    if not worktrees_dir.is_dir():
        return []

    rows: list[dict[str, Any]] = []
    for child in sorted(worktrees_dir.iterdir()):
        if not child.is_dir():
            continue
        slug = child.name
        branch = f"{prefix}/{slug}"
        if branch in by_branch_with_commits:
            rows.append(by_branch_with_commits[branch])
            continue
        # Either branch is missing or has no commits ahead of target.
        rows.append({
            "branch": branch,
            "slug": slug,
            "commit_count": 0,
            "commit_subjects": [],
            "worktree_path": str(child),
        })
    return rows


@worktrees_app.command("list")
def list_cmd(
    project: str = typer.Option(".", "--project", "-p", help="Project root directory."),
    target: str = typer.Option(
        "", "--target", help="Target branch (default: auto-detect).",
    ),
    prefix: str = typer.Option(
        "feat", "--prefix", help="Feature-branch prefix.",
    ),
) -> None:
    """List all worktrees with their branches and commit counts."""
    project_dir, target_branch = _resolve_project_and_target(project, target or None)
    rows = _list_all_worktree_dirs(project_dir, prefix=prefix, target=target_branch)

    worktrees_dir = project_dir / ".claw-forge" / "worktrees"
    if not rows:
        console.print(
            f"[dim]No worktree directories under {worktrees_dir}/[/dim]"
        )
        return

    console.print(f"[bold]Worktrees under {worktrees_dir}/[/bold]\n")
    salvageable = 0
    for row in rows:
        n: int = row["commit_count"]
        if n > 0:
            salvageable += 1
            console.print(
                f"  [bold]{row['branch']}[/bold] — "
                f"{n} commit{'s' if n != 1 else ''} ahead of {target_branch}"
            )
            subjects: list[str] = row["commit_subjects"]
            for subj in subjects[:5]:
                console.print(f"    • {subj}")
            if len(subjects) > 5:
                console.print(f"    [dim]… {len(subjects) - 5} more[/dim]")
        else:
            console.print(
                f"  [dim]{row['branch']} — empty (no commits / branch missing)[/dim]"
            )
        console.print()

    console.print(
        f"[dim]{len(rows)} worktree(s) total — "
        f"{salvageable} salvageable, {len(rows) - salvageable} empty.[/dim]"
    )


@worktrees_app.command("prune")
def prune_cmd(
    project: str = typer.Option(".", "--project", "-p", help="Project root directory."),
    target: str = typer.Option(
        "", "--target", help="Target branch (default: auto-detect).",
    ),
    prefix: str = typer.Option(
        "feat", "--prefix", help="Feature-branch prefix.",
    ),
    discard: bool = typer.Option(
        False, "--discard",
        help=(
            "Force-remove every worktree directory and its branch without "
            "attempting salvage.  Use when the work is throwaway."
        ),
    ),
) -> None:
    """Salvage-merge worktrees with commits, then drop the directories.

    Default behaviour (no flags) runs the same two-step cleanup
    ``claw-forge run`` does internally — squash-merge any feature branch
    with commits ahead of *target*, then remove the leftover directories.
    With ``--discard``, both steps are skipped and every directory + branch
    is force-removed.
    """
    project_dir, target_branch = _resolve_project_and_target(project, target or None)
    worktrees_dir = project_dir / ".claw-forge" / "worktrees"

    if not worktrees_dir.is_dir():
        console.print(f"[dim]No worktree directories under {worktrees_dir}/[/dim]")
        return

    if discard:
        removed: list[str] = []
        for child in sorted(worktrees_dir.iterdir()):
            if not child.is_dir():
                continue
            slug = child.name
            branch = f"{prefix}/{slug}"
            with suppress(Exception):
                _run_git(["worktree", "remove", "--force", str(child)], project_dir)
            if child.exists():
                shutil.rmtree(child, ignore_errors=True)
            if branch_exists(project_dir, branch):
                with suppress(Exception):
                    delete_branch(project_dir, branch, force=True)
            removed.append(branch)
        with suppress(Exception):
            _run_git(["worktree", "prune"], project_dir)
        console.print(
            f"[green]Discarded {len(removed)} worktree(s) and their branches.[/green]"
        )
        return

    salvaged = merge_orphaned_worktrees(
        project_dir, prefix=prefix, target=target_branch,
    )
    pruned = prune_worktrees(project_dir)

    if salvaged:
        console.print(
            f"[green]Salvage-merged {len(salvaged)} branch(es) → "
            f"{target_branch}:[/green]"
        )
        for b in salvaged:
            console.print(f"  • {b}")
    if pruned:
        console.print(
            f"[dim]Pruned {pruned} worktree director{'ies' if pruned != 1 else 'y'}."
            f"[/dim]"
        )
    if not salvaged and not pruned:
        console.print(
            f"[dim]Nothing to prune under {worktrees_dir}/[/dim]"
        )


# Re-export for tests so they can drive the subapp without going through main.
__all__ = ["worktrees_app", "list_cmd", "prune_cmd"]
