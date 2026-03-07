"""Tests for async dispatcher."""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from claw_forge.orchestrator.dispatcher import (
    Dispatcher,
    DispatcherConfig,
    _FreezableSemaphore,
)
from claw_forge.state.scheduler import TaskNode


async def _success_handler(task: TaskNode) -> dict:
    return {"status": "done", "task": task.id}


async def _failing_handler(task: TaskNode) -> dict:
    if task.id == "fail":
        raise RuntimeError("intentional")
    return {"status": "done"}


class TestDispatcher:
    @pytest.mark.asyncio
    async def test_simple_dispatch(self):
        d = Dispatcher(handler=_success_handler)
        d.add_task(TaskNode("a", "coding", 1, []))
        d.add_task(TaskNode("b", "testing", 1, []))
        result = await d.run()
        assert result.all_succeeded
        assert "a" in result.completed
        assert "b" in result.completed

    @pytest.mark.asyncio
    async def test_dependency_waves(self):
        order = []

        async def _tracking_handler(task):
            order.append(task.id)
            return {}

        d = Dispatcher(handler=_tracking_handler)
        d.add_task(TaskNode("a", "init", 1, []))
        d.add_task(TaskNode("b", "code", 1, ["a"]))
        result = await d.run()
        assert result.all_succeeded
        assert order.index("a") < order.index("b")


# ---------------------------------------------------------------------------
# _FreezableSemaphore
# ---------------------------------------------------------------------------


class TestFreezableSemaphore:
    @pytest.mark.asyncio
    async def test_freeze_absorbs_release(self):
        """freeze_one() causes the next release() to be a no-op (lines 46-47, 52)."""
        sem = _FreezableSemaphore(2)
        await sem.acquire()          # value: 1
        sem.freeze_one()             # _frozen = 1
        sem.release()                # _frozen > 0 → swallow → _frozen = 0
        assert sem._frozen == 0
        assert sem._sem._value == 1  # NOT restored (would be 2 without freeze)

    @pytest.mark.asyncio
    async def test_release_without_freeze_restores_slot(self):
        """Normal release without freeze actually releases the semaphore."""
        sem = _FreezableSemaphore(1)
        await sem.acquire()
        assert sem._sem._value == 0
        sem.release()
        assert sem._sem._value == 1

    def test_unfreeze_one_decrements_frozen(self):
        """unfreeze_one() cancels a pending freeze (lines 56-57)."""
        sem = _FreezableSemaphore(2)
        sem.freeze_one()      # _frozen = 1
        sem.unfreeze_one()    # _frozen > 0 → _frozen = 0
        assert sem._frozen == 0

    def test_unfreeze_one_noop_when_not_frozen(self):
        """unfreeze_one() with _frozen == 0 is a no-op."""
        sem = _FreezableSemaphore(2)
        sem.unfreeze_one()    # _frozen == 0 → no change
        assert sem._frozen == 0

    @pytest.mark.asyncio
    async def test_context_manager_acquires_and_releases(self):
        """__aenter__ / __aexit__ acquire and release the semaphore."""
        sem = _FreezableSemaphore(1)
        async with sem:
            assert sem._sem._value == 0
        assert sem._sem._value == 1


# ---------------------------------------------------------------------------
# _run_resumed_task
# ---------------------------------------------------------------------------


class TestRunResumedTask:
    @pytest.mark.asyncio
    async def test_run_resumed_task_success_restores_slot(self):
        """Normal completion restores semaphore slot (lines 371-386)."""
        async def handler(task: TaskNode) -> dict:
            return {"done": True}

        d = Dispatcher(handler=handler)
        node = TaskNode("t1", "coding", 1, [])
        d._scheduler.add_task(node)

        # Consume one slot (simulating freeze_one)
        await d._semaphore._sem.acquire()
        before = d._semaphore._sem._value

        await d._run_resumed_task(node)

        # Slot should be restored after normal completion
        assert d._semaphore._sem._value == before + 1

    @pytest.mark.asyncio
    async def test_run_resumed_task_exception_restores_slot(self):
        """Exception in handler still restores slot (lines 380-386)."""
        async def failing_handler(task: TaskNode) -> dict:
            raise RuntimeError("resumed task failed")

        d = Dispatcher(handler=failing_handler)
        node = TaskNode("t1", "coding", 1, [])
        d._scheduler.add_task(node)

        await d._semaphore._sem.acquire()
        before = d._semaphore._sem._value

        await d._run_resumed_task(node)  # should not raise

        assert d._semaphore._sem._value == before + 1

    @pytest.mark.asyncio
    async def test_run_resumed_task_cancelled_does_not_restore_slot(self):
        """CancelledError in handler does NOT restore slot (lines 376-379)."""
        ready = asyncio.Event()

        async def blocking_handler(task: TaskNode) -> dict:
            ready.set()
            await asyncio.Event().wait()  # block until cancelled
            return {}

        d = Dispatcher(handler=blocking_handler)
        node = TaskNode("t1", "coding", 1, [])
        d._scheduler.add_task(node)

        await d._semaphore._sem.acquire()
        before = d._semaphore._sem._value

        t = asyncio.create_task(d._run_resumed_task(node))
        await ready.wait()
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t

        # Slot should NOT be restored (cancelled path returns early)
        assert d._semaphore._sem._value == before


# ---------------------------------------------------------------------------
# _run_task CancelledError paths
# ---------------------------------------------------------------------------


class TestRunTaskCancellation:
    @pytest.mark.asyncio
    async def test_cancelled_during_retry_sleep_returns_none(self):
        """CancelledError in asyncio.sleep during retry → returns None (lines 342-347)."""
        from unittest.mock import patch

        sleep_started = asyncio.Event()

        async def mock_sleep(secs: float) -> None:
            sleep_started.set()
            await asyncio.Event().wait()  # block until cancelled

        async def failing_handler(task: TaskNode) -> dict:
            raise RuntimeError("intentional fail")

        d = Dispatcher(
            handler=failing_handler,
            config=DispatcherConfig(retry_attempts=3),
        )
        node = TaskNode("t1", "coding", 1, [])
        d._scheduler.add_task(node)

        with patch("claw_forge.orchestrator.dispatcher.asyncio.sleep", side_effect=mock_sleep):
            run_task = asyncio.create_task(d._run_task(node))
            await sleep_started.wait()
            run_task.cancel()
            try:
                result = await run_task
            except asyncio.CancelledError:
                result = None
        assert result is None

    @pytest.mark.asyncio
    async def test_cancelled_before_semaphore_returns_none(self):
        """CancelledError while waiting to acquire semaphore → returns None (lines 356-359)."""
        async def handler(task: TaskNode) -> dict:
            return {}

        d = Dispatcher(handler=handler)
        node = TaskNode("t1", "coding", 1, [])
        d._scheduler.add_task(node)

        # Exhaust all semaphore slots so the task blocks on acquire
        for _ in range(d._semaphore._value):
            await d._semaphore._sem.acquire()

        run_task = asyncio.create_task(d._run_task(node))
        await asyncio.sleep(0)  # let task start and block
        run_task.cancel()
        try:
            result = await run_task
        except asyncio.CancelledError:
            result = None
        assert result is None
