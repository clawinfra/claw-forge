"""Tests for claw_forge.git.branching — create, switch, delete feature branches."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claw_forge.git.branching import (
    branch_exists,
    branch_overlap_files,
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


def _commit_file(repo: Path, name: str, content: str, msg: str) -> None:
    (repo / name).write_text(content)
    subprocess.run(["git", "add", name], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=repo, check=True, capture_output=True,
    )


class TestBranchOverlapFiles:
    def test_returns_empty_when_branch_at_target(self, git_repo: Path) -> None:
        subprocess.run(
            ["git", "checkout", "-b", "feat/x"],
            cwd=git_repo, check=True, capture_output=True,
        )
        assert branch_overlap_files(git_repo, "feat/x", "main") == []

    def test_returns_empty_when_no_file_overlap(self, git_repo: Path) -> None:
        subprocess.run(
            ["git", "checkout", "-b", "feat/x"],
            cwd=git_repo, check=True, capture_output=True,
        )
        _commit_file(git_repo, "branch_only.txt", "branch", "branch change")
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=git_repo, check=True, capture_output=True,
        )
        _commit_file(git_repo, "main_only.txt", "main", "main change")
        assert branch_overlap_files(git_repo, "feat/x", "main") == []

    def test_returns_overlapping_files_sorted(self, git_repo: Path) -> None:
        _commit_file(git_repo, "a.py", "v0", "seed a")
        _commit_file(git_repo, "b.py", "v0", "seed b")
        subprocess.run(
            ["git", "checkout", "-b", "feat/x"],
            cwd=git_repo, check=True, capture_output=True,
        )
        _commit_file(git_repo, "b.py", "branch", "branch edits b")
        _commit_file(git_repo, "a.py", "branch", "branch edits a")
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=git_repo, check=True, capture_output=True,
        )
        _commit_file(git_repo, "a.py", "main", "main edits a")
        _commit_file(git_repo, "b.py", "main", "main edits b")
        # Both sides touched a.py and b.py since the merge-base
        assert branch_overlap_files(git_repo, "feat/x", "main") == ["a.py", "b.py"]

    def test_returns_empty_for_unknown_branch(self, git_repo: Path) -> None:
        assert branch_overlap_files(git_repo, "feat/missing", "main") == []
