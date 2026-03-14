"""Tests for claw_forge.git.merge — squash-merge feature branches."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claw_forge.git.branching import branch_exists, create_feature_branch, current_branch
from claw_forge.git.commits import commit_checkpoint
from claw_forge.git.merge import squash_merge


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


class TestSquashMerge:
    def test_squash_merge_creates_single_commit(self, git_repo: Path) -> None:
        create_feature_branch(git_repo, "t1", "auth")
        (git_repo / "auth.py").write_text("login = True\n")
        commit_checkpoint(
            git_repo, message="feat(auth): add login",
            task_id="t1", plugin="coding", phase="milestone", session_id="s1",
        )
        (git_repo / "auth_test.py").write_text("assert True\n")
        commit_checkpoint(
            git_repo, message="test(auth): add test",
            task_id="t1", plugin="testing", phase="milestone", session_id="s1",
        )

        result = squash_merge(git_repo, "feat/auth")
        assert result["merged"] is True
        assert result["commit_hash"]
        assert current_branch(git_repo) in ("main", "master")

    def test_squash_merge_deletes_branch(self, git_repo: Path) -> None:
        create_feature_branch(git_repo, "t2", "payments")
        (git_repo / "pay.py").write_text("pay = True\n")
        commit_checkpoint(
            git_repo, message="feat(pay): add payments",
            task_id="t2", plugin="coding", phase="milestone", session_id="s1",
        )
        squash_merge(git_repo, "feat/payments")
        assert branch_exists(git_repo, "feat/payments") is False

    def test_squash_merge_custom_target(self, git_repo: Path) -> None:
        # Create a develop branch
        subprocess.run(
            ["git", "checkout", "-b", "develop"],
            cwd=git_repo, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=git_repo, check=True, capture_output=True,
        )
        create_feature_branch(git_repo, "t3", "nav")
        (git_repo / "nav.py").write_text("nav = True\n")
        commit_checkpoint(
            git_repo, message="feat(nav): add nav",
            task_id="t3", plugin="coding", phase="milestone", session_id="s1",
        )
        result = squash_merge(git_repo, "feat/nav", target="develop")
        assert result["merged"] is True
        assert current_branch(git_repo) == "develop"

    def test_squash_merge_nonexistent_branch(self, git_repo: Path) -> None:
        result = squash_merge(git_repo, "feat/nonexistent")
        assert result["merged"] is False

    def test_squash_merge_with_semantic_message(self, git_repo: Path) -> None:
        create_feature_branch(git_repo, "t4", "user-auth")
        (git_repo / "auth.py").write_text("login = True\n")
        commit_checkpoint(
            git_repo, message="Implement login endpoint",
            task_id="t4", plugin="coding", phase="coding", session_id="s1",
        )
        (git_repo / "test_auth.py").write_text("assert True\n")
        commit_checkpoint(
            git_repo, message="Add auth integration tests",
            task_id="t4", plugin="testing", phase="testing", session_id="s1",
        )

        result = squash_merge(
            git_repo, "feat/user-auth",
            title="Implement user authentication",
            steps=["Create login endpoint", "Write integration tests"],
            task_id="t4",
            session_id="s1",
        )
        assert result["merged"] is True

        # Verify the commit message on main
        log = subprocess.run(
            ["git", "log", "-1", "--format=%B"],
            cwd=git_repo, capture_output=True, text=True, check=True,
        )
        body = log.stdout
        assert "Implement user authentication" in body
        assert "Completed Steps:" in body
        assert "- [x] Create login endpoint" in body
        assert "- [x] Write integration tests" in body
        assert "Completed Phases:" in body
        assert "- Implement login endpoint" in body
        assert "- Add auth integration tests" in body
        assert "Task-ID: t4" in body
        assert "Session: s1" in body

    def test_squash_merge_without_context_uses_default(
        self, git_repo: Path,
    ) -> None:
        create_feature_branch(git_repo, "t5", "legacy")
        (git_repo / "legacy.py").write_text("old = True\n")
        commit_checkpoint(
            git_repo, message="feat(legacy): add old module",
            task_id="t5", plugin="coding", phase="coding", session_id="s1",
        )
        squash_merge(git_repo, "feat/legacy")

        log = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=git_repo, capture_output=True, text=True, check=True,
        )
        assert log.stdout.strip() == "merge: feat/legacy (squash)"
