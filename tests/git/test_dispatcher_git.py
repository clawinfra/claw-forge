"""Tests for git integration in the dispatcher task lifecycle."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from claw_forge.git import GitOps


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
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
            message="feat(pay): add payments",
            task_id="task-1", plugin="coding",
            phase="coding", session_id="s1",
        ))
        # Testing phase
        (git_repo / "test_pay.py").write_text("assert True\n")
        asyncio.run(ops.checkpoint(
            message="test(pay): add tests",
            task_id="task-1", plugin="testing",
            phase="testing", session_id="s1",
        ))
        # Merge
        result = asyncio.run(ops.merge("feat/payments"))
        assert result["merged"] is True
        # History shows the squash commit on main
        history = asyncio.run(ops.history())
        assert len(history) >= 1
