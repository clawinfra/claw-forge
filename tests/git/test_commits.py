"""Tests for claw_forge.git.commits — checkpoint commits with trailers, history parsing."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claw_forge.git.commits import commit_checkpoint, task_history


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
