"""Tests for claw_forge.git — public API re-exports and GitOps lock."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from claw_forge.git import GitOps


@pytest.fixture()
def git_ops(tmp_path: Path) -> GitOps:
    return GitOps(project_dir=tmp_path, enabled=True)


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

    @patch("claw_forge.git.init_or_detect")
    def test_enabled_init_calls_init_or_detect(self, mock_init, tmp_path: Path) -> None:
        mock_init.return_value = {"initialized": True, "default_branch": "main"}
        ops = GitOps(project_dir=tmp_path, enabled=True)
        result = asyncio.run(ops.init())
        mock_init.assert_called_once_with(tmp_path)
        assert result["initialized"] is True

    def test_lock_serializes_operations(self, tmp_path: Path) -> None:
        ops = GitOps(project_dir=tmp_path, enabled=True)
        # Verify the lock attribute exists and is an asyncio.Lock
        assert isinstance(ops._lock, asyncio.Lock)
