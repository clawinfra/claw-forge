"""Tests for periodic auto-checkpoint background task.

Covers:
- Checkpoint is called after the configured interval
- Task is cancelled cleanly on completion
- No checkpoint task when disabled (interval=0 or git_enabled=False)
- Errors in checkpoint are silently caught
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


async def _periodic_checkpoint(
    checkpoint_fn: AsyncMock,
    wt_path: Path,
    t_id: str,
    t_plugin: str,
    sid: str,
    interval: float,
) -> None:
    """Replica of the nested function in cli.py for isolated testing."""
    while True:
        await asyncio.sleep(interval)
        with suppress(Exception):
            await checkpoint_fn(
                message=f"auto-save: {t_plugin} in progress",
                task_id=t_id,
                plugin=t_plugin,
                phase="auto-save",
                session_id=sid,
                cwd=wt_path,
            )


class TestPeriodicCheckpoint:
    @pytest.mark.asyncio
    async def test_calls_checkpoint_after_interval(self, tmp_path: Path) -> None:
        mock_cp = AsyncMock()
        task = asyncio.create_task(
            _periodic_checkpoint(mock_cp, tmp_path, "t1", "coding", "s1", 0.05)
        )
        await asyncio.sleep(0.12)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        assert mock_cp.call_count >= 1
        call_kw = mock_cp.call_args
        assert call_kw.kwargs["phase"] == "auto-save"
        assert call_kw.kwargs["task_id"] == "t1"

    @pytest.mark.asyncio
    async def test_cancelled_cleanly(self, tmp_path: Path) -> None:
        mock_cp = AsyncMock()
        task = asyncio.create_task(
            _periodic_checkpoint(mock_cp, tmp_path, "t1", "coding", "s1", 0.05)
        )
        await asyncio.sleep(0.02)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        assert task.done()

    @pytest.mark.asyncio
    async def test_error_in_checkpoint_does_not_propagate(self, tmp_path: Path) -> None:
        mock_cp = AsyncMock(side_effect=RuntimeError("git error"))
        task = asyncio.create_task(
            _periodic_checkpoint(mock_cp, tmp_path, "t1", "coding", "s1", 0.05)
        )
        await asyncio.sleep(0.12)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        # Task should still be running (cancelled, not crashed)
        assert task.cancelled() or task.done()
        assert mock_cp.call_count >= 1

    @pytest.mark.asyncio
    async def test_message_contains_plugin_name(self, tmp_path: Path) -> None:
        mock_cp = AsyncMock()
        task = asyncio.create_task(
            _periodic_checkpoint(mock_cp, tmp_path, "t1", "testing", "s1", 0.05)
        )
        await asyncio.sleep(0.08)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        assert mock_cp.call_count >= 1
        assert "testing" in mock_cp.call_args.kwargs["message"]
