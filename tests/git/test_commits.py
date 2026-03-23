"""Tests for claw_forge.git.commits — checkpoint commits with trailers, history parsing."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claw_forge.git.commits import (
    branch_commit_subjects,
    commit_checkpoint,
    has_remote,
    push_to_remote,
    task_history,
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


class TestCommitCheckpoint:
    def test_creates_commit_with_message(self, git_repo: Path) -> None:
        (git_repo / "foo.py").write_text("x = 1\n")
        result = commit_checkpoint(
            git_repo,
            message="feat(auth): add login",
            task_id="task-1",
            plugin="coding",
            phase="milestone",
            session_id="sess-1",
        )
        assert result["commit_hash"]  # non-empty short SHA
        assert len(result["commit_hash"]) >= 7

    def test_commit_contains_trailers(self, git_repo: Path) -> None:
        (git_repo / "bar.py").write_text("y = 2\n")
        commit_checkpoint(
            git_repo,
            message="feat(auth): add login",
            task_id="task-1",
            plugin="coding",
            phase="milestone",
            session_id="sess-1",
        )
        log = subprocess.run(
            ["git", "log", "-1", "--format=%B"],
            cwd=git_repo, capture_output=True, text=True, check=True,
        )
        body = log.stdout
        assert "Task-ID: task-1" in body
        assert "Plugin: coding" in body
        assert "Phase: milestone" in body
        assert "Session: sess-1" in body

    def test_no_changes_returns_none(self, git_repo: Path) -> None:
        result = commit_checkpoint(
            git_repo,
            message="feat: nothing",
            task_id="t1",
            plugin="coding",
            phase="milestone",
            session_id="s1",
        )
        assert result is None

    def test_returns_branch_name(self, git_repo: Path) -> None:
        (git_repo / "baz.py").write_text("z = 3\n")
        result = commit_checkpoint(
            git_repo,
            message="feat(auth): add login",
            task_id="task-1",
            plugin="coding",
            phase="milestone",
            session_id="sess-1",
        )
        assert result["branch"] in ("main", "master")


class TestTaskHistory:
    def test_returns_commits_for_task(self, git_repo: Path) -> None:
        (git_repo / "a.py").write_text("a = 1\n")
        commit_checkpoint(
            git_repo, message="feat: step 1",
            task_id="task-A", plugin="coding", phase="milestone", session_id="s1",
        )
        (git_repo / "b.py").write_text("b = 2\n")
        commit_checkpoint(
            git_repo, message="feat: step 2",
            task_id="task-A", plugin="testing", phase="milestone", session_id="s1",
        )
        (git_repo / "c.py").write_text("c = 3\n")
        commit_checkpoint(
            git_repo, message="feat: other task",
            task_id="task-B", plugin="coding", phase="milestone", session_id="s1",
        )
        history = task_history(git_repo, task_id="task-A")
        assert len(history) == 2
        assert all(c["trailers"]["task_id"] == "task-A" for c in history)

    def test_returns_all_when_no_task_id(self, git_repo: Path) -> None:
        (git_repo / "d.py").write_text("d = 4\n")
        commit_checkpoint(
            git_repo, message="feat: whatever",
            task_id="task-X", plugin="coding", phase="save", session_id="s1",
        )
        history = task_history(git_repo)
        assert len(history) >= 1

    def test_respects_limit(self, git_repo: Path) -> None:
        for i in range(5):
            (git_repo / f"f{i}.py").write_text(f"v = {i}\n")
            commit_checkpoint(
                git_repo, message=f"feat: step {i}",
                task_id="task-L", plugin="coding", phase="milestone", session_id="s1",
            )
        history = task_history(git_repo, task_id="task-L", limit=2)
        assert len(history) == 2

    def test_commit_has_expected_keys(self, git_repo: Path) -> None:
        (git_repo / "e.py").write_text("e = 5\n")
        commit_checkpoint(
            git_repo, message="feat: keys",
            task_id="task-K", plugin="coding", phase="milestone", session_id="s1",
        )
        history = task_history(git_repo, task_id="task-K")
        commit = history[0]
        assert "hash" in commit
        assert "message" in commit
        assert "timestamp" in commit
        assert "trailers" in commit
        assert commit["trailers"]["plugin"] == "coding"


class TestBranchCommitSubjects:
    def test_returns_subjects_from_branch(self, git_repo: Path) -> None:
        subprocess.run(
            ["git", "checkout", "-b", "feat/test"],
            cwd=git_repo, check=True, capture_output=True,
        )
        (git_repo / "a.py").write_text("a = 1\n")
        commit_checkpoint(
            git_repo, message="feat: first change",
            task_id="t1", plugin="coding", phase="coding", session_id="s1",
        )
        (git_repo / "b.py").write_text("b = 2\n")
        commit_checkpoint(
            git_repo, message="test: add tests",
            task_id="t1", plugin="testing", phase="testing", session_id="s1",
        )
        subjects = branch_commit_subjects(git_repo, "feat/test", "main")
        assert len(subjects) == 2
        assert "feat: first change" in subjects
        assert "test: add tests" in subjects

    def test_returns_empty_for_no_diff(self, git_repo: Path) -> None:
        subjects = branch_commit_subjects(git_repo, "main", "main")
        assert subjects == []

    def test_returns_empty_for_nonexistent_branch(self, git_repo: Path) -> None:
        subjects = branch_commit_subjects(git_repo, "nonexistent", "main")
        assert subjects == []


class TestPushToRemote:
    def test_push_no_remote_returns_error(self, git_repo: Path) -> None:
        result = push_to_remote(git_repo)
        assert result["success"] is False
        assert result["error"]
        assert result["branch"] == "main"

    def test_push_explicit_branch(self, git_repo: Path) -> None:
        # No remote configured — push will fail, but the branch param is passed
        result = push_to_remote(git_repo, branch="main")
        assert result["success"] is False
        assert result["branch"] == "main"

    def test_push_default_branch_detection(self, git_repo: Path) -> None:
        # When branch is None, it detects the current branch
        result = push_to_remote(git_repo)
        assert result["branch"] == "main"

    def test_push_to_local_remote_succeeds(self, git_repo: Path, tmp_path: Path) -> None:
        # Create a bare repo as a local remote
        bare = tmp_path / "bare.git"
        subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", str(bare)],
            cwd=git_repo, check=True, capture_output=True,
        )
        result = push_to_remote(git_repo, branch="main")
        assert result["success"] is True
        assert result["error"] is None


class TestHasRemote:
    def test_no_remote_returns_false(self, git_repo: Path) -> None:
        assert has_remote(git_repo) is False

    def test_has_remote_after_adding(self, git_repo: Path) -> None:
        subprocess.run(
            ["git", "remote", "add", "origin", "https://example.com/repo.git"],
            cwd=git_repo, check=True, capture_output=True,
        )
        assert has_remote(git_repo) is True

    def test_has_remote_wrong_name(self, git_repo: Path) -> None:
        subprocess.run(
            ["git", "remote", "add", "upstream", "https://example.com/repo.git"],
            cwd=git_repo, check=True, capture_output=True,
        )
        assert has_remote(git_repo, "origin") is False
        assert has_remote(git_repo, "upstream") is True

    def test_has_remote_nonrepo_returns_false(self, tmp_path: Path) -> None:
        assert has_remote(tmp_path) is False


class TestTaskHistoryEdgeCases:
    def test_history_on_nonrepo_returns_empty(self, tmp_path: Path) -> None:
        result = task_history(tmp_path)
        assert result == []

    def test_history_empty_hash_skipped(self, git_repo: Path) -> None:
        # The initial commit already exists; just verify parsing works
        history = task_history(git_repo, limit=100)
        # All returned commits should have non-empty hashes
        for commit in history:
            assert commit["hash"]

    def test_history_malformed_entries_skipped(self, git_repo: Path) -> None:
        """Verify that malformed log entries (< 4 parts) are skipped."""
        from unittest.mock import Mock, patch

        # Mock _run_git to return a malformed log entry
        mock_result = Mock()
        # Two entries: one malformed (too few separators) and one valid
        sep = "---COMMIT-SEP---"
        mock_result.stdout = (
            f"abc1234{sep}good msg{sep}2024-01-01T00:00:00{sep}body{sep}\n"
            f"short{sep}bad\n"  # malformed — fewer than 4 parts
        )
        with patch("claw_forge.git.commits._run_git", return_value=mock_result):
            history = task_history(git_repo)
        assert len(history) == 1
        assert history[0]["message"] == "good msg"

    def test_history_empty_hash_entry_skipped(self, git_repo: Path) -> None:
        """Entries where full_hash is empty after stripping are skipped."""
        from unittest.mock import Mock, patch

        mock_result = Mock()
        sep = "---COMMIT-SEP---"
        mock_result.stdout = (
            f"  {sep}empty hash{sep}2024-01-01{sep}body{sep}\n"
        )
        with patch("claw_forge.git.commits._run_git", return_value=mock_result):
            history = task_history(git_repo)
        assert history == []
