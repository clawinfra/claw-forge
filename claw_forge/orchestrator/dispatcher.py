"""Asyncio TaskGroup-based dispatcher for agent tasks."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Awaitable

from claw_forge.state.scheduler import Scheduler, TaskNode

logger = logging.getLogger(__name__)

TaskHandler = Callable[[TaskNode], Awaitable[dict[str, Any]]]


class DispatchResult:
    """Result of dispatching a wave of tasks."""

    def __init__(self) -> None:
        self.completed: dict[str, dict[str, Any]] = {}
        self.failed: dict[str, str] = {}

    @property
    def all_succeeded(self) -> bool:
        return len(self.failed) == 0


class Dispatcher:
    """Execute tasks in dependency-ordered waves using asyncio.TaskGroup.

    Each wave contains tasks that can run in parallel (all dependencies met).
    Waves execute sequentially; tasks within a wave execute concurrently,
    bounded by the concurrency semaphore.
    """

    def __init__(
        self,
        handler: TaskHandler,
        max_concurrency: int = 5,
    ) -> None:
        self._handler = handler
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._scheduler = Scheduler()

    def add_task(self, task: TaskNode) -> None:
        self._scheduler.add_task(task)

    async def run(self) -> DispatchResult:
        """Execute all tasks respecting dependencies."""
        self._scheduler.validate_no_cycles()
        result = DispatchResult()
        waves = self._scheduler.get_execution_order()

        for wave_idx, wave in enumerate(waves):
            logger.info("Dispatching wave %d: %s", wave_idx, wave)

            async with asyncio.TaskGroup() as tg:
                wave_futures: dict[str, asyncio.Task[dict[str, Any] | None]] = {}
                for task_id in wave:
                    task_node = self._scheduler._tasks[task_id]
                    wave_futures[task_id] = tg.create_task(
                        self._run_task(task_node)
                    )

            for task_id, future in wave_futures.items():
                exc = future.exception() if future.done() else None
                if exc:
                    result.failed[task_id] = str(exc)
                    self._scheduler.mark_failed(task_id)
                else:
                    task_result = future.result()
                    result.completed[task_id] = task_result or {}
                    self._scheduler.mark_completed(task_id)

        return result

    async def _run_task(self, task: TaskNode) -> dict[str, Any] | None:
        async with self._semaphore:
            logger.info("Running task %s (%s)", task.id, task.plugin_name)
            try:
                return await self._handler(task)
            except Exception:
                logger.exception("Task %s failed", task.id)
                raise
