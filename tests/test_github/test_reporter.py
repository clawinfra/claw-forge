"""Tests for claw_forge.github.reporter."""

from __future__ import annotations

import httpx
import pytest
import respx

from claw_forge.github.client import GitHubClient
from claw_forge.github.models import GitHubContext
from claw_forge.github.reporter import ProgressReporter

API = "https://api.github.com"

_CTX = GitHubContext(
    owner="owner",
    repo="repo",
    issue_number=1,
    token="test-token",
    branch_name="feat/github-1",
)


def _comment_mock(mock: respx.MockRouter) -> list[str]:
    """Register a comment mock and return a list that accumulates posted bodies."""
    bodies: list[str] = []

    async def _capture(request: httpx.Request) -> httpx.Response:
        import json

        payload = json.loads(request.content)
        bodies.append(payload["body"])
        return httpx.Response(201, json={"id": len(bodies), "body": payload["body"]})

    mock.post(f"/repos/{_CTX.owner}/{_CTX.repo}/issues/{_CTX.issue_number}/comments").mock(
        side_effect=_capture
    )
    return bodies


# ── start / stop ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reporter_start_stop() -> None:
    """Reporter starts and stops cleanly without errors (no comments posted)."""
    with respx.mock(base_url=API, assert_all_called=False) as mock:
        _comment_mock(mock)

        async with GitHubClient("test-token") as client:
            reporter = ProgressReporter(client, _CTX)
            await reporter.start()
            await reporter.stop()


# ── report_start ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_report_start_posts_comment() -> None:
    with respx.mock(base_url=API) as mock:
        bodies = _comment_mock(mock)

        async with GitHubClient("test-token") as client:
            reporter = ProgressReporter(client, _CTX)
            await reporter.start()
            await reporter.report_start(10, "coding")
            await reporter.stop()

    assert len(bodies) == 1
    assert "claw-forge started" in bodies[0]
    assert "coding" in bodies[0]
    assert "10" in bodies[0]
    assert _CTX.branch_name in bodies[0]


# ── report_task_start / complete / error ──────────────────────────────────────


@pytest.mark.asyncio
async def test_report_task_lifecycle() -> None:
    with respx.mock(base_url=API) as mock:
        bodies = _comment_mock(mock)

        async with GitHubClient("test-token") as client:
            reporter = ProgressReporter(client, _CTX)
            await reporter.start()
            await reporter.report_task_start("task-abc", "Add login endpoint")
            await reporter.report_task_complete("task-abc")
            await reporter.report_task_error("task-xyz", "Connection refused")
            await reporter.stop()

    assert len(bodies) == 3
    assert "task-abc" in bodies[0]
    assert "Add login endpoint" in bodies[0]
    assert "✅" in bodies[1]
    assert "task-abc" in bodies[1]
    assert "❌" in bodies[2]
    assert "task-xyz" in bodies[2]
    assert "Connection refused" in bodies[2]


# ── report_summary ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_report_summary_with_pr_url() -> None:
    with respx.mock(base_url=API) as mock:
        bodies = _comment_mock(mock)

        async with GitHubClient("test-token") as client:
            reporter = ProgressReporter(client, _CTX)
            await reporter.start()
            await reporter.report_summary(
                completed=8, failed=2, pr_url="https://github.com/owner/repo/pull/1"
            )
            await reporter.stop()

    assert len(bodies) == 1
    body = bodies[0]
    assert "8" in body
    assert "2" in body
    assert "https://github.com/owner/repo/pull/1" in body


@pytest.mark.asyncio
async def test_report_summary_without_pr_url() -> None:
    with respx.mock(base_url=API) as mock:
        bodies = _comment_mock(mock)

        async with GitHubClient("test-token") as client:
            reporter = ProgressReporter(client, _CTX)
            await reporter.start()
            await reporter.report_summary(completed=5, failed=0, pr_url=None)
            await reporter.stop()

    assert len(bodies) == 1
    assert "5" in bodies[0]


@pytest.mark.asyncio
async def test_report_summary_failure_hint() -> None:
    """When there are failures and no PR, the summary includes a retry hint."""
    with respx.mock(base_url=API) as mock:
        bodies = _comment_mock(mock)

        async with GitHubClient("test-token") as client:
            reporter = ProgressReporter(client, _CTX)
            await reporter.start()
            await reporter.report_summary(completed=3, failed=2, pr_url=None)
            await reporter.stop()

    assert "failed" in bodies[0].lower() or "retry" in bodies[0].lower()


# ── API failure resilience ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reporter_survives_api_failure() -> None:
    """Comment posting errors are swallowed — reporter keeps running."""
    with respx.mock(base_url=API) as mock:
        mock.post(
            f"/repos/{_CTX.owner}/{_CTX.repo}/issues/{_CTX.issue_number}/comments"
        ).mock(return_value=httpx.Response(500, text="Server Error"))

        async with GitHubClient("test-token") as client:
            reporter = ProgressReporter(client, _CTX)
            await reporter.start()
            await reporter.report_start(3, "coding")
            await reporter.report_task_complete("t-1")
            await reporter.stop()
        # No exception raised — reporter survived the 500s
