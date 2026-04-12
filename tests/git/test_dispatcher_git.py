"""Tests for git integration in the dispatcher task lifecycle."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from claw_forge.git import GitOps
from claw_forge.git.branching import branch_exists, branch_has_commits_ahead, current_branch


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


class TestApplyOnCompletion:
    """Tests for GitOps.apply_on_completion — the dispatcher's post-task git hook."""

    def _make_worktree_with_commit(
        self, ops: GitOps, git_repo: Path, task_id: str, slug: str, filename: str
    ) -> tuple[str, Path]:
        """Helper: create a worktree, write a file, and commit a checkpoint."""
        result = asyncio.run(ops.create_worktree(task_id, slug))
        assert result is not None
        branch, wt_path = result
        (wt_path / filename).write_text("x = 1\n")
        asyncio.run(ops.checkpoint(
            message=f"feat: implement {slug}",
            task_id=task_id, plugin="coding",
            phase="coding", session_id="s1",
            cwd=wt_path,
        ))
        return branch, wt_path

    def test_auto_strategy_merges_to_main_and_removes_worktree(
        self, git_repo: Path
    ) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        branch, wt_path = self._make_worktree_with_commit(
            ops, git_repo, "t1", "user-auth", "auth.py"
        )

        result = asyncio.run(ops.apply_on_completion(
            task_id="t1",
            slug="user-auth",
            description="Implement user authentication",
            plugin_name="coding",
            steps=["Add login endpoint", "Write tests"],
            worktree_path=wt_path,
            success=True,
            commit_on_boundary=True,
            merge_strategy="auto",
            branch_prefix="feat",
            target_branch="main",
            session_id="s1",
        ))

        assert result is not None
        assert result["merged"] is True
        assert not wt_path.exists(), "worktree should be removed after merge"
        assert not branch_exists(git_repo, branch), "feature branch should be deleted"
        assert current_branch(git_repo) == "main"
        assert (git_repo / "auth.py").exists(), "merged file should be on main"

    def test_manual_strategy_skips_merge_and_preserves_worktree(
        self, git_repo: Path
    ) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        branch, wt_path = self._make_worktree_with_commit(
            ops, git_repo, "t2", "payments", "pay.py"
        )

        result = asyncio.run(ops.apply_on_completion(
            task_id="t2",
            slug="payments",
            description="Implement payments",
            plugin_name="coding",
            steps=None,
            worktree_path=wt_path,
            success=True,
            commit_on_boundary=True,
            merge_strategy="manual",
            branch_prefix="feat",
            target_branch="main",
            session_id="s1",
        ))

        assert result is None, "manual strategy should return None (no merge)"
        assert wt_path.exists(), "worktree should be preserved for manual merge"
        assert branch_exists(git_repo, branch), "feature branch should still exist"

    def test_commit_on_boundary_false_skips_checkpoint_and_merge(
        self, git_repo: Path
    ) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        wt_result = asyncio.run(ops.create_worktree("t3", "notifications"))
        assert wt_result is not None
        _, wt_path = wt_result
        (wt_path / "notify.py").write_text("n = 1\n")

        result = asyncio.run(ops.apply_on_completion(
            task_id="t3",
            slug="notifications",
            description="Add notifications",
            plugin_name="coding",
            steps=None,
            worktree_path=wt_path,
            success=True,
            commit_on_boundary=False,
            merge_strategy="auto",
            branch_prefix="feat",
            target_branch="main",
            session_id="s1",
        ))

        assert result is None
        # No checkpoint commit should have been made — branch has no commits ahead of main
        assert not branch_has_commits_ahead(git_repo, "feat/notifications", "main"), (
            "no commits ahead of main when commit_on_boundary=False"
        )
        # File should not have landed on main (no merge)
        assert not (git_repo / "notify.py").exists(), (
            "uncommitted file should not appear on main when commit_on_boundary=False"
        )

    def test_failure_preserves_worktree_when_branch_has_commits(
        self, git_repo: Path
    ) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        _, wt_path = self._make_worktree_with_commit(
            ops, git_repo, "t4", "search", "search.py"
        )

        asyncio.run(ops.apply_on_completion(
            task_id="t4",
            slug="search",
            description="Add search",
            plugin_name="coding",
            steps=None,
            worktree_path=wt_path,
            success=False,
            commit_on_boundary=True,
            merge_strategy="auto",
            branch_prefix="feat",
            target_branch="main",
            session_id="s1",
        ))

        assert wt_path.exists(), (
            "worktree must be preserved when task fails and branch has commits ahead "
            "so the retry agent can resume from checkpoint work"
        )

    def test_failure_removes_worktree_when_no_commits_ahead(
        self, git_repo: Path
    ) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        # Create worktree but do NOT commit anything
        result = asyncio.run(ops.create_worktree("t5", "empty-task"))
        assert result is not None
        _, wt_path = result

        asyncio.run(ops.apply_on_completion(
            task_id="t5",
            slug="empty-task",
            description="Empty task",
            plugin_name="coding",
            steps=None,
            worktree_path=wt_path,
            success=False,
            commit_on_boundary=True,
            merge_strategy="auto",
            branch_prefix="feat",
            target_branch="main",
            session_id="s1",
        ))

        assert not wt_path.exists(), (
            "worktree should be removed when task fails with no committed work"
        )

    def test_git_disabled_is_noop(self, git_repo: Path) -> None:
        ops = GitOps(project_dir=git_repo, enabled=False)
        result = asyncio.run(ops.apply_on_completion(
            task_id="t6",
            slug="anything",
            description="Some task",
            plugin_name="coding",
            steps=None,
            worktree_path=None,
            success=True,
            commit_on_boundary=True,
            merge_strategy="auto",
            branch_prefix="feat",
            target_branch="main",
            session_id="s1",
        ))
        assert result is None


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
        assert result is not None
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
        assert result is not None
        assert result["merged"] is True
        # History shows the squash commit on main
        history = asyncio.run(ops.history())
        assert len(history) >= 1
        # Verify semantic message content
        latest = history[0]
        assert latest["message"] == "Implement payment processing"
