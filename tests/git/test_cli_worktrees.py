"""Tests for ``claw-forge worktrees`` CLI commands."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from claw_forge.cli import app
from claw_forge.git.branching import (
    branch_exists,
    create_worktree,
)
from claw_forge.git.commits import commit_checkpoint


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(
        ["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t.x"], cwd=tmp_path, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"], cwd=tmp_path, check=True,
    )
    (tmp_path / "README.md").write_text("# init\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True,
    )
    return tmp_path


def _make_worktree_with_commit(
    project: Path, slug: str, *, commit_msg: str = "feat: change",
) -> tuple[str, Path]:
    branch, wt = create_worktree(project, f"task-{slug}", slug)
    (wt / f"{slug}.py").write_text(f"# {slug}\n")
    commit_checkpoint(
        wt, message=commit_msg,
        task_id=f"task-{slug}", plugin="coding", phase="coding",
        session_id="s1",
    )
    return branch, wt


class TestWorktreesList:
    def test_list_no_worktrees_directory(self, git_repo: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            app, ["worktrees", "list", "--project", str(git_repo)],
        )
        assert result.exit_code == 0, result.output
        assert "No worktree directories" in result.output

    def test_list_shows_branch_and_commit_count(self, git_repo: Path) -> None:
        _make_worktree_with_commit(git_repo, "alpha", commit_msg="feat: a1")

        runner = CliRunner()
        result = runner.invoke(
            app, ["worktrees", "list", "--project", str(git_repo)],
        )
        assert result.exit_code == 0, result.output
        assert "feat/alpha" in result.output
        assert "1 commit" in result.output
        assert "feat: a1" in result.output
        assert "1 salvageable" in result.output

    def test_worktrees_no_subcommand_shows_help(self) -> None:
        """Bare ``claw-forge worktrees`` shows help; users must pick a
        subcommand.  ``no_args_is_help=True`` is what produces this.
        """
        runner = CliRunner()
        result = runner.invoke(app, ["worktrees"])
        assert "list" in result.output.lower()
        assert "prune" in result.output.lower()

    def test_list_includes_empty_branches(self, git_repo: Path) -> None:
        """Worktree dirs whose branches have no commits ahead of target are
        listed too — otherwise ``empty + leftover`` cases would be invisible
        until the user ran ``prune``.
        """
        # Create a worktree but DON'T commit to it.
        create_worktree(git_repo, "task-empty", "emptywt")

        runner = CliRunner()
        result = runner.invoke(
            app, ["worktrees", "list", "--project", str(git_repo)],
        )
        assert result.exit_code == 0, result.output
        assert "feat/emptywt" in result.output
        assert "empty" in result.output


class TestWorktreesPrune:
    def test_prune_salvage_merges_branch_with_commits(
        self, git_repo: Path,
    ) -> None:
        branch, wt = _make_worktree_with_commit(git_repo, "gamma")

        runner = CliRunner()
        result = runner.invoke(
            app, ["worktrees", "prune", "--project", str(git_repo)],
        )
        assert result.exit_code == 0, result.output
        assert "Salvage-merged" in result.output
        assert branch in result.output
        # Worktree dir + branch removed; salvaged work landed on main.
        assert not wt.exists()
        assert not branch_exists(git_repo, branch)
        assert (git_repo / "gamma.py").exists()

    def test_prune_drops_empty_directory(self, git_repo: Path) -> None:
        """A worktree dir whose branch has no commits is just removed —
        nothing to salvage.
        """
        _, wt = create_worktree(git_repo, "task-empty", "delta")
        # Branch exists but is at the same commit as main → nothing to salvage.

        runner = CliRunner()
        result = runner.invoke(
            app, ["worktrees", "prune", "--project", str(git_repo)],
        )
        assert result.exit_code == 0, result.output
        assert not wt.exists()
        # The empty branch shouldn't be salvage-merged (nothing to merge).
        assert "Salvage-merged" not in result.output
        assert "Pruned" in result.output

    def test_prune_no_worktrees_directory(self, git_repo: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            app, ["worktrees", "prune", "--project", str(git_repo)],
        )
        assert result.exit_code == 0, result.output
        assert "No worktree directories" in result.output

    def test_prune_discard_skips_salvage_and_force_removes(
        self, git_repo: Path,
    ) -> None:
        """``--discard`` removes the worktree + branch even if the branch has
        unmerged commits, without attempting salvage.  Use case: throwaway
        agent output the user explicitly does not want on main.
        """
        branch, wt = _make_worktree_with_commit(git_repo, "epsilon")
        # Confirm there are commits to discard.
        assert branch_exists(git_repo, branch)

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["worktrees", "prune", "--project", str(git_repo), "--discard"],
        )
        assert result.exit_code == 0, result.output
        assert "Discarded 1 worktree" in result.output
        assert not wt.exists()
        assert not branch_exists(git_repo, branch)
        # Discarded work did NOT land on main.
        assert not (git_repo / "epsilon.py").exists()
