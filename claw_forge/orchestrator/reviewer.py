"""ParallelReviewer — background regression test runner.

Detects the project's test command, runs it periodically as features
complete, and broadcasts results via the state service WebSocket.
This is a pure asyncio subprocess task — **not** an LLM session.
"""

from __future__ import annotations

import asyncio
import contextlib
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
    implicated_feature_ids: list[int] = field(default_factory=list)
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
    ) -> None:
        self._project_dir = Path(project_dir)
        self._state_service = state_service
        self._interval = max(1, interval_features)
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._feature_event = asyncio.Event()
        self._completed_count = 0
        self._last_triggered = 0
        self._run_number = 0
        self._last_result: RegressionResult | None = None
        self._test_command = detect_test_command(self._project_dir)

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

    def notify_feature_completed(self) -> None:
        """Call when a feature completes to potentially trigger a run."""
        self._completed_count += 1
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

            # Broadcast start
            await self._state_service.ws_manager.broadcast(
                {"type": "regression_started", "run_number": run_num}
            )

            result = await self._run_tests(run_num)
            self._last_result = result

            # Broadcast result
            await self._state_service.ws_manager.broadcast(
                {"type": "regression_result", **result.to_dict()}
            )
            logger.info(
                "Regression run #%d: %s (%d total, %d failed, %dms)",
                run_num,
                "PASS" if result.passed else "FAIL",
                result.total,
                result.failed,
                result.duration_ms,
            )

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

        # pytest: "X passed, Y failed"
        m = re.search(
            r"(\d+) passed(?:.*?(\d+) failed)?", output
        )
        if m:
            p = int(m.group(1))
            f = int(m.group(2)) if m.group(2) else 0
            total = p + f
            failed = f

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

        return total, failed, failed_names

    def _implicate_features(
        self,
        output: str,
        features: list[dict[str, Any]],
    ) -> list[int]:
        """Match test output to feature names heuristically.

        Looks for feature names (or slugified versions) in the test
        output and returns their IDs.
        """
        implicated: list[int] = []
        output_lower = output.lower()
        for feat in features:
            name = str(feat.get("name", ""))
            feat_id = feat.get("id")
            if not name or feat_id is None:
                continue
            # Check for name or slug in output
            slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            if name.lower() in output_lower or slug in output_lower:
                with contextlib.suppress(ValueError, TypeError):
                    implicated.append(int(feat_id))
        return implicated
