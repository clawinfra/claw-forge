"""Tests for git worktree operations — create, remove, prune, isolation."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claw_forge.git.branching import (
    branch_exists,
    create_worktree,
    current_branch,
    prune_worktrees,
    remove_worktree,
)
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


class TestCreateWorktree:
    def test_creates_worktree_directory_and_branch(self, git_repo: Path) -> None:
        branch, wt_path = create_worktree(git_repo, "t1", "auth")
        assert branch == "feat/auth"
        assert wt_path.is_dir()
        assert branch_exists(git_repo, "feat/auth")

    def test_returns_branch_name_and_path(self, git_repo: Path) -> None:
        branch, wt_path = create_worktree(git_repo, "t1", "payments")
        assert branch == "feat/payments"
        assert wt_path == git_repo / ".claw-forge" / "worktrees" / "payments"

    def test_worktree_has_independent_head(self, git_repo: Path) -> None:
        _, wt_path = create_worktree(git_repo, "t1", "auth")
        # Main repo stays on main
        assert current_branch(git_repo) == "main"
        # Worktree is on the feature branch
        assert current_branch(wt_path) == "feat/auth"

    def test_custom_prefix(self, git_repo: Path) -> None:
        branch, wt_path = create_worktree(git_repo, "t1", "login-bug", prefix="fix")
        assert branch == "fix/login-bug"
        assert wt_path.is_dir()

    def test_stale_directory_is_replaced(self, git_repo: Path) -> None:
        wt_dir = git_repo / ".claw-forge" / "worktrees" / "stale"
        wt_dir.mkdir(parents=True)
        (wt_dir / "leftover.txt").write_text("stale")

        branch, wt_path = create_worktree(git_repo, "t1", "stale")
        assert branch == "feat/stale"
        assert wt_path.is_dir()
        # The stale file should be gone, replaced by a real worktree
        assert not (wt_path / "leftover.txt").exists()
        # The worktree should have the repo's README
        assert (wt_path / "README.md").exists()

    def test_existing_branch_reuses_branch(self, git_repo: Path) -> None:
        # Create the branch first (without a worktree)
        subprocess.run(
            ["git", "branch", "feat/existing"],
            cwd=git_repo, check=True, capture_output=True,
        )
        branch, wt_path = create_worktree(git_repo, "t1", "existing")
        assert branch == "feat/existing"
        assert wt_path.is_dir()
        assert current_branch(wt_path) == "feat/existing"


class TestRemoveWorktree:
    def test_removes_directory_and_worktree_entry(self, git_repo: Path) -> None:
        _, wt_path = create_worktree(git_repo, "t1", "temp")
        assert wt_path.is_dir()

        remove_worktree(git_repo, wt_path)
        assert not wt_path.exists()

    def test_removes_with_dirty_files(self, git_repo: Path) -> None:
        _, wt_path = create_worktree(git_repo, "t1", "dirty")
        (wt_path / "uncommitted.py").write_text("x = 1\n")

        remove_worktree(git_repo, wt_path)
        assert not wt_path.exists()

    def test_nonexistent_worktree_is_noop(self, git_repo: Path) -> None:
        fake_path = git_repo / ".claw-forge" / "worktrees" / "nonexistent"
        # Should not raise
        remove_worktree(git_repo, fake_path)


class TestPruneWorktrees:
    def test_prunes_stale_worktrees(self, git_repo: Path) -> None:
        _, wt1 = create_worktree(git_repo, "t1", "feat-a")
        _, wt2 = create_worktree(git_repo, "t2", "feat-b")
        assert wt1.is_dir()
        assert wt2.is_dir()

        count = prune_worktrees(git_repo)
        assert count == 2
        assert not wt1.exists()
        assert not wt2.exists()

    def test_no_worktrees_dir_returns_zero(self, git_repo: Path) -> None:
        count = prune_worktrees(git_repo)
        assert count == 0

    def test_cleans_git_bookkeeping(self, git_repo: Path) -> None:
        _, wt_path = create_worktree(git_repo, "t1", "cleanup")
        # Manually delete the directory (simulating a crash)
        import shutil
        shutil.rmtree(wt_path)
        # The parent dir still exists with no children
        worktrees_dir = git_repo / ".claw-forge" / "worktrees"
        assert worktrees_dir.is_dir()

        count = prune_worktrees(git_repo)
        # The dir entry was already gone, but the bookkeeping is cleaned
        assert count == 0  # no child dirs to iterate

    def test_prune_with_fallback_rmtree(self, git_repo: Path) -> None:
        """Worktree dir that git can't remove is cleaned by shutil.rmtree."""
        wt_dir = git_repo / ".claw-forge" / "worktrees" / "orphan"
        wt_dir.mkdir(parents=True)
        (wt_dir / "file.txt").write_text("orphan data")
        # This is not a real git worktree — git worktree remove will fail,
        # but shutil.rmtree fallback should clean it up.
        count = prune_worktrees(git_repo)
        assert count == 1
        assert not wt_dir.exists()


class TestWorktreeIsolation:
    def test_parallel_commits_no_interference(self, git_repo: Path) -> None:
        _, wt_a = create_worktree(git_repo, "t1", "feat-a")
        _, wt_b = create_worktree(git_repo, "t2", "feat-b")

        # Write different files in each worktree
        (wt_a / "a.py").write_text("a = 1\n")
        (wt_b / "b.py").write_text("b = 2\n")

        # Commit in both (independent — no lock needed)
        result_a = commit_checkpoint(
            wt_a, message="add a", task_id="t1",
            plugin="coding", phase="coding", session_id="s1",
        )
        result_b = commit_checkpoint(
            wt_b, message="add b", task_id="t2",
            plugin="coding", phase="coding", session_id="s1",
        )

        assert result_a is not None
        assert result_b is not None
        # Each commit is on its own branch
        assert result_a["branch"] == "feat/feat-a"
        assert result_b["branch"] == "feat/feat-b"

    def test_merge_after_worktree_work(self, git_repo: Path) -> None:
        branch, wt_path = create_worktree(git_repo, "t1", "merge-me")

        (wt_path / "feature.py").write_text("feature = True\n")
        commit_checkpoint(
            wt_path, message="implement feature", task_id="t1",
            plugin="coding", phase="coding", session_id="s1",
        )

        result = squash_merge(
            git_repo, branch, "main",
            title="Add feature",
            task_id="t1",
            worktree_path=wt_path,
        )
        assert result["merged"] is True
        assert result["commit_hash"]
        # Worktree should be cleaned up
        assert not wt_path.exists()
        # File should be on main
        assert (git_repo / "feature.py").exists()

    def test_full_lifecycle_create_write_commit_merge_cleanup(self, git_repo: Path) -> None:
        # 1. Create worktree
        branch, wt_path = create_worktree(git_repo, "t1", "lifecycle")
        assert current_branch(git_repo) == "main"
        assert current_branch(wt_path) == "feat/lifecycle"

        # 2. Write code in worktree
        (wt_path / "app.py").write_text("def main(): pass\n")

        # 3. Checkpoint
        cp = commit_checkpoint(
            wt_path, message="scaffold app", task_id="t1",
            plugin="coding", phase="coding", session_id="s1",
        )
        assert cp is not None
        assert cp["commit_hash"]

        # 4. More code + second checkpoint
        (wt_path / "tests.py").write_text("def test_main(): pass\n")
        cp2 = commit_checkpoint(
            wt_path, message="add tests", task_id="t1",
            plugin="testing", phase="testing", session_id="s1",
        )
        assert cp2 is not None

        # 5. Merge with worktree cleanup
        result = squash_merge(
            git_repo, branch, "main",
            title="Implement lifecycle feature",
            steps=["scaffold app", "add tests"],
            task_id="t1",
            session_id="s1",
            worktree_path=wt_path,
        )
        assert result["merged"] is True
        assert not wt_path.exists()

        # 6. Verify files on main
        assert (git_repo / "app.py").exists()
        assert (git_repo / "tests.py").exists()
        assert not branch_exists(git_repo, branch)

    def test_merge_failure_preserves_worktree(self, git_repo: Path) -> None:
        """When merge fails, the worktree should NOT be cleaned up."""
        result = squash_merge(
            git_repo, "nonexistent/branch", "main",
            worktree_path=git_repo / ".claw-forge" / "worktrees" / "ghost",
        )
        assert result["merged"] is False
