"""Tests for claw_forge.git — public API re-exports and GitOps lock."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from claw_forge.git import GitOps


@pytest.fixture()
def git_ops(tmp_path: Path) -> GitOps:
    return GitOps(project_dir=tmp_path, enabled=True)


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


class TestGitOps:
    def test_disabled_init_is_noop(self, tmp_path: Path) -> None:
        ops = GitOps(project_dir=tmp_path, enabled=False)
        result = asyncio.run(ops.init())
        assert result is None

    def test_disabled_checkpoint_is_noop(self, tmp_path: Path) -> None:
        ops = GitOps(project_dir=tmp_path, enabled=False)
        result = asyncio.run(ops.checkpoint(
            message="test", task_id="t1", plugin="coding",
            phase="milestone", session_id="s1",
        ))
        assert result is None

    def test_disabled_merge_is_noop(self, tmp_path: Path) -> None:
        ops = GitOps(project_dir=tmp_path, enabled=False)
        result = asyncio.run(ops.merge("feat/test"))
        assert result is None

    def test_disabled_create_branch_is_noop(self, tmp_path: Path) -> None:
        ops = GitOps(project_dir=tmp_path, enabled=False)
        result = asyncio.run(ops.create_branch("t1", "auth"))
        assert result is None

    @patch("claw_forge.git.init_or_detect")
    @patch("claw_forge.git.prune_worktrees", return_value=0)
    def test_enabled_init_calls_init_or_detect(
        self, mock_prune, mock_init, tmp_path: Path,
    ) -> None:
        mock_init.return_value = {"initialized": True, "default_branch": "main"}
        ops = GitOps(project_dir=tmp_path, enabled=True)
        result = asyncio.run(ops.init())
        mock_init.assert_called_once_with(tmp_path)
        assert result["initialized"] is True

    def test_lock_serializes_operations(self, tmp_path: Path) -> None:
        ops = GitOps(project_dir=tmp_path, enabled=True)
        assert isinstance(ops._lock, asyncio.Lock)


class TestGitOpsWorktree:
    def test_disabled_create_worktree_is_noop(self, tmp_path: Path) -> None:
        ops = GitOps(project_dir=tmp_path, enabled=False)
        result = asyncio.run(ops.create_worktree("t1", "auth"))
        assert result is None

    def test_disabled_remove_worktree_is_noop(self, tmp_path: Path) -> None:
        ops = GitOps(project_dir=tmp_path, enabled=False)
        # Should not raise
        asyncio.run(ops.remove_worktree(tmp_path / "nonexistent"))

    def test_enabled_remove_worktree(self, git_repo: Path) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        result = asyncio.run(ops.create_worktree("t1", "remove-me"))
        assert result is not None
        _, wt_path = result
        assert wt_path.is_dir()
        asyncio.run(ops.remove_worktree(wt_path))
        assert not wt_path.exists()

    def test_disabled_history_is_empty(self, tmp_path: Path) -> None:
        ops = GitOps(project_dir=tmp_path, enabled=False)
        result = asyncio.run(ops.history())
        assert result == []

    def test_create_worktree_returns_tuple(self, git_repo: Path) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        result = asyncio.run(ops.create_worktree("t1", "payments"))
        assert result is not None
        branch, wt_path = result
        assert branch == "feat/payments"
        assert wt_path.is_dir()

    def test_checkpoint_with_cwd_uses_worktree_dir(self, git_repo: Path) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        result = asyncio.run(ops.create_worktree("t1", "cwd-test"))
        assert result is not None
        _, wt_path = result

        (wt_path / "new_file.py").write_text("x = 1\n")
        cp = asyncio.run(ops.checkpoint(
            message="test cwd", task_id="t1", plugin="coding",
            phase="coding", session_id="s1", cwd=wt_path,
        ))
        assert cp is not None
        assert cp["branch"] == "feat/cwd-test"

    def test_checkpoint_without_cwd_uses_project_dir(self, git_repo: Path) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        # Add a file and commit on main (no worktree)
        (git_repo / "direct.py").write_text("y = 2\n")
        cp = asyncio.run(ops.checkpoint(
            message="direct commit", task_id="t1", plugin="coding",
            phase="coding", session_id="s1",
        ))
        assert cp is not None
        assert cp["branch"] == "main"

    def test_merge_passes_worktree_path(self, git_repo: Path) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        wt_result = asyncio.run(ops.create_worktree("t1", "merge-wt"))
        assert wt_result is not None
        branch, wt_path = wt_result

        (wt_path / "merged.py").write_text("z = 3\n")
        asyncio.run(ops.checkpoint(
            message="add merged.py", task_id="t1", plugin="coding",
            phase="coding", session_id="s1", cwd=wt_path,
        ))

        result = asyncio.run(ops.merge(
            branch, title="Merge test",
            task_id="t1", session_id="s1",
            worktree_path=wt_path,
        ))
        assert result is not None
        assert result["merged"] is True
        assert not wt_path.exists()

    @patch("claw_forge.git.init_or_detect")
    @patch("claw_forge.git.prune_worktrees", return_value=3)
    def test_init_prunes_stale_worktrees(
        self, mock_prune, mock_init, tmp_path: Path,
    ) -> None:
        mock_init.return_value = {"initialized": False, "default_branch": "main"}
        ops = GitOps(project_dir=tmp_path, enabled=True)
        result = asyncio.run(ops.init())
        mock_prune.assert_called_once_with(tmp_path)
        assert result is not None
        assert result["pruned_worktrees"] == 3

    @patch("claw_forge.git.init_or_detect")
    @patch("claw_forge.git.prune_worktrees", return_value=0)
    def test_init_no_pruned_key_when_zero(
        self, mock_prune, mock_init, tmp_path: Path,
    ) -> None:
        mock_init.return_value = {"initialized": True, "default_branch": "main"}
        ops = GitOps(project_dir=tmp_path, enabled=True)
        result = asyncio.run(ops.init())
        assert result is not None
        assert "pruned_worktrees" not in result

    def test_history_with_cwd(self, git_repo: Path) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        wt_result = asyncio.run(ops.create_worktree("t1", "hist-test"))
        assert wt_result is not None
        _, wt_path = wt_result

        (wt_path / "hist.py").write_text("h = 1\n")
        asyncio.run(ops.checkpoint(
            message="history checkpoint", task_id="t1", plugin="coding",
            phase="coding", session_id="s1", cwd=wt_path,
        ))

        history = asyncio.run(ops.history(cwd=wt_path))
        assert len(history) >= 1
        assert any("history checkpoint" in c["message"] for c in history)
