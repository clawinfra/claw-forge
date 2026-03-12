"""Harbor API adapter for Terminal Bench 2.0 evaluation.

Wraps Harbor's agent protocol and translates it to claw-forge run_agent() calls.
All Harbor HTTP calls use httpx (synchronous client). The run_task() method is
async because it calls run_agent() which is async.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exception classes
# ---------------------------------------------------------------------------


class HarborError(Exception):
    """Base class for all Harbor adapter errors."""


class HarborAPIError(HarborError):
    """HTTP-level error from Harbor API (non-2xx response)."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"Harbor API error {status_code}: {message}")


class HarborTaskNotFoundError(HarborError):
    """Task ID does not exist in this Harbor run."""


class HarborScoringError(HarborError):
    """Harbor returned a malformed or incomplete scoring response."""


class HarborTimeoutError(HarborError):
    """Task exceeded its timeout budget."""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HarborTask:
    """A task received from the Harbor API."""

    task_id: str
    description: str
    sandbox_url: str
    working_dir: str
    scoring_url: str
    timeout_s: int
    metadata: dict[str, Any]


@dataclass
class TaskResult:
    """Result of running one (config, rep, task) triple."""

    config_id: str
    task_id: str
    rep: int
    score: float
    passed: bool
    duration_s: float
    error: str | None
    raw_scoring: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AblationConfig:
    """Configuration for one ablation variant."""

    config_id: str
    edit_mode: str
    pre_completion_hook: bool
    loop_detection_hook: bool
    description: str


# Canonical registry — single source of truth
ABLATION_CONFIGS: dict[str, AblationConfig] = {
    "A": AblationConfig("A", "str_replace", False, False, "baseline"),
    "B": AblationConfig("B", "hashline", False, False, "hashline"),
    "C": AblationConfig("C", "str_replace", True, False, "verify"),
    "D": AblationConfig("D", "str_replace", False, True, "loop"),
    "E": AblationConfig("E", "hashline", True, True, "full"),
}


# ---------------------------------------------------------------------------
# HarborAdapter
# ---------------------------------------------------------------------------

_MAX_RETRIES = 2
_RETRY_DELAY_S = 2.0


class HarborAdapter:
    """HTTP client wrapping Harbor's agent protocol.

    Harbor orchestrates task sandboxes (via Daytona), calls the agent,
    and scores the output.  This adapter bridges Harbor → claw-forge.

    Protocol summary (see docs/benchmarks/harbor-protocol.md):
      POST /api/v1/tasks/{task_id}/start     → HarborTask metadata
      POST /api/v1/tasks/{task_id}/submit    → ScoringResponse
      GET  /api/v1/tasks                     → list[task_id]
    """

    def __init__(
        self,
        harbor_base_url: str,
        harbor_api_key: str,
        *,
        request_timeout_s: float = 30.0,
        task_timeout_s: int = 300,
    ) -> None:
        self.harbor_base_url = harbor_base_url.rstrip("/")
        self.harbor_api_key = harbor_api_key
        self.request_timeout_s = request_timeout_s
        self.task_timeout_s = task_timeout_s
        self._client = httpx.Client(
            base_url=self.harbor_base_url,
            headers={
                "Authorization": f"Bearer {harbor_api_key}",
                "Content-Type": "application/json",
            },
            timeout=request_timeout_s,
        )

    # -- public helpers -----------------------------------------------------

    def list_tasks(self) -> list[str]:
        """Return all task IDs available in this Harbor benchmark run."""
        resp = self._request_with_retry("GET", "/api/v1/tasks")
        data = resp.json()
        if not isinstance(data, list):
            raise HarborAPIError(resp.status_code, "Expected list of task IDs")
        return [str(t) for t in data]

    def start_task(self, task_id: str) -> HarborTask:
        """Start a task and retrieve its specification from Harbor."""
        resp = self._request_with_retry("POST", f"/api/v1/tasks/{task_id}/start")
        data = resp.json()
        return HarborTask(
            task_id=data["task_id"],
            description=data["description"],
            sandbox_url=data["sandbox_url"],
            working_dir=data["working_dir"],
            scoring_url=data["scoring_url"],
            timeout_s=data.get("timeout_s", self.task_timeout_s),
            metadata=data.get("metadata", {}),
        )

    def submit_result(
        self,
        task: HarborTask,
        agent_output: str,
    ) -> dict[str, Any]:
        """Submit agent output to Harbor for scoring."""
        payload = {"task_id": task.task_id, "agent_output": agent_output}
        resp = self._request_with_retry(
            "POST",
            task.scoring_url,
            json=payload,
            is_absolute_url=True,
        )
        data: dict[str, Any] = resp.json()
        if "score" not in data or "passed" not in data:
            raise HarborScoringError(
                f"Malformed scoring response: missing 'score' or 'passed' in {data!r}"
            )
        return data

    async def run_task(
        self,
        task_id: str,
        *,
        config: AblationConfig,
        rep: int = 1,
        model: str = "claude-sonnet-4-6",
        dry_run: bool = False,
    ) -> TaskResult:
        """Run one (task, config, rep) triple end-to-end.

        Never raises — all exceptions are caught and returned as
        TaskResult(error=str(e)).
        """
        start = time.monotonic()
        try:
            task = self.start_task(task_id)

            if dry_run:
                return TaskResult(
                    config_id=config.config_id,
                    task_id=task_id,
                    rep=rep,
                    score=0.0,
                    passed=False,
                    duration_s=time.monotonic() - start,
                    error="dry-run",
                )

            prompt = self._build_prompt(task)
            hooks = self._build_hooks(config)
            effective_timeout = task.timeout_s or self.task_timeout_s

            # Import run_agent lazily to avoid hard import errors in tests
            from claw_forge.sdk import run_agent

            agent_output = ""
            try:
                result_messages = await asyncio.wait_for(
                    run_agent(
                        prompt,
                        model=model,
                        edit_mode=config.edit_mode,
                        hooks=hooks,
                    ),
                    timeout=effective_timeout,
                )
                # Collect final text from result messages
                if hasattr(result_messages, "result"):
                    agent_output = str(result_messages.result)
                elif isinstance(result_messages, str):
                    agent_output = result_messages
                else:
                    agent_output = str(result_messages)
            except TimeoutError:
                return TaskResult(
                    config_id=config.config_id,
                    task_id=task_id,
                    rep=rep,
                    score=0.0,
                    passed=False,
                    duration_s=time.monotonic() - start,
                    error=f"timeout after {effective_timeout}s",
                )

            scoring = self.submit_result(task, agent_output)
            return TaskResult(
                config_id=config.config_id,
                task_id=task_id,
                rep=rep,
                score=float(scoring["score"]),
                passed=bool(scoring["passed"]),
                duration_s=time.monotonic() - start,
                error=None,
                raw_scoring=scoring,
            )

        except Exception as exc:  # noqa: BLE001
            return TaskResult(
                config_id=config.config_id,
                task_id=task_id,
                rep=rep,
                score=0.0,
                passed=False,
                duration_s=time.monotonic() - start,
                error=str(exc),
            )

    # -- private helpers ----------------------------------------------------

    def _build_prompt(self, task: HarborTask) -> str:
        """Translate a HarborTask into a claw-forge agent prompt string."""
        return (
            f"Solve the following task in {task.working_dir}:\n\n"
            f"{task.description}\n\n"
            "After making changes, verify your solution by running any available "
            "tests. Ensure the code compiles/passes before submitting."
        )

    def _build_hooks(self, config: AblationConfig) -> dict[str, Any]:
        """Build the SDK hooks dict for a given ablation config."""
        hooks: dict[str, Any] = {"edit_mode": config.edit_mode}
        if config.pre_completion_hook:
            hooks["pre_completion_checklist"] = True
        if config.loop_detection_hook:
            hooks["loop_detection"] = True
        return hooks

    def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        is_absolute_url: bool = False,
    ) -> httpx.Response:
        """Make an HTTP request with retry on 5xx errors.

        Retries up to _MAX_RETRIES times with _RETRY_DELAY_S fixed delay.
        Raises HarborTaskNotFoundError on 404, HarborAPIError on other non-2xx.
        """
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                if is_absolute_url:
                    resp = self._client.request(method, url, json=json)
                else:
                    resp = self._client.request(method, url, json=json)
                if resp.status_code == 404:
                    raise HarborTaskNotFoundError(f"Task not found: {url}")
                if 500 <= resp.status_code < 600:
                    exc = HarborAPIError(resp.status_code, resp.text)
                    if attempt < _MAX_RETRIES:
                        logger.warning(
                            "Harbor %s %s returned %d, retrying (%d/%d)...",
                            method,
                            url,
                            resp.status_code,
                            attempt + 1,
                            _MAX_RETRIES,
                        )
                        time.sleep(_RETRY_DELAY_S)
                        last_exc = exc
                        continue
                    raise exc
                if resp.status_code >= 400:
                    raise HarborAPIError(resp.status_code, resp.text)
                return resp
            except httpx.HTTPError as exc:
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        "Harbor %s %s network error: %s, retrying (%d/%d)...",
                        method,
                        url,
                        exc,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    time.sleep(_RETRY_DELAY_S)
                    last_exc = exc
                    continue
                raise HarborAPIError(0, str(exc)) from exc
        # Should not reach here, but satisfy type checker
        raise last_exc or HarborAPIError(0, "Unknown error")  # pragma: no cover
