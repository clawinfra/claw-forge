"""Tests for git integration in the dispatcher task lifecycle."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from claw_forge.git import GitOps


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


class TestWorktreeLifecycle:
    def test_create_worktree_for_task(self, git_repo: Path) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        result = asyncio.run(ops.create_worktree("task-1", "user-auth"))
        assert result is not None
        branch, wt_path = result
        assert branch == "feat/user-auth"
        assert wt_path.is_dir()

    def test_checkpoint_in_worktree(self, git_repo: Path) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        result = asyncio.run(ops.create_worktree("task-1", "user-auth"))
        assert result is not None
        _, wt_path = result
        (wt_path / "auth.py").write_text("login = True\n")
        cp = asyncio.run(ops.checkpoint(
            message="feat(auth): implement login",
            task_id="task-1", plugin="coding",
            phase="coding", session_id="sess-1",
            cwd=wt_path,
        ))
        assert cp is not None
        assert cp["commit_hash"]

    def test_merge_from_worktree_cleans_up(self, git_repo: Path) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        result = asyncio.run(ops.create_worktree("task-1", "user-auth"))
        assert result is not None
        branch, wt_path = result
        (wt_path / "auth.py").write_text("login = True\n")
        asyncio.run(ops.checkpoint(
            message="feat(auth): implement login",
            task_id="task-1", plugin="coding",
            phase="coding", session_id="sess-1",
            cwd=wt_path,
        ))
        merge_result = asyncio.run(ops.merge(
            branch, worktree_path=wt_path,
        ))
        assert merge_result is not None
        assert merge_result["merged"] is True
        assert not wt_path.exists()

    def test_full_worktree_lifecycle(self, git_repo: Path) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        # Create worktree
        result = asyncio.run(ops.create_worktree("task-1", "payments"))
        assert result is not None
        branch, wt_path = result
        # Coding phase — in worktree
        (wt_path / "pay.py").write_text("pay = True\n")
        asyncio.run(ops.checkpoint(
            message="Implement payment processing",
            task_id="task-1", plugin="coding",
            phase="coding", session_id="s1",
            cwd=wt_path,
        ))
        # Testing phase
        (wt_path / "test_pay.py").write_text("assert True\n")
        asyncio.run(ops.checkpoint(
            message="Add payment tests",
            task_id="task-1", plugin="testing",
            phase="testing", session_id="s1",
            cwd=wt_path,
        ))
        # Merge with worktree cleanup
        merge_result = asyncio.run(ops.merge(
            branch,
            title="Implement payment processing",
            steps=["Add Stripe integration", "Write unit tests"],
            task_id="task-1",
            session_id="s1",
            worktree_path=wt_path,
        ))
        assert merge_result is not None
        assert merge_result["merged"] is True
        assert not wt_path.exists()
        # History shows the squash commit on main
        history = asyncio.run(ops.history())
        assert len(history) >= 1
        latest = history[0]
        assert latest["message"] == "Implement payment processing"


class TestGitOpsIntegration:
    def test_create_branch_for_task(self, git_repo: Path) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        branch = asyncio.run(ops.create_branch("task-1", "user-auth"))
        assert branch == "feat/user-auth"

    def test_checkpoint_after_plugin(self, git_repo: Path) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        asyncio.run(ops.create_branch("task-1", "user-auth"))
        (git_repo / "auth.py").write_text("login = True\n")
        result = asyncio.run(ops.checkpoint(
            message="feat(auth): implement login",
            task_id="task-1",
            plugin="coding",
            phase="coding",
            session_id="sess-1",
        ))
        assert result is not None
        assert result["commit_hash"]

    def test_merge_after_completion(self, git_repo: Path) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        asyncio.run(ops.create_branch("task-1", "user-auth"))
        (git_repo / "auth.py").write_text("login = True\n")
        asyncio.run(ops.checkpoint(
            message="feat(auth): implement login",
            task_id="task-1",
            plugin="coding",
            phase="coding",
            session_id="sess-1",
        ))
        result = asyncio.run(ops.merge("feat/user-auth"))
        assert result["merged"] is True

    def test_full_lifecycle(self, git_repo: Path) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        # Create branch
        asyncio.run(ops.create_branch("task-1", "payments"))
        # Coding phase
        (git_repo / "pay.py").write_text("pay = True\n")
        asyncio.run(ops.checkpoint(
            message="Implement payment processing",
            task_id="task-1", plugin="coding",
            phase="coding", session_id="s1",
        ))
        # Testing phase
        (git_repo / "test_pay.py").write_text("assert True\n")
        asyncio.run(ops.checkpoint(
            message="Add payment tests",
            task_id="task-1", plugin="testing",
            phase="testing", session_id="s1",
        ))
        # Merge with semantic context
        result = asyncio.run(ops.merge(
            "feat/payments",
            title="Implement payment processing",
            steps=["Add Stripe integration", "Write unit tests"],
            task_id="task-1",
            session_id="s1",
        ))
        assert result["merged"] is True
        # History shows the squash commit on main
        history = asyncio.run(ops.history())
        assert len(history) >= 1
        # Verify semantic message content
        latest = history[0]
        assert latest["message"] == "Implement payment processing"
