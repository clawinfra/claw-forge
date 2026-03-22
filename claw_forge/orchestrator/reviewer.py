"""ParallelReviewer — background regression test runner.

Detects the project's test command, runs it periodically as features
complete, and broadcasts results via the state service WebSocket.
This is a pure asyncio subprocess task — **not** an LLM session.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from claw_forge.state.service import AgentStateService

logger = logging.getLogger(__name__)


def detect_test_command(project_dir: str | Path) -> str | None:
    """Infer the test command for a project directory.

    Returns the shell command string or ``None`` if no known test
    framework is detected (caller should ask the user).

    Detection order (first match wins):
    1. ``package.json`` → ``npm test``
    2. ``pyproject.toml`` or ``setup.py`` → ``uv run pytest`` /
       ``pytest``
    3. ``Cargo.toml`` → ``cargo test``
    4. ``go.mod`` → ``go test ./...``
    5. ``Makefile`` with a ``test:`` target → ``make test``
    """
    root = Path(project_dir)

    # Node / npm
    if (root / "package.json").exists():
        return "npm test"

    # Python — prefer uv when pyproject.toml present
    if (root / "pyproject.toml").exists():
        return "uv run pytest"
    if (root / "setup.py").exists():
        return "pytest"

    # Rust
    if (root / "Cargo.toml").exists():
        return "cargo test"

    # Go
    if (root / "go.mod").exists():
        return "go test ./..."

    # Makefile with test target
    makefile = root / "Makefile"
    if makefile.exists():
        try:
            content = makefile.read_text(encoding="utf-8")
            if re.search(r"^test\s*:", content, re.MULTILINE):
                return "make test"
        except OSError:
            pass

    return None


@dataclass
class RegressionResult:
    """Outcome of a single regression test run."""

    passed: bool
    total: int
    failed: int
    failed_tests: list[str] = field(default_factory=list)
    duration_ms: int = 0
    run_number: int = 0
    implicated_feature_ids: list[str] = field(default_factory=list)
    trigger_features: list[dict[str, str]] = field(default_factory=list)
    output: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-friendly dictionary."""
        return {
            "passed": self.passed,
            "total": self.total,
            "failed": self.failed,
            "failed_tests": self.failed_tests,
            "duration_ms": self.duration_ms,
            "run_number": self.run_number,
            "implicated_feature_ids": self.implicated_feature_ids,
            "trigger_features": self.trigger_features,
            "output": self.output,
        }


class ParallelReviewer:
    """Background regression runner that triggers after N features.

    Parameters
    ----------
    project_dir:
        Root of the project under test.
    state_service:
        ``AgentStateService`` instance used to broadcast results.
    interval_features:
        Number of completed features between test runs.
    """

    def __init__(
        self,
        project_dir: str | Path,
        state_service: AgentStateService,
        interval_features: int = 3,
        max_bugfix_retries: int = 2,
    ) -> None:
        self._project_dir = Path(project_dir)
        self._state_service = state_service
        self._interval = max(1, interval_features)
        self._max_bugfix_retries = max_bugfix_retries
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._feature_event = asyncio.Event()
        self._completed_count = 0
        self._last_triggered = 0
        self._run_number = 0
        self._last_result: RegressionResult | None = None
        self._test_command = detect_test_command(self._project_dir)
        self.session_id: str | None = None
        # Buffer of features completed since last trigger
        self._pending_triggers: list[dict[str, str]] = []

    # ── Public API ───────────────────────────────────────────────────

    @property
    def last_result(self) -> RegressionResult | None:
        """Most recent regression result, or ``None`` if never run."""
        return self._last_result

    @property
    def run_count(self) -> int:
        """Total number of regression runs executed so far."""
        return self._run_number

    @property
    def test_command(self) -> str | None:
        """The detected (or overridden) test command."""
        return self._test_command

    def notify_feature_completed(
        self,
        task_id: str = "",
        task_name: str = "",
    ) -> None:
        """Call when a feature completes to potentially trigger a run."""
        self._completed_count += 1
        if task_id:
            self._pending_triggers.append({"id": task_id, "name": task_name})
        if (
            self._completed_count - self._last_triggered
            >= self._interval
        ):
            self._feature_event.set()

    async def start(self) -> None:
        """Start the background review loop."""
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "ParallelReviewer started (cmd=%s, interval=%d)",
            self._test_command,
            self._interval,
        )

    async def stop(self) -> None:
        """Signal the loop to stop and wait for it to finish."""
        if self._task is None:
            return
        self._stop_event.set()
        self._feature_event.set()  # unblock wait
        await self._task
        self._task = None
        logger.info("ParallelReviewer stopped")

    # ── Internal ─────────────────────────────────────────────────────

    async def _loop(self) -> None:
        """Wait for feature completions, then run tests."""
        while not self._stop_event.is_set():
            # Wait until enough features have completed
            await self._feature_event.wait()
            self._feature_event.clear()

            if self._stop_event.is_set():
                break
            if self._test_command is None:
                logger.warning(
                    "No test command detected for %s — skipping",
                    self._project_dir,
                )
                continue

            self._last_triggered = self._completed_count
            self._run_number += 1
            run_num = self._run_number
            # Snapshot and clear the trigger buffer
            triggers = list(self._pending_triggers)
            self._pending_triggers.clear()

            # Broadcast start
            await self._state_service.ws_manager.broadcast(
                {"type": "regression_started", "run_number": run_num}
            )

            result = await self._run_tests(run_num)
            result.trigger_features = triggers
            self._last_result = result

            # Auto-dispatch bugfix tasks for regressions
            bugfix_ids: list[str] = []
            if not result.passed:
                bugfix_ids = await self._dispatch_bugfix_tasks(result)

            # Broadcast result
            await self._state_service.ws_manager.broadcast(
                {"type": "regression_result", **result.to_dict()}
            )
            if bugfix_ids:
                await self._state_service.ws_manager.broadcast(
                    {
                        "type": "bugfix_dispatched",
                        "task_ids": bugfix_ids,
                        "run_number": run_num,
                    }
                )
            logger.info(
                "Regression run #%d: %s (%d total, %d failed, %dms)%s",
                run_num,
                "PASS" if result.passed else "FAIL",
                result.total,
                result.failed,
                result.duration_ms,
                f" — dispatched {len(bugfix_ids)} bugfix task(s)" if bugfix_ids else "",
            )

    async def _dispatch_bugfix_tasks(
        self, result: RegressionResult,
    ) -> list[str]:
        """Create bugfix tasks for features implicated in test failures.

        Returns the IDs of created tasks. Respects ``max_bugfix_retries``
        to prevent infinite fix loops.
        """
        from sqlalchemy import select

        from claw_forge.state.models import Session, Task

        # Find the active session (most recent running/pending)
        session_id = self.session_id
        if session_id is None:
            try:
                async with self._state_service._session_factory() as db:
                    sess_result = await db.execute(
                        select(Session)
                        .where(Session.status.in_(["running", "pending"]))
                        .order_by(Session.created_at.desc())
                        .limit(1)
                    )
                    session = sess_result.scalar_one_or_none()
                    if session is None:
                        return []
                    session_id = session.id
            except Exception:  # noqa: BLE001
                logger.warning("Could not determine session for bugfix dispatch")
                return []

        try:
            async with self._state_service._session_factory() as db:
                tasks_result = await db.execute(
                    select(Task).where(Task.session_id == session_id)
                )
                all_tasks = list(tasks_result.scalars().all())

                # Build feature list for implication matching
                features = [
                    {"id": t.id, "name": t.description or t.plugin_name}
                    for t in all_tasks
                    if t.status == "completed" and t.plugin_name != "bugfix"
                ]

                implicated_ids = self._implicate_features(result.output, features)
                result.implicated_feature_ids = implicated_ids
                if not implicated_ids:
                    logger.info("Regression detected but no features implicated")
                    return []

                created_ids: list[str] = []
                for feat_id in implicated_ids:
                    original = next(
                        (t for t in all_tasks if t.id == str(feat_id)),
                        None,
                    )
                    if original is None:
                        continue

                    # Check retry limit
                    existing_retries = max(
                        (
                            t.bugfix_retry_count
                            for t in all_tasks
                            if t.parent_task_id == original.id
                            and t.plugin_name == "bugfix"
                        ),
                        default=0,
                    )
                    if existing_retries >= self._max_bugfix_retries:
                        logger.warning(
                            "Bugfix retry limit (%d) reached for task %s — skipping",
                            self._max_bugfix_retries,
                            original.id,
                        )
                        continue

                    import uuid as _uuid

                    failed_names = ", ".join(result.failed_tests) or "unknown"
                    task_id = str(_uuid.uuid4())
                    new_task = Task(
                        id=task_id,
                        session_id=session_id,
                        plugin_name="bugfix",
                        description=(
                            f"Fix regression: "
                            f"{original.description or original.plugin_name}"
                        ),
                        category="bugfix",
                        depends_on=[original.id],
                        parent_task_id=original.id,
                        bugfix_retry_count=existing_retries + 1,
                        priority=(original.priority or 0) + 10,
                        steps=[
                            f"Failed tests: {failed_names}",
                            "Run the test suite and fix the failing tests.",
                            f"Test output (last 4000 chars):\n{result.output}",
                        ],
                    )
                    db.add(new_task)
                    created_ids.append(task_id)

                if created_ids:
                    await db.commit()
                return created_ids
        except Exception:  # noqa: BLE001
            logger.exception("Failed to dispatch bugfix tasks")
            return []

    async def _run_tests(self, run_number: int) -> RegressionResult:
        """Execute the test command as a subprocess."""
        assert self._test_command is not None
        parts = self._test_command.split()
        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(self._project_dir),
            )
            try:
                stdout_bytes, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=120.0
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                elapsed = int((time.monotonic() - start) * 1000)
                return RegressionResult(
                    passed=False,
                    total=0,
                    failed=0,
                    failed_tests=["TIMEOUT"],
                    duration_ms=elapsed,
                    run_number=run_number,
                    output="Test command timed out after 120s",
                )
        except FileNotFoundError:
            elapsed = int((time.monotonic() - start) * 1000)
            return RegressionResult(
                passed=False,
                total=0,
                failed=0,
                failed_tests=["COMMAND_NOT_FOUND"],
                duration_ms=elapsed,
                run_number=run_number,
                output=f"Command not found: {self._test_command}",
            )

        elapsed = int((time.monotonic() - start) * 1000)
        output = stdout_bytes.decode("utf-8", errors="replace")
        passed = proc.returncode == 0
        total, failed, failed_names = self._parse_output(output)

        return RegressionResult(
            passed=passed,
            total=total,
            failed=failed,
            failed_tests=failed_names,
            duration_ms=elapsed,
            run_number=run_number,
            output=output[-4000:],  # cap stored output
        )

    @staticmethod
    def _parse_output(
        output: str,
    ) -> tuple[int, int, list[str]]:
        """Best-effort parse of test runner output.

        Supports pytest summary lines, jest/npm, cargo test, and go test.
        Returns ``(total, failed, failed_test_names)``.
        """
        total = 0
        failed = 0
        failed_names: list[str] = []

        # pytest: "X passed, Y failed" and/or "Z errors"
        m = re.search(
            r"(\d+) passed(?:.*?(\d+) failed)?", output
        )
        if m:
            p = int(m.group(1))
            f = int(m.group(2)) if m.group(2) else 0
            total = p + f
            failed = f

        # pytest collection errors: "N errors" (e.g. import failures)
        m_err = re.search(r"(\d+) error", output)
        if m_err:
            errs = int(m_err.group(1))
            total += errs
            failed += errs

        # cargo test: "test result: ok. X passed; Y failed"
        m2 = re.search(
            r"test result:.*?(\d+) passed.*?(\d+) failed",
            output,
        )
        if m2:
            p = int(m2.group(1))
            f = int(m2.group(2))
            total = p + f
            failed = f

        # go test: "ok" / "FAIL" lines
        go_ok = len(re.findall(r"^ok\s+", output, re.MULTILINE))
        go_fail = len(
            re.findall(r"^FAIL\s+", output, re.MULTILINE)
        )
        if go_ok + go_fail > total:
            total = go_ok + go_fail
            failed = go_fail

        # Collect FAILED test names (pytest FAILED lines)
        for line in re.findall(
            r"FAILED\s+(\S+)", output
        ):
            failed_names.append(line)

        # cargo FAILED test names
        for line in re.findall(
            r"test\s+(\S+)\s+\.\.\.\s+FAILED", output
        ):
            failed_names.append(line)

        # pytest ERROR lines (collection/import errors)
        for line in re.findall(
            r"ERROR\s+(\S+)", output
        ):
            if line not in failed_names:
                failed_names.append(line)

        return total, failed, failed_names

    def _implicate_features(
        self,
        output: str,
        features: list[dict[str, Any]],
    ) -> list[str]:
        """Match test output to feature names heuristically.

        Looks for feature names (or slugified versions) in the test
        output and returns their IDs.
        """
        implicated: list[str] = []
        output_lower = output.lower()
        for feat in features:
            name = str(feat.get("name", ""))
            feat_id = feat.get("id")
            if not name or feat_id is None:
                continue
            # Check for name or slug in output
            slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            if name.lower() in output_lower or slug in output_lower:
                implicated.append(str(feat_id))
        return implicated
