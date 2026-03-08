"""Tests for claw_forge.git.branching — create, switch, delete feature branches."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claw_forge.git.branching import (
    branch_exists,
    create_feature_branch,
    current_branch,
    delete_branch,
    switch_branch,
)


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
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


class TestCreateFeatureBranch:
    def test_creates_branch_with_prefix(self, git_repo: Path) -> None:
        create_feature_branch(git_repo, "abc123", "user-auth", prefix="feat")
        assert branch_exists(git_repo, "feat/user-auth")

    def test_switches_to_new_branch(self, git_repo: Path) -> None:
        create_feature_branch(git_repo, "abc123", "user-auth")
        assert current_branch(git_repo) == "feat/user-auth"

    def test_custom_prefix(self, git_repo: Path) -> None:
        create_feature_branch(git_repo, "abc123", "fix-login", prefix="fix")
        assert branch_exists(git_repo, "fix/fix-login")

    def test_already_exists_switches_only(self, git_repo: Path) -> None:
        create_feature_branch(git_repo, "abc123", "user-auth")
        switch_branch(git_repo, "main")
        create_feature_branch(git_repo, "abc123", "user-auth")
        assert current_branch(git_repo) == "feat/user-auth"


class TestCurrentBranch:
    def test_returns_main_on_fresh_repo(self, git_repo: Path) -> None:
        name = current_branch(git_repo)
        assert name in ("main", "master")


class TestBranchExists:
    def test_returns_true_for_existing(self, git_repo: Path) -> None:
        assert branch_exists(git_repo, "main") or branch_exists(git_repo, "master")

    def test_returns_false_for_nonexistent(self, git_repo: Path) -> None:
        assert branch_exists(git_repo, "nonexistent") is False


class TestDeleteBranch:
    def test_deletes_merged_branch(self, git_repo: Path) -> None:
        create_feature_branch(git_repo, "abc123", "temp")
        switch_branch(git_repo, "main")
        delete_branch(git_repo, "feat/temp")
        assert branch_exists(git_repo, "feat/temp") is False

    def test_delete_nonexistent_is_noop(self, git_repo: Path) -> None:
        delete_branch(git_repo, "nonexistent")  # should not raise
