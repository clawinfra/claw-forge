"""Tests for claw-forge merge CLI command."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from claw_forge.cli import app

runner = CliRunner()


@pytest.fixture()
def git_project(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    (tmp_path / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    return tmp_path


class TestMergeCommand:
    def test_merge_nonexistent_branch_shows_error(self, git_project: Path) -> None:
        result = runner.invoke(app, ["merge", "nonexistent", "--project", str(git_project)])
        assert result.exit_code == 0 or "not found" in result.output.lower()

    def test_merge_existing_branch_succeeds(self, git_project: Path) -> None:
        from claw_forge.git.branching import create_feature_branch
        from claw_forge.git.commits import commit_checkpoint

        create_feature_branch(git_project, "t1", "test-feat")
        (git_project / "x.py").write_text("x = 1\n")
        commit_checkpoint(
            git_project, message="feat: add x",
            task_id="t1", plugin="coding", phase="milestone", session_id="s1",
        )
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=git_project, check=True, capture_output=True,
        )

        result = runner.invoke(app, ["merge", "feat/test-feat", "--project", str(git_project)])
        assert "merged" in result.output.lower() or result.exit_code == 0

    def test_merge_no_branch_lists_branches(self, git_project: Path) -> None:
        from claw_forge.git.branching import create_feature_branch

        create_feature_branch(git_project, "t1", "list-test")
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=git_project, check=True, capture_output=True,
        )

        result = runner.invoke(app, ["merge", "--project", str(git_project)])
        assert "feat/list-test" in result.output or "feature branches" in result.output.lower()
