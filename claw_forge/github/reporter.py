"""Progress reporter for GitHub issue-triggered runs.

Hooks into the orchestrator to post real-time updates to GitHub issues
as agents work on tasks.  Comments are queued and posted by a background
worker task so agent execution is never blocked on API latency.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claw_forge.github.client import GitHubClient
    from claw_forge.github.models import GitHubContext

logger = logging.getLogger(__name__)


class ProgressReporter:
    """Posts progress updates to a GitHub issue during claw-forge runs.

    Maintains an async queue of pending comments and drains it via a
    background worker task so that calling ``report_*`` methods never
    blocks the agent pipeline.

    Usage::

        async with GitHubClient(token) as client:
            reporter = ProgressReporter(client, ctx)
            await reporter.start()
            await reporter.report_start(10, "coding")
            # ... agent runs ...
            await reporter.stop()
    """

    def __init__(self, client: GitHubClient, context: GitHubContext) -> None:
        self.client = client
        self.context = context
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._stopped = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background comment-poster task."""
        self._stopped = False
        self._worker_task = asyncio.create_task(self._worker())
        logger.info(
            "Progress reporter started for %s/%s#%d",
            self.context.owner,
            self.context.repo,
            self.context.issue_number,
        )

    async def stop(self) -> None:
        """Stop the background worker after flushing any queued comments."""
        self._stopped = True
        if self._worker_task is not None:
            try:
                await asyncio.wait_for(self._worker_task, timeout=30.0)
            except TimeoutError:
                self._worker_task.cancel()
                logger.warning("Progress reporter worker timed out during shutdown")
            self._worker_task = None
        logger.info("Progress reporter stopped")

    # ── Background worker ─────────────────────────────────────────────────────

    async def _worker(self) -> None:
        """Drain the comment queue, posting each entry to GitHub.

        Runs until ``_stopped`` is True AND the queue is empty.
        Each comment is posted with best-effort error handling: transient
        API errors are logged and swallowed so the worker keeps running.
        """
        while not self._stopped or not self._queue.empty():
            try:
                comment = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            await self._post_safe(comment)
            self._queue.task_done()

    async def _post_safe(self, comment: str) -> None:
        """Post a comment with error suppression."""
        try:
            await self.client.post_comment(
                self.context.owner,
                self.context.repo,
                self.context.issue_number,
                comment,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to post GitHub comment: %s", exc)

    async def _enqueue(self, comment: str) -> None:
        await self._queue.put(comment)

    # ── Progress events ───────────────────────────────────────────────────────

    async def report_start(self, task_count: int, plugin_name: str) -> None:
        """Report that claw-forge has started.

        Args:
            task_count: Total number of tasks to execute.
            plugin_name: Agent plugin type (coding, testing, etc.).
        """
        comment = (
            f"🤖 **claw-forge started**\n\n"
            f"- Plugin: `{plugin_name}`\n"
            f"- Tasks: {task_count}\n"
            f"- Branch: `{self.context.branch_name}`\n\n"
            f"Working on it... 🚀"
        )
        await self._enqueue(comment)

    async def report_task_start(self, task_id: str, description: str) -> None:
        """Report that a task has started.

        Args:
            task_id: Task identifier.
            description: Task description.
        """
        comment = f"▶️ **Started task:** `{task_id}`\n_ {description} _"
        await self._enqueue(comment)

    async def report_task_complete(self, task_id: str) -> None:
        """Report that a task completed successfully.

        Args:
            task_id: Task identifier.
        """
        comment = f"✅ **Completed:** `{task_id}`"
        await self._enqueue(comment)

    async def report_task_error(self, task_id: str, error: str) -> None:
        """Report that a task failed.

        Args:
            task_id: Task identifier.
            error: Error message or traceback.
        """
        comment = f"❌ **Failed:** `{task_id}`\n```\n{error}\n```"
        await self._enqueue(comment)

    async def report_summary(
        self,
        completed: int,
        failed: int,
        pr_url: str | None = None,
    ) -> None:
        """Post the final run summary.

        Args:
            completed: Number of successfully completed tasks.
            failed: Number of failed tasks.
            pr_url: URL of the created draft PR (if any).
        """
        lines = [
            "## 🏁 claw-forge run complete",
            "",
            f"- ✅ Completed: {completed}",
            f"- ❌ Failed: {failed}",
        ]

        if pr_url:
            lines += [
                "",
                f"📄 **Draft PR:** [{pr_url}]({pr_url})",
                "",
                "Please review the changes and mark the PR as ready when satisfied.",
            ]
        elif failed > 0:
            lines += [
                "",
                "⚠️ Some tasks failed — please check the logs and retry.",
            ]

        await self._enqueue("\n".join(lines))
