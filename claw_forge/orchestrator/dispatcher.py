"""Asyncio TaskGroup-based dispatcher for agent tasks.

Supports:
- YOLO mode: skip human input, max concurrency (CPU count), aggressive retry
- Pause/resume: drain mode — finish in-flight agents, don't start new ones
- Human input: tasks that move to ``needs_human`` are skipped until answered
- ParallelReviewer: background regression tests triggered after N features
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from claw_forge.state.scheduler import Scheduler, TaskNode

if TYPE_CHECKING:
    from claw_forge.orchestrator.reviewer import ParallelReviewer
    from claw_forge.state.service import AgentStateService

logger = logging.getLogger(__name__)


class _FreezableSemaphore:
    """Wraps ``asyncio.Semaphore`` with the ability to swallow releases.

    When ``freeze_one()`` is called, the next ``release()`` is silently
    consumed instead of actually freeing a slot.  This prevents a queued
    task from filling a slot that was vacated by an individually-stopped task.
    """

    def __init__(self, value: int) -> None:
        self._sem = asyncio.Semaphore(value)
        self._frozen: int = 0
        self._value: int = value

    async def acquire(self) -> None:
        await self._sem.acquire()

    def release(self) -> None:
        if self._frozen > 0:
            self._frozen -= 1
            return  # swallow — don't actually free the slot
        self._sem.release()

    def freeze_one(self) -> None:
        """Make the next ``release()`` a no-op, consuming the freed slot."""
        self._frozen += 1

    def unfreeze_one(self) -> None:
        """Cancel a pending freeze (if the release hasn't happened yet)."""
        if self._frozen > 0:
            self._frozen -= 1

    async def __aenter__(self) -> _FreezableSemaphore:
        await self.acquire()
        return self

    async def __aexit__(self, *args: Any) -> None:
        self.release()

TaskHandler = Callable[[TaskNode], Awaitable[dict[str, Any]]]

_YOLO_WARNING = (
    "⚠️  YOLO MODE: Human approval skipped, max concurrency, aggressive retry"
)


class DispatcherConfig:
    """Configuration knobs for the dispatcher.

    Parameters
    ----------
    max_concurrency:
        Maximum number of tasks that run in parallel.  ``None`` means use
        ``os.cpu_count()`` (YOLO default).
    retry_attempts:
        How many times to retry a failed task handler before giving up.
    yolo:
        When *True*: human-input tasks are auto-approved with a warning log,
        concurrency is set to CPU count, and retry attempts are bumped to 5.
    """

    def __init__(
        self,
        max_concurrency: int = 5,
        retry_attempts: int = 3,
        *,
        yolo: bool = False,
    ) -> None:
        self.yolo = yolo
        if yolo:
            self.max_concurrency: int = max(1, os.cpu_count() or 4)
            self.retry_attempts: int = 5
        else:
            self.max_concurrency = max_concurrency
            self.retry_attempts = retry_attempts


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

    YOLO mode
    ---------
    Pass ``yolo=True`` (or construct with ``DispatcherConfig(yolo=True)``):

    * Concurrency is set to ``os.cpu_count()``.
    * Retry attempts are bumped to 5.
    * Tasks in ``needs_human`` status are auto-approved with a log warning
      instead of blocking.

    Pause / resume
    --------------
    Call ``pause()`` to set the drain flag.  The current in-flight wave will
    complete normally, but no new waves will start.  Call ``resume()`` to
    clear the flag and continue.
    """

    def __init__(
        self,
        handler: TaskHandler,
        max_concurrency: int = 5,
        *,
        yolo: bool = False,
        config: DispatcherConfig | None = None,
        state_url: str | None = None,
    ) -> None:
        if config is not None:
            self._config = config
        else:
            self._config = DispatcherConfig(
                max_concurrency=max_concurrency,
                yolo=yolo,
            )

        self._handler = handler
        self._semaphore = _FreezableSemaphore(self._config.max_concurrency)
        self._scheduler = Scheduler()
        self._paused: bool = False
        self._reviewer: ParallelReviewer | None = None
        # URL of the state service for stop-poll; enables cancel monitor when set
        self._state_url: str | None = state_url
        # Registry of currently-running asyncio Tasks keyed by task ID
        self._running_tasks: dict[str, asyncio.Task[Any]] = {}
        # Task IDs running outside the semaphore (individually resumed tasks)
        self._resumed_tasks: set[str] = set()
        # Errors from tasks that exhausted retries (keyed by task ID).
        # Stored here instead of raised so TaskGroup doesn't cancel siblings.
        self._task_errors: dict[str, Exception | None] = {}

        if self._config.yolo:
            logger.warning(_YOLO_WARNING)

    # ── Public properties ────────────────────────────────────────────────────

    @property
    def yolo(self) -> bool:
        """Whether YOLO mode is active."""
        return self._config.yolo

    @property
    def max_concurrency(self) -> int:
        """Effective concurrency limit."""
        return self._config.max_concurrency

    @property
    def retry_attempts(self) -> int:
        """Number of retry attempts per task."""
        return self._config.retry_attempts

    @property
    def is_paused(self) -> bool:
        """True when the dispatcher is in drain (paused) mode."""
        return self._paused

    # ── Pause / resume ───────────────────────────────────────────────────────

    def pause(self) -> None:
        """Signal the dispatcher to drain: finish in-flight tasks, start no new ones."""
        logger.info("Dispatcher paused — draining in-flight tasks")
        self._paused = True

    def resume(self) -> None:
        """Clear the paused flag and allow new waves to start."""
        logger.info("Dispatcher resumed — normal operation")
        self._paused = False

    # ── Regression reviewer ──────────────────────────────────────────────────

    async def start_reviewer(
        self,
        project_dir: str,
        state_service: AgentStateService,
        interval_features: int = 3,
    ) -> None:
        """Create and start a :class:`ParallelReviewer`."""
        from claw_forge.orchestrator.reviewer import ParallelReviewer

        self._reviewer = ParallelReviewer(
            project_dir=project_dir,
            state_service=state_service,
            interval_features=interval_features,
        )
        state_service._reviewer = self._reviewer
        await self._reviewer.start()

    async def stop_reviewer(self) -> None:
        """Stop the background reviewer if running."""
        if self._reviewer is not None:
            await self._reviewer.stop()
            self._reviewer = None

    # ── Task management ──────────────────────────────────────────────────────

    def add_task(self, task: TaskNode) -> None:
        self._scheduler.add_task(task)

    # ── Execution ────────────────────────────────────────────────────────────

    async def run(self) -> DispatchResult:
        """Execute all tasks respecting dependencies.

        Waves run sequentially.  Tasks within a wave run concurrently up to
        ``max_concurrency``.  If ``is_paused`` becomes True between waves, no
        further waves are started (drain mode).

        YOLO mode pre-processes tasks: any task in ``needs_human`` status is
        reset to ``pending`` before scheduling so it participates in execution.
        """
        # YOLO: reset needs_human tasks to pending so they're dispatched
        if self._config.yolo:
            for task in self._scheduler._tasks.values():
                if task.status == "needs_human":
                    logger.warning(
                        "YOLO MODE: Auto-approving needs_human task %s (%s)",
                        task.id,
                        task.plugin_name,
                    )
                    task.status = "pending"

        self._scheduler.validate_no_cycles()
        result = DispatchResult()
        waves = self._scheduler.get_execution_order()

        # Start background cancel monitor if state service URL is known
        monitor: asyncio.Task[None] | None = None
        if self._state_url:
            monitor = asyncio.create_task(self._cancel_monitor())

        try:
            for wave_idx, wave in enumerate(waves):
                # Drain mode: stop dispatching new waves
                if self._paused:
                    logger.info("Dispatcher is paused — stopping before wave %d", wave_idx)
                    break

                logger.info("Dispatching wave %d: %s", wave_idx, wave)

                async with asyncio.TaskGroup() as tg:
                    wave_futures: dict[str, asyncio.Task[dict[str, Any] | None]] = {}
                    for task_id in wave:
                        task_node = self._scheduler._tasks[task_id]
                        wave_futures[task_id] = tg.create_task(
                            self._run_task(task_node)
                        )

                for task_id, future in wave_futures.items():
                    stored_err = self._task_errors.pop(task_id, None)
                    if stored_err is not None:
                        result.failed[task_id] = str(stored_err)
                        self._scheduler.mark_failed(task_id)
                    else:
                        task_result = future.result()
                        result.completed[task_id] = task_result or {}
                        self._scheduler.mark_completed(task_id)
                        # Notify reviewer of feature completion
                        if self._reviewer is not None:
                            self._reviewer.notify_feature_completed()

            # ── Bugfix sweep: pick up tasks created by the reviewer ───────
            await self._run_bugfix_sweep(result)
        finally:
            if monitor is not None:
                monitor.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await monitor

        return result

    async def _run_bugfix_sweep(self, result: DispatchResult) -> None:
        """Execute pending bugfix tasks that the reviewer created mid-run.

        The main wave plan is pre-computed, so bugfix tasks inserted into
        the DB during execution are never scheduled.  This sweep queries
        the state service for any pending bugfix tasks and runs them.
        """
        if self._state_url is None or self._paused:
            return

        import httpx

        max_rounds = 3  # prevent infinite fix loops
        for round_num in range(1, max_rounds + 1):
            if self._paused:
                break
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{self._state_url}/sessions",
                        timeout=5.0,
                    )
                    sessions = resp.json()
                    if not sessions:
                        return
                    session_id = sessions[0]["id"]

                    resp = await client.get(
                        f"{self._state_url}/sessions/{session_id}/tasks",
                        timeout=5.0,
                    )
                    tasks = resp.json()
            except Exception:  # noqa: BLE001
                logger.warning("Bugfix sweep: failed to fetch tasks")
                return

            pending_bugfixes = [
                t for t in tasks
                if t.get("plugin_name") == "bugfix"
                and t.get("status") == "pending"
            ]
            if not pending_bugfixes:
                return

            logger.info(
                "Bugfix sweep round %d: %d pending bugfix task(s)",
                round_num,
                len(pending_bugfixes),
            )
            for task_data in pending_bugfixes:
                if self._paused:
                    break
                node = TaskNode(
                    id=task_data["id"],
                    plugin_name="bugfix",
                    priority=task_data.get("priority", 0),
                    depends_on=[],
                    status="pending",
                    category=task_data.get("category", "bugfix"),
                    steps=task_data.get("steps", []),
                    description=task_data.get("description", ""),
                )
                try:
                    task_result = await self._run_task(node)
                    if self._task_errors.pop(node.id, None) is not None:
                        result.failed[node.id] = "bugfix failed"
                    else:
                        result.completed[node.id] = task_result or {}
                except Exception:  # noqa: BLE001  # pragma: no cover
                    logger.exception("Bugfix task %s failed", node.id)
                    result.failed[node.id] = "bugfix exception"

    async def _run_task(self, task: TaskNode) -> dict[str, Any] | None:
        """Run a single task with retry logic.

        Retries up to ``retry_attempts`` times with exponential back-off.
        YOLO mode is handled before scheduling (see ``run()``).

        If the task's asyncio.Task is cancelled (via the stop UI control), the
        cancellation is caught gracefully and ``None`` is returned — the state
        service has already reset the task to ``pending``.

        Non-cancellation exceptions are caught after retry exhaustion and
        stored in ``_task_errors`` instead of re-raising.  This prevents
        ``asyncio.TaskGroup`` from killing the entire wave when a single
        task fails.
        """
        self._running_tasks[task.id] = asyncio.current_task()  # type: ignore[assignment]
        try:
            async with self._semaphore:
                logger.info("Running task %s (%s)", task.id, task.plugin_name)
                last_exc: Exception | None = None

                for attempt in range(1, self._config.retry_attempts + 1):
                    try:
                        return await self._handler(task)
                    except asyncio.CancelledError:
                        logger.info(
                            "Task %s stopped by user — resetting to pending", task.id
                        )
                        return None
                    except Exception as exc:
                        last_exc = exc
                        if attempt < self._config.retry_attempts:
                            wait = 2 ** (attempt - 1)  # exponential backoff: 1s, 2s, 4s …
                            logger.warning(
                                "Task %s failed (attempt %d/%d) — retrying in %ds: %s",
                                task.id,
                                attempt,
                                self._config.retry_attempts,
                                wait,
                                exc,
                            )
                            try:
                                await asyncio.sleep(wait)
                            except asyncio.CancelledError:
                                logger.info(
                                    "Task %s stopped during retry wait — resetting to pending",
                                    task.id,
                                )
                                return None
                        else:
                            logger.exception(
                                "Task %s failed after %d attempts", task.id, attempt
                            )

                # Store the error instead of raising — TaskGroup would cancel
                # all sibling tasks if we let the exception propagate.
                self._task_errors[task.id] = last_exc
                return None
        except asyncio.CancelledError:
            # Cancelled while waiting to acquire the semaphore
            logger.info(
                "Task %s stopped before acquiring semaphore — resetting to pending", task.id
            )
            return None
        finally:
            self._running_tasks.pop(task.id, None)

    async def _run_resumed_task(self, task: TaskNode) -> None:
        """Run an individually-resumed task, bypassing the semaphore.

        The semaphore slot was consumed during stop (via ``freeze_one``).
        This task runs in that reserved slot without acquiring the semaphore.
        On normal completion, the underlying semaphore slot is restored so
        overall concurrency is preserved.
        """
        self._resumed_tasks.add(task.id)
        self._running_tasks[task.id] = asyncio.current_task()  # type: ignore[assignment]
        try:
            logger.info("Resuming task %s (%s)", task.id, task.plugin_name)
            await self._handler(task)
        except asyncio.CancelledError:
            logger.info("Resumed task %s stopped again", task.id)
            # Don't restore the slot — it stays consumed for the next resume
            return
        except Exception:
            logger.exception("Resumed task %s failed", task.id)
        finally:
            self._running_tasks.pop(task.id, None)
            self._resumed_tasks.discard(task.id)
        # Normal completion or failure: restore the semaphore slot
        self._semaphore._sem.release()

    async def _cancel_monitor(self) -> None:
        """Poll the state service for stop/pause/resume signals.

        Runs as a background asyncio.Task for the duration of ``run()``.
        Polls ``GET {state_url}/stop-poll`` every 2 s:
        - Cancels any task IDs listed in ``task_ids``.
        - Calls ``self.pause()`` when ``pause`` flag is True.
        - Calls ``self.resume()`` when ``resume`` flag is True.
        """
        import httpx

        async with httpx.AsyncClient() as client:
            while True:
                await asyncio.sleep(2)
                try:
                    resp = await client.get(
                        f"{self._state_url}/stop-poll", timeout=3.0
                    )
                    data: dict[str, Any] = resp.json()
                    for task_id in data.get("task_ids", []):
                        t = self._running_tasks.get(task_id)
                        if t is not None:
                            # Only freeze for semaphore-managed tasks (not resumed ones)
                            if task_id not in self._resumed_tasks:
                                self._semaphore.freeze_one()
                            t.cancel()
                    if data.get("pause"):
                        self.pause()
                        # Hard-stop: cancel tasks waiting for the semaphore too.
                        # Without this, cancelled tasks release the semaphore and
                        # queued tasks immediately acquire it and become "running",
                        # causing the In Progress count to grow on Stop All.
                        for t in list(self._running_tasks.values()):
                            t.cancel()
                    if data.get("resume"):
                        self.resume()
                    # Individual task resumes: bypass the semaphore and
                    # spawn directly — the frozen slot is already reserved.
                    for task_id in data.get("resume_task_ids", []):
                        node = self._scheduler._tasks.get(task_id)
                        if node is not None:
                            node.status = "pending"
                            asyncio.create_task(self._run_resumed_task(node))
                except Exception:  # noqa: BLE001  # pragma: no cover
                    pass  # transient errors are fine — we'll retry next cycle
