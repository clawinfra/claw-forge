"""Tests for async dispatcher."""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

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
    async def test_failing_task_does_not_crash_wave(self):
        """A failing task should be recorded in result.failed without
        crashing sibling tasks via ExceptionGroup (TaskGroup safety)."""
        d = Dispatcher(
            handler=_failing_handler,
            config=DispatcherConfig(retry_attempts=1),
        )
        d.add_task(TaskNode("fail", "coding", 1, []))
        d.add_task(TaskNode("ok", "coding", 1, []))
        result = await d.run()
        assert "fail" in result.failed
        assert "ok" in result.completed

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


# ---------------------------------------------------------------------------
# _cancel_monitor
# ---------------------------------------------------------------------------


class TestCancelMonitor:
    @pytest.mark.asyncio
    async def test_cancel_monitor_full_signal_coverage(self):
        """Drive _cancel_monitor through all signal paths (lines 406-432)."""
        d = Dispatcher(handler=_success_handler, state_url="http://localhost:0")

        # A regular running task (not in _resumed_tasks → freeze + cancel)
        mock_task = MagicMock()
        d._running_tasks["t-stop"] = mock_task

        # A resumed task (in _resumed_tasks → cancel but NO freeze)
        resumed_mock = MagicMock()
        d._running_tasks["t-resumed"] = resumed_mock
        d._resumed_tasks.add("t-resumed")

        # A node for resume_task_ids path
        resume_node = TaskNode("t-resume-node", "coding", 1, [])
        d._scheduler.add_task(resume_node)

        # Also add a non-existent node to cover `if node is not None:` False branch
        responses = [
            # iter 1: stop t-stop (not resumed → freeze+cancel) and t-resumed (resumed → no freeze)
            {
                "task_ids": ["t-stop", "t-resumed", "t-unknown"],
                "pause": False,
                "resume": False,
                "resume_task_ids": [],
            },
            # iter 2: pause → pause() + cancel all running
            {
                "task_ids": [],
                "pause": True,
                "resume": False,
                "resume_task_ids": [],
            },
            # iter 3: resume + resume_task_ids (known node + unknown node)
            {
                "task_ids": [],
                "pause": False,
                "resume": True,
                "resume_task_ids": ["t-resume-node", "t-missing-node"],
            },
        ]

        sleep_count = 0
        get_count = 0
        created_tasks = []

        async def mock_sleep(_: float) -> None:
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count > len(responses):
                # Signal done after all responses consumed
                raise asyncio.CancelledError()

        async def mock_get(*args: object, **kwargs: object) -> MagicMock:
            nonlocal get_count
            if get_count < len(responses):
                data = responses[get_count]
                get_count += 1
            else:
                # cover except Exception: pass
                get_count += 1
                raise RuntimeError("transient http error")
            mock_resp = MagicMock()
            mock_resp.json.return_value = data
            return mock_resp

        mock_client = AsyncMock()
        mock_client.get.side_effect = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        def fake_create_task(coro: object) -> MagicMock:
            # Prevent real tasks from being spawned; close the coroutine
            if hasattr(coro, "close"):
                coro.close()  # type: ignore[union-attr]
            t = MagicMock()
            created_tasks.append(t)
            return t

        with (
            patch("claw_forge.orchestrator.dispatcher.asyncio.sleep", mock_sleep),
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("claw_forge.orchestrator.dispatcher.asyncio.create_task", fake_create_task),
            contextlib.suppress(asyncio.CancelledError),
        ):
            await d._cancel_monitor()

        # t-stop was in running_tasks and NOT in resumed_tasks → freeze + cancel
        assert mock_task.cancel.called
        # t-resumed was in running_tasks AND in resumed_tasks → cancel (no freeze)
        assert resumed_mock.cancel.called
        # resume_task_ids: t-resume-node should have spawned a task
        assert len(created_tasks) >= 1


# ── Bugfix sweep tests ────────────────────────────────────────────────────


class TestBugfixSweep:
    """Tests for _run_bugfix_sweep."""

    @pytest.mark.asyncio
    async def test_sweep_skipped_when_no_state_url(self) -> None:
        """Sweep does nothing when state_url is None."""
        d = Dispatcher(handler=_success_handler, state_url=None)
        from claw_forge.orchestrator.dispatcher import DispatchResult

        result = DispatchResult()
        await d._run_bugfix_sweep(result)
        assert len(result.completed) == 0
        assert len(result.failed) == 0

    @pytest.mark.asyncio
    async def test_sweep_skipped_when_paused(self) -> None:
        """Sweep does nothing when dispatcher is paused."""
        d = Dispatcher(handler=_success_handler, state_url="http://localhost:8420")
        d.pause()
        from claw_forge.orchestrator.dispatcher import DispatchResult

        result = DispatchResult()
        await d._run_bugfix_sweep(result)
        assert len(result.completed) == 0

    @pytest.mark.asyncio
    async def test_sweep_runs_pending_bugfix_tasks(self) -> None:
        """Sweep picks up pending bugfix tasks and runs them."""
        d = Dispatcher(handler=_success_handler, state_url="http://localhost:8420")
        from claw_forge.orchestrator.dispatcher import DispatchResult

        mock_session_resp = MagicMock()
        mock_session_resp.json.return_value = [{"id": "sess-1"}]

        bugfix_tasks = [
            {
                "id": "bugfix-1",
                "plugin_name": "bugfix",
                "status": "pending",
                "priority": 10,
                "category": "bugfix",
                "steps": ["fix it"],
                "description": "Fix regression",
            },
        ]
        mock_tasks_resp = MagicMock()
        mock_tasks_resp.json.return_value = bugfix_tasks

        # Second round returns no pending bugfixes (loop termination)
        mock_session_resp_2 = MagicMock()
        mock_session_resp_2.json.return_value = [{"id": "sess-1"}]
        mock_tasks_resp_2 = MagicMock()
        mock_tasks_resp_2.json.return_value = []

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[
            mock_session_resp, mock_tasks_resp,
            mock_session_resp_2, mock_tasks_resp_2,
        ])

        result = DispatchResult()
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await d._run_bugfix_sweep(result)

        assert "bugfix-1" in result.completed

    @pytest.mark.asyncio
    async def test_sweep_no_pending_bugfixes_exits(self) -> None:
        """Sweep exits early when no pending bugfix tasks found."""
        d = Dispatcher(handler=_success_handler, state_url="http://localhost:8420")
        from claw_forge.orchestrator.dispatcher import DispatchResult

        mock_session_resp = AsyncMock()
        mock_session_resp.json.return_value = [{"id": "sess-1"}]

        mock_tasks_resp = AsyncMock()
        mock_tasks_resp.json.return_value = [
            {"id": "t-1", "plugin_name": "coding", "status": "completed"},
        ]

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=[mock_session_resp, mock_tasks_resp])

        result = DispatchResult()
        with patch("httpx.AsyncClient", return_value=mock_client):
            await d._run_bugfix_sweep(result)

        assert len(result.completed) == 0

    @pytest.mark.asyncio
    async def test_sweep_handles_http_error(self) -> None:
        """Sweep handles network errors gracefully."""
        d = Dispatcher(handler=_success_handler, state_url="http://localhost:8420")
        from claw_forge.orchestrator.dispatcher import DispatchResult

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))

        result = DispatchResult()
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await d._run_bugfix_sweep(result)

        assert len(result.completed) == 0
        assert len(result.failed) == 0

    @pytest.mark.asyncio
    async def test_sweep_records_failed_bugfix(self) -> None:
        """Sweep records failure when bugfix task handler raises."""
        d = Dispatcher(handler=_failing_handler, state_url="http://localhost:8420")
        from claw_forge.orchestrator.dispatcher import DispatchResult

        mock_session_resp = MagicMock()
        mock_session_resp.json.return_value = [{"id": "sess-1"}]

        mock_tasks_resp = MagicMock()
        mock_tasks_resp.json.return_value = [
            {
                "id": "fail",
                "plugin_name": "bugfix",
                "status": "pending",
                "priority": 10,
                "category": "bugfix",
                "steps": [],
                "description": "Fix regression",
            },
        ]

        mock_session_resp_2 = MagicMock()
        mock_session_resp_2.json.return_value = [{"id": "sess-1"}]
        mock_tasks_resp_2 = MagicMock()
        mock_tasks_resp_2.json.return_value = []

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[
            mock_session_resp, mock_tasks_resp,
            mock_session_resp_2, mock_tasks_resp_2,
        ])

        result = DispatchResult()
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await d._run_bugfix_sweep(result)

        assert "fail" in result.failed
