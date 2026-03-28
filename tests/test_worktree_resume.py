"""Tests for worktree resume-after-interrupt and orphan salvage behaviour.

Covers:
- create_worktree reuses existing branch with commits (resume path)
- create_worktree nukes empty/stale branch (fresh path)
- branch_has_commits_ahead helper
- merge_orphaned_worktrees salvages partial commits to main
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from claw_forge.git.branching import (
    branch_exists,
    branch_has_commits_ahead,
    create_worktree,
    merge_orphaned_worktrees,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    result.check_returncode()
    return result.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    """Create a git repo with an initial commit on main."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.email", "test@example.com"], repo)
    _git(["config", "user.name", "Test"], repo)
    (repo / "README.md").write_text("init\n")
    _git(["add", "."], repo)
    _git(["commit", "-m", "init"], repo)
    return repo


def _add_commit(repo: Path, filename: str, message: str) -> None:
    """Add a file and commit it in the current working directory context."""
    (repo / filename).write_text(f"{message}\n")
    _git(["add", "."], repo)
    _git(["commit", "-m", message], repo)


def _add_commit_in_worktree(worktree: Path, repo: Path, filename: str, message: str) -> None:
    """Add a file and commit it inside a worktree."""
    (worktree / filename).write_text(f"{message}\n")
    _git(["add", "."], worktree)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=worktree,
        env={**os.environ, "GIT_AUTHOR_EMAIL": "test@example.com",
             "GIT_AUTHOR_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
             "GIT_COMMITTER_NAME": "Test"},
        capture_output=True,
        check=True,
    )


# ── branch_has_commits_ahead ─────────────────────────────────────────────────


class TestBranchHasCommitsAhead:
    def test_no_commits_returns_false(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        # Create branch with no additional commits
        _git(["checkout", "-b", "feat/empty"], repo)
        _git(["checkout", "main"], repo)
        assert branch_has_commits_ahead(repo, "feat/empty", "main") is False

    def test_with_commits_returns_true(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        _git(["checkout", "-b", "feat/work"], repo)
        _add_commit(repo, "work.txt", "wip: partial work")
        _git(["checkout", "main"], repo)
        assert branch_has_commits_ahead(repo, "feat/work", "main") is True

    def test_nonexistent_branch_returns_false(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        assert branch_has_commits_ahead(repo, "feat/ghost", "main") is False


# ── create_worktree — resume path ────────────────────────────────────────────


class TestCreateWorktreeResume:
    def test_reuses_worktree_with_commits(self, tmp_path: Path) -> None:
        """If branch has commits, existing worktree dir is reused unchanged."""
        repo = _init_repo(tmp_path)

        # Simulate first run: create worktree and commit some work
        branch, wt_path = create_worktree(repo, "task-1", "task-1", base_branch="main")
        _add_commit_in_worktree(wt_path, repo, "partial.txt", "wip: partial work")

        # Record the file's mtime so we can verify it wasn't touched
        mtime_before = (wt_path / "partial.txt").stat().st_mtime

        # Go back to main (as if the process died)
        _git(["checkout", "main"], repo)

        # Simulate resume: call create_worktree again for same slug
        branch2, wt_path2 = create_worktree(repo, "task-1", "task-1", base_branch="main")

        assert branch2 == branch
        assert wt_path2 == wt_path
        # File must still be there — not nuked
        assert (wt_path / "partial.txt").exists()
        assert (wt_path / "partial.txt").stat().st_mtime == mtime_before

    def test_nukes_empty_branch_on_fresh_run(self, tmp_path: Path) -> None:
        """If branch has no commits ahead of main, worktree is recreated fresh."""
        repo = _init_repo(tmp_path)

        # Create worktree but don't commit anything
        branch, wt_path = create_worktree(repo, "task-2", "task-2", base_branch="main")
        # Stash a sentinel file manually (not committed)
        sentinel = wt_path / "sentinel.txt"
        sentinel.write_text("I should be gone on resume\n")

        _git(["checkout", "main"], repo)

        # Resume: no commits → fresh worktree
        branch2, wt_path2 = create_worktree(repo, "task-2", "task-2", base_branch="main")
        assert branch2 == branch
        # Sentinel gone because directory was nuked
        assert not sentinel.exists()

    def test_relinks_worktree_when_dir_missing(self, tmp_path: Path) -> None:
        """Branch exists with commits but worktree dir was pruned → re-link."""
        repo = _init_repo(tmp_path)

        branch, wt_path = create_worktree(repo, "task-3", "task-3", base_branch="main")
        _add_commit_in_worktree(wt_path, repo, "work.rs", "feat: some work")

        _git(["checkout", "main"], repo)

        # Simulate OS pruning the worktree dir but git branch survives
        import shutil
        _git(["worktree", "remove", "--force", str(wt_path)], repo)
        if wt_path.exists():
            shutil.rmtree(wt_path)

        assert not wt_path.exists()
        assert branch_exists(repo, branch)

        # Resume should re-link without error
        branch2, wt_path2 = create_worktree(repo, "task-3", "task-3", base_branch="main")
        assert wt_path2 == wt_path
        assert wt_path2.exists()
        # The commit on the branch is accessible in the re-linked worktree
        log = _git(["log", "--oneline", "-1"], wt_path2)
        assert "some work" in log


# ── merge_orphaned_worktrees ─────────────────────────────────────────────────


class TestMergeOrphanedWorktrees:
    def test_salvages_commits_to_main(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)

        # Simulate a killed agent: worktree created, work committed, process died
        branch, wt_path = create_worktree(repo, "task-4", "task-4", base_branch="main")
        _add_commit_in_worktree(wt_path, repo, "feature.py", "feat: salvageable work")
        _git(["checkout", "main"], repo)

        salvaged = merge_orphaned_worktrees(repo, prefix="feat", target="main")

        assert branch in salvaged
        # The salvage commit must be on main
        log = _git(["log", "--oneline", "main"], repo)
        assert "salvage" in log

    def test_skips_empty_branches(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)

        # Worktree with zero commits ahead of main
        create_worktree(repo, "task-5", "task-5", base_branch="main")
        _git(["checkout", "main"], repo)

        salvaged = merge_orphaned_worktrees(repo, prefix="feat", target="main")
        assert salvaged == []

    def test_no_worktrees_dir_returns_empty(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        # No .claw-forge/worktrees directory at all
        salvaged = merge_orphaned_worktrees(repo, prefix="feat", target="main")
        assert salvaged == []

    def test_multiple_orphaned_worktrees_all_merged(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)

        for i in range(3):
            _, wt = create_worktree(repo, f"task-{i}", f"task-{i}", base_branch="main")
            _add_commit_in_worktree(wt, repo, f"file{i}.py", f"feat: work {i}")
        _git(["checkout", "main"], repo)

        salvaged = merge_orphaned_worktrees(repo, prefix="feat", target="main")
        assert len(salvaged) == 3
