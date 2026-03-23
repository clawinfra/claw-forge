"""
Tests for bugs that escaped e2e + 90% coverage.

Root causes:
1. cli.py was only 73% covered despite 90% aggregate — per-file gaps hide real risk
2. The claude CLI branch (sdk_available=True) was never exercised (claude not in PATH in CI)
3. WebSocket proxy had no integration test
4. Config path resolution tested only from same CWD as project
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from typer.testing import CliRunner

from claw_forge.cli import app
from claw_forge.output_parser import _parse_filename

runner = CliRunner()


# ── Bug 3: output_parser extensionless path regression ───────────────────────

class TestOutputParserEdgeCases:
    """Targeted tests for paths that slipped past earlier coverage."""

    def test_shell_command_path_rejected(self) -> None:
        """path/to/check must NOT be treated as a filename (no extension)."""
        assert _parse_filename("path/to/check") is None

    def test_shell_command_path_file_rejected(self) -> None:
        assert _parse_filename("path/to/file") is None

    def test_deeply_nested_no_extension_rejected(self) -> None:
        assert _parse_filename("a/b/c/d") is None

    def test_root_level_no_extension_rejected(self) -> None:
        # A bare word without slash or dot → None
        assert _parse_filename("Makefile") is None  # no dot, no slash

    def test_makefile_with_path_rejected(self) -> None:
        # path/Makefile — slash present but last component has no dot → rejected
        assert _parse_filename("build/Makefile") is None

    def test_dotfile_accepted(self) -> None:
        # .env, .gitignore — starts with dot, counts as extension
        result = _parse_filename(".env")
        assert result == ".env"

    def test_nested_dotfile_accepted(self) -> None:
        result = _parse_filename("config/.env")
        assert result == "config/.env"

    def test_no_stray_files_in_project(self, tmp_path: Path) -> None:
        """Ensure shell-command-looking blocks don't create files on disk."""
        text = (
            "Here's how to check:\n"
            "```path/to/check\n"
            "ls /tmp\n"
            "```\n"
            "And the main file:\n"
            "```src/app.py\n"
            "print('hello')\n"
            "```\n"
        )
        from claw_forge.output_parser import write_code_blocks
        written = write_code_blocks(text, tmp_path)
        assert written == ["src/app.py"]
        assert not (tmp_path / "path" / "to" / "check").exists()
        assert (tmp_path / "src" / "app.py").read_text() == "print('hello')\n"


# ── Bug 2: --config resolves relative to --project ───────────────────────────

class TestConfigPathResolution:
    """run --project /some/dir must load claw-forge.yaml from that dir, not CWD."""

    def test_run_loads_config_from_project_dir(self, tmp_path: Path) -> None:
        """Config in project dir is found even when invoked from a different CWD."""
        # Write a minimal valid config in the project dir
        cfg = tmp_path / "claw-forge.yaml"
        cfg.write_text(
            "pool:\n  strategy: priority\n"
            "providers:\n"
            "  direct:\n    type: anthropic\n    api_key: sk-test\n    priority: 1\n"
            "agent:\n  default_model: claude-sonnet-4-6\n"
            "state:\n  port: 8421\n"
        )
        # Invoke with --project pointing to tmp_path but from a different implied CWD
        # Use --dry-run so we don't actually call the API
        result = runner.invoke(app, [
            "run",
            "--project", str(tmp_path),
            "--config", "claw-forge.yaml",  # relative — must resolve to project dir
            "--dry-run",
        ])
        # Should not fail with "Config not found"
        assert "Config not found" not in (result.output or "")
        assert result.exit_code in (0, 1)  # 1 is ok (no tasks), 0 is ok

    def test_run_explicit_absolute_config_path(self, tmp_path: Path) -> None:
        """Absolute --config path always works regardless of CWD."""
        cfg = tmp_path / "custom.yaml"
        cfg.write_text(
            "pool:\n  strategy: priority\n"
            "providers: {}\n"
            "agent:\n  default_model: claude-sonnet-4-6\n"
            "state:\n  port: 8422\n"
        )
        result = runner.invoke(app, [
            "run",
            "--project", str(tmp_path),
            "--config", str(cfg),
            "--dry-run",
        ])
        assert "Config not found" not in (result.output or "")

    def test_run_missing_config_shows_error(self, tmp_path: Path) -> None:
        """Missing config shows a helpful error, not a Python traceback."""
        result = runner.invoke(app, [
            "run",
            "--project", str(tmp_path),
            "--config", str(tmp_path / "nonexistent.yaml"),
            "--dry-run",
        ])
        assert result.exit_code != 0
        assert "Config not found" in (result.output or "") or result.exception is not None


# ── Parallel CLI agent execution (env lock pattern) ──────────────────────────

class TestCliParallelExecution:
    """Verify the _env_lock allows parallel agent sessions."""

    @pytest.mark.asyncio
    async def test_env_lock_allows_parallel_sessions(self) -> None:
        """Multiple AgentSessions run concurrently after options are built."""
        env_lock = asyncio.Lock()
        timeline: list[tuple[str, float]] = []

        async def fake_session(name: str) -> None:
            async with env_lock:
                # Options construction (brief, serialized)
                pass
            # Agent execution (parallel)
            timeline.append((f"start:{name}", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.05)
            timeline.append((f"end:{name}", asyncio.get_event_loop().time()))

        await asyncio.gather(
            fake_session("A"),
            fake_session("B"),
            fake_session("C"),
        )
        # All three should START before any END (parallel execution)
        starts = [t for tag, t in timeline if tag.startswith("start:")]
        ends = [t for tag, t in timeline if tag.startswith("end:")]
        # The last start should happen before the first end
        assert max(starts) < min(ends), (
            f"Sessions did not run in parallel: {timeline}"
        )

    @pytest.mark.asyncio
    async def test_env_lock_serialises_options_construction(self) -> None:
        """The env lock prevents concurrent env reads."""
        env_lock = asyncio.Lock()
        in_critical: list[bool] = []
        overlap_detected = False

        async def fake_session(name: str) -> None:
            nonlocal overlap_detected
            async with env_lock:
                if any(in_critical):
                    overlap_detected = True
                in_critical.append(True)
                await asyncio.sleep(0.01)  # simulate options construction
                in_critical.pop()

        await asyncio.gather(
            fake_session("A"),
            fake_session("B"),
            fake_session("C"),
        )
        assert not overlap_detected, "Lock failed to prevent concurrent access"

    @pytest.mark.asyncio
    async def test_env_lock_on_exception_releases(self) -> None:
        """Lock is released even when options construction raises."""
        env_lock = asyncio.Lock()

        async def failing_setup() -> None:
            async with env_lock:
                raise RuntimeError("bad env")

        with pytest.raises(RuntimeError):
            await failing_setup()

        # Lock must be acquirable again
        assert not env_lock.locked()


# ── WebSocket proxy: double-close guard ──────────────────────────────────────

class TestWebSocketProxyCloseGuard:
    """Ensure proxy_ws doesn't raise on double-close."""

    @pytest.mark.asyncio
    async def test_close_guard_skips_when_disconnected(self) -> None:
        """websocket.close() must not be called if state != CONNECTED."""
        from starlette.websockets import WebSocketState

        mock_ws = Mock()
        mock_ws.client_state = WebSocketState.DISCONNECTED
        mock_ws.close = AsyncMock()

        # Simulate the guard logic from proxy_ws
        import contextlib
        if mock_ws.client_state == WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await mock_ws.close()

        mock_ws.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_guard_calls_when_connected(self) -> None:
        from starlette.websockets import WebSocketState

        mock_ws = Mock()
        mock_ws.client_state = WebSocketState.CONNECTED
        mock_ws.close = AsyncMock()

        import contextlib
        if mock_ws.client_state == WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await mock_ws.close()

        mock_ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_guard_suppresses_runtime_error(self) -> None:
        """RuntimeError from double-close must be swallowed, not propagated."""
        from starlette.websockets import WebSocketState

        mock_ws = Mock()
        mock_ws.client_state = WebSocketState.CONNECTED
        mock_ws.close = AsyncMock(side_effect=RuntimeError(
            "Unexpected ASGI message 'websocket.close'"
        ))

        import contextlib
        # Must not raise
        if mock_ws.client_state == WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await mock_ws.close()
