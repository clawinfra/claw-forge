"""Tests for --auto-push hook and git push_to_remote / has_remote utilities."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# ── Unit tests: git utilities ─────────────────────────────────────────────────


class TestHasRemote:
    def test_returns_true_when_remote_exists(self, tmp_path: Path) -> None:
        from claw_forge.git.commits import has_remote
        from claw_forge.git.repo import _run_git

        _run_git(["init"], tmp_path)
        _run_git(["remote", "add", "origin", "https://example.com/repo.git"], tmp_path)
        assert has_remote(tmp_path, "origin") is True

    def test_returns_false_when_remote_missing(self, tmp_path: Path) -> None:
        from claw_forge.git.commits import has_remote
        from claw_forge.git.repo import _run_git

        _run_git(["init"], tmp_path)
        assert has_remote(tmp_path, "origin") is False

    def test_returns_false_on_exception(self, tmp_path: Path) -> None:
        from claw_forge.git.commits import has_remote

        # Not a git repo
        assert has_remote(tmp_path / "nonexistent", "origin") is False


class TestPushToRemote:
    def test_returns_success_dict_on_push(self, tmp_path: Path) -> None:
        from claw_forge.git.commits import push_to_remote

        with patch("claw_forge.git.commits._run_git") as mock_git:
            mock_git.return_value = Mock(stdout="main\n")
            result = push_to_remote(tmp_path, remote="origin", branch="main")

        assert result["success"] is True
        assert result["remote"] == "origin"
        assert result["branch"] == "main"
        assert result["error"] is None

    def test_returns_failure_dict_on_error(self, tmp_path: Path) -> None:
        from claw_forge.git.commits import push_to_remote

        with patch("claw_forge.git.commits._run_git") as mock_git:
            mock_git.side_effect = subprocess.CalledProcessError(1, "git push")
            result = push_to_remote(tmp_path, remote="origin", branch="main")

        assert result["success"] is False
        assert result["error"] is not None

    def test_uses_current_branch_when_branch_not_specified(self, tmp_path: Path) -> None:
        from claw_forge.git.commits import push_to_remote

        with (
            patch("claw_forge.git.commits.current_branch", return_value="feat/my-branch"),
            patch("claw_forge.git.commits._run_git") as mock_git,
        ):
            mock_git.return_value = Mock(stdout="")
            result = push_to_remote(tmp_path, remote="origin")

        assert result["branch"] == "feat/my-branch"


# ── Unit tests: auto_push_hook ────────────────────────────────────────────────


class TestAutoPushHook:
    @pytest.mark.asyncio
    async def test_skips_when_not_git_repo(self, tmp_path: Path) -> None:
        from claw_forge.agent.hooks import auto_push_hook

        hook = auto_push_hook(str(tmp_path))
        result = await hook(input_data={}, tool_use_id=None, context=Mock())
        # Should return silently, not raise
        assert result is not None

    @pytest.mark.asyncio
    async def test_skips_when_no_remote(self, tmp_path: Path) -> None:
        from claw_forge.agent.hooks import auto_push_hook
        from claw_forge.git.repo import _run_git

        _run_git(["init"], tmp_path)
        hook = auto_push_hook(str(tmp_path))
        result = await hook(input_data={}, tool_use_id=None, context=Mock())
        assert result is not None

    @pytest.mark.asyncio
    async def test_pushes_when_remote_exists(self, tmp_path: Path) -> None:
        from claw_forge.agent.hooks import auto_push_hook

        (tmp_path / ".git").mkdir()  # fake git dir
        with (
            patch("claw_forge.git.commits.has_remote", return_value=True),
            patch("claw_forge.git.commits.push_to_remote", return_value={
                "remote": "origin", "branch": "main", "success": True, "error": None
            }) as mock_push,
        ):
            hook = auto_push_hook(str(tmp_path))
            result = await hook(input_data={}, tool_use_id=None, context=Mock())

        mock_push.assert_called_once()
        assert result is not None

    @pytest.mark.asyncio
    async def test_push_failure_does_not_raise(self, tmp_path: Path) -> None:
        from claw_forge.agent.hooks import auto_push_hook

        (tmp_path / ".git").mkdir()
        with (
            patch("claw_forge.git.commits.has_remote", return_value=True),
            patch("claw_forge.git.commits.push_to_remote", return_value={
                "remote": "origin", "branch": "main", "success": False,
                "error": "rejected: non-fast-forward"
            }),
        ):
            hook = auto_push_hook(str(tmp_path))
            # Should not raise even on push failure
            result = await hook(input_data={}, tool_use_id=None, context=Mock())

        assert result is not None


# ── Integration: get_default_hooks includes auto_push Stop hook ───────────────


class TestGetDefaultHooksAutoPush:
    def test_auto_push_none_no_stop_hook_added(self) -> None:
        from claw_forge.agent.hooks import get_default_hooks

        hooks = get_default_hooks(verify_on_exit=False, auto_push=None)
        assert "Stop" not in hooks

    def test_auto_push_path_adds_stop_hook(self, tmp_path: Path) -> None:
        from claw_forge.agent.hooks import get_default_hooks

        hooks = get_default_hooks(verify_on_exit=False, auto_push=str(tmp_path))
        assert "Stop" in hooks
        assert len(hooks["Stop"]) == 1

    def test_auto_push_with_custom_remote(self, tmp_path: Path) -> None:
        from claw_forge.agent.hooks import get_default_hooks

        hooks = get_default_hooks(
            verify_on_exit=False,
            auto_push=f"{tmp_path}:upstream",
        )
        assert "Stop" in hooks

    def test_auto_push_and_verify_on_exit_both_add_stop_hooks(self, tmp_path: Path) -> None:
        from claw_forge.agent.hooks import get_default_hooks

        hooks = get_default_hooks(verify_on_exit=True, auto_push=str(tmp_path))
        assert "Stop" in hooks
        assert len(hooks["Stop"]) == 2  # verify-on-exit + auto-push


# ── CLI: --auto-push flag appears in help ─────────────────────────────────────


class TestAutoPushCLIFlag:
    def test_auto_push_flag_in_help(self) -> None:
        import re

        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["run", "--help"])
        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "--auto-push" in clean
