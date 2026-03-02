"""Tests for YOLO mode dispatcher behaviour."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from claw_forge.orchestrator.dispatcher import Dispatcher, DispatcherConfig
from claw_forge.state.scheduler import TaskNode


# ── Fixtures ──────────────────────────────────────────────────────────────────


async def _simple_handler(task: TaskNode) -> dict:
    return {"status": "done", "task": task.id}


async def _needs_human_handler(task: TaskNode) -> dict:
    """Simulates an agent that would block on needs_human, but in YOLO just runs."""
    return {"status": "done", "task": task.id, "was_human": task.status}


# ── DispatcherConfig tests ─────────────────────────────────────────────────────


class TestDispatcherConfig:
    def test_default_config(self) -> None:
        cfg = DispatcherConfig()
        assert cfg.yolo is False
        assert cfg.max_concurrency == 5
        assert cfg.retry_attempts == 3

    def test_yolo_sets_cpu_count(self) -> None:
        cpu = max(1, os.cpu_count() or 4)
        cfg = DispatcherConfig(yolo=True)
        assert cfg.yolo is True
        assert cfg.max_concurrency == cpu

    def test_yolo_sets_aggressive_retry(self) -> None:
        cfg = DispatcherConfig(yolo=True)
        assert cfg.retry_attempts == 5

    def test_custom_max_concurrency_without_yolo(self) -> None:
        cfg = DispatcherConfig(max_concurrency=8, retry_attempts=2)
        assert cfg.max_concurrency == 8
        assert cfg.retry_attempts == 2

    def test_yolo_overrides_max_concurrency_arg(self) -> None:
        """YOLO ignores the explicit max_concurrency arg and uses CPU count."""
        cpu = max(1, os.cpu_count() or 4)
        cfg = DispatcherConfig(max_concurrency=1, yolo=True)
        assert cfg.max_concurrency == cpu


# ── Dispatcher YOLO flag propagation ─────────────────────────────────────────


class TestDispatcherYoloFlag:
    def test_yolo_flag_accessible(self) -> None:
        d = Dispatcher(handler=_simple_handler, yolo=True)
        assert d.yolo is True

    def test_yolo_false_by_default(self) -> None:
        d = Dispatcher(handler=_simple_handler)
        assert d.yolo is False

    def test_yolo_sets_cpu_concurrency(self) -> None:
        cpu = max(1, os.cpu_count() or 4)
        d = Dispatcher(handler=_simple_handler, yolo=True)
        assert d.max_concurrency == cpu

    def test_normal_mode_concurrency(self) -> None:
        d = Dispatcher(handler=_simple_handler, max_concurrency=3)
        assert d.max_concurrency == 3

    def test_yolo_sets_retry_5(self) -> None:
        d = Dispatcher(handler=_simple_handler, yolo=True)
        assert d.retry_attempts == 5

    def test_normal_retry_3(self) -> None:
        d = Dispatcher(handler=_simple_handler)
        assert d.retry_attempts == 3

    def test_config_yolo_propagates(self) -> None:
        cfg = DispatcherConfig(yolo=True)
        d = Dispatcher(handler=_simple_handler, config=cfg)
        assert d.yolo is True
        assert d.retry_attempts == 5


# ── YOLO auto-approval of needs_human tasks ───────────────────────────────────


class TestYoloAutoApproval:
    @pytest.mark.asyncio
    async def test_yolo_auto_approves_needs_human(self) -> None:
        """In YOLO mode, needs_human tasks should be auto-approved and run."""
        d = Dispatcher(handler=_needs_human_handler, yolo=True)
        task = TaskNode("t1", "coding", 5, [])
        task.status = "needs_human"
        d.add_task(task)

        result = await d.run()
        # Task should complete (not blocked)
        assert "t1" in result.completed

    @pytest.mark.asyncio
    async def test_normal_mode_does_not_alter_needs_human(self) -> None:
        """In normal mode, a needs_human task is not auto-approved by dispatcher."""
        d = Dispatcher(handler=_simple_handler)
        task = TaskNode("t1", "coding", 5, [])
        task.status = "needs_human"

        # The scheduler only dispatches "pending" tasks — so needs_human stays pending
        # We add it but then manually verify the dispatcher doesn't touch its status
        d._scheduler.add_task(task)

        # needs_human is not in get_execution_order (only "pending" tasks go)
        waves = d._scheduler.get_execution_order()
        # t1 should not appear in any wave (it's not "pending")
        flat = [t for wave in waves for t in wave]
        assert "t1" not in flat

    @pytest.mark.asyncio
    async def test_yolo_warning_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """YOLO mode should log a prominent warning on construction."""
        import logging
        with caplog.at_level(logging.WARNING, logger="claw_forge.orchestrator.dispatcher"):
            Dispatcher(handler=_simple_handler, yolo=True)
        assert any("YOLO MODE" in r.message for r in caplog.records)


# ── YOLO concurrency is CPU count ─────────────────────────────────────────────


class TestYoloConcurrency:
    @pytest.mark.asyncio
    async def test_tasks_all_complete_in_yolo_mode(self) -> None:
        """All tasks should complete even at high concurrency."""
        cpu = max(1, os.cpu_count() or 4)
        d = Dispatcher(handler=_simple_handler, yolo=True)

        # Add cpu*2 independent tasks
        for i in range(cpu * 2):
            d.add_task(TaskNode(f"t{i}", "coding", 5, []))

        result = await d.run()
        assert result.all_succeeded
        assert len(result.completed) == cpu * 2

    @pytest.mark.asyncio
    async def test_yolo_respects_cpu_semaphore(self) -> None:
        """Semaphore should be set to CPU count in YOLO mode."""
        cpu = max(1, os.cpu_count() or 4)
        d = Dispatcher(handler=_simple_handler, yolo=True)
        # _semaphore._value reflects the initial capacity
        assert d._semaphore._value == cpu
