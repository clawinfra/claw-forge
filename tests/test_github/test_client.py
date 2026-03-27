"""Tests for claw_forge.github.client."""

from __future__ import annotations

import httpx
import pytest
import respx

from claw_forge.github.client import (
    GitHubAPIError,
    GitHubAuthError,
    GitHubClient,
    GitHubClientError,
)

API = "https://api.github.com"


# ── read_issue ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_read_issue_success() -> None:
    """Happy-path: read_issue returns parsed data."""
    issue_payload = {
        "title": "Add authentication",
        "body": "Implement OAuth2 login flow",
        "number": 1,
        "user": {"login": "testuser"},
        "labels": [{"name": "feature"}, {"name": "good first issue"}],
    }
    comments_payload = [
        {"body": "Please use httpx"},
        {"body": ""},  # empty body should be filtered
    ]

    with respx.mock(base_url=API) as mock:
        mock.get("/repos/owner/repo/issues/1").mock(
            return_value=httpx.Response(200, json=issue_payload)
        )
        mock.get("/repos/owner/repo/issues/1/comments").mock(
            return_value=httpx.Response(200, json=comments_payload)
        )

        async with GitHubClient("test-token") as client:
            result = await client.read_issue("owner", "repo", 1)

    assert result["title"] == "Add authentication"
    assert result["body"] == "Implement OAuth2 login flow"
    assert result["number"] == 1
    assert result["user"]["login"] == "testuser"
    assert result["labels"] == ["feature", "good first issue"]
    assert result["comments"] == ["Please use httpx"]  # empty entry filtered


@pytest.mark.asyncio
async def test_read_issue_no_body() -> None:
    """Issues with a null body should return empty string."""
    issue_payload = {
        "title": "Bare issue",
        "body": None,
        "number": 2,
        "user": {"login": "alice"},
        "labels": [],
    }

    with respx.mock(base_url=API) as mock:
        mock.get("/repos/owner/repo/issues/2").mock(
            return_value=httpx.Response(200, json=issue_payload)
        )
        mock.get("/repos/owner/repo/issues/2/comments").mock(
            return_value=httpx.Response(200, json=[])
        )

        async with GitHubClient("test-token") as client:
            result = await client.read_issue("owner", "repo", 2)

    assert result["body"] == ""


@pytest.mark.asyncio
async def test_read_issue_auth_error() -> None:
    """HTTP 401 raises GitHubAuthError."""
    with respx.mock(base_url=API) as mock:
        mock.get("/repos/owner/repo/issues/1").mock(
            return_value=httpx.Response(401)
        )

        async with GitHubClient("invalid-token") as client:
            with pytest.raises(GitHubAuthError):
                await client.read_issue("owner", "repo", 1)


@pytest.mark.asyncio
async def test_read_issue_not_found() -> None:
    """HTTP 404 raises GitHubAPIError with status_code=404."""
    with respx.mock(base_url=API) as mock:
        mock.get("/repos/owner/repo/issues/999").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )

        async with GitHubClient("test-token") as client:
            with pytest.raises(GitHubAPIError) as exc_info:
                await client.read_issue("owner", "repo", 999)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_read_issue_server_error() -> None:
    """HTTP 500 raises GitHubAPIError."""
    with respx.mock(base_url=API) as mock:
        mock.get("/repos/owner/repo/issues/1").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        async with GitHubClient("test-token") as client:
            with pytest.raises(GitHubAPIError) as exc_info:
                await client.read_issue("owner", "repo", 1)

    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_read_issue_comments_failure_is_best_effort() -> None:
    """If the comments endpoint fails, read_issue still succeeds with empty comments."""
    issue_payload = {
        "title": "Test",
        "body": "Body",
        "number": 1,
        "user": {"login": "alice"},
        "labels": [],
    }

    with respx.mock(base_url=API) as mock:
        mock.get("/repos/owner/repo/issues/1").mock(
            return_value=httpx.Response(200, json=issue_payload)
        )
        mock.get("/repos/owner/repo/issues/1/comments").mock(
            return_value=httpx.Response(500, text="oops")
        )

        async with GitHubClient("test-token") as client:
            result = await client.read_issue("owner", "repo", 1)

    assert result["comments"] == []


# ── post_comment ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_comment_success() -> None:
    """Happy-path: post_comment returns API response."""
    response_payload = {"id": 123, "body": "Working on it!"}

    with respx.mock(base_url=API) as mock:
        mock.post("/repos/owner/repo/issues/5/comments").mock(
            return_value=httpx.Response(201, json=response_payload)
        )

        async with GitHubClient("test-token") as client:
            result = await client.post_comment("owner", "repo", 5, "Working on it!")

    assert result["id"] == 123
    assert result["body"] == "Working on it!"


@pytest.mark.asyncio
async def test_post_comment_failure() -> None:
    """Non-success status raises GitHubAPIError."""
    with respx.mock(base_url=API) as mock:
        mock.post("/repos/owner/repo/issues/5/comments").mock(
            return_value=httpx.Response(403, json={"message": "Forbidden"})
        )

        async with GitHubClient("test-token") as client:
            with pytest.raises(GitHubAPIError) as exc_info:
                await client.post_comment("owner", "repo", 5, "hello")

    assert exc_info.value.status_code == 403


# ── create_draft_pr ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_draft_pr_success() -> None:
    """Happy-path: create_draft_pr returns PR details."""
    pr_payload = {
        "id": 456,
        "number": 7,
        "html_url": "https://github.com/owner/repo/pull/7",
        "draft": True,
    }

    with respx.mock(base_url=API) as mock:
        mock.post("/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(201, json=pr_payload)
        )

        async with GitHubClient("test-token") as client:
            result = await client.create_draft_pr(
                "owner", "repo",
                head="feat/github-15",
                base="main",
                title="[GHA] Add authentication",
                body="Closes #15",
                issue_number=15,
            )

    assert result["draft"] is True
    assert result["html_url"] == "https://github.com/owner/repo/pull/7"


@pytest.mark.asyncio
async def test_create_draft_pr_appends_closes() -> None:
    """create_draft_pr appends Closes #N to the body if not present."""
    captured: list[dict] = []

    async def _capture(request: httpx.Request) -> httpx.Response:
        import json as _json
        captured.append(_json.loads(request.content))
        return httpx.Response(201, json={"id": 1, "html_url": "https://x", "draft": True})

    with respx.mock(base_url=API) as mock:
        mock.post("/repos/owner/repo/pulls").mock(side_effect=_capture)

        async with GitHubClient("test-token") as client:
            await client.create_draft_pr(
                "owner", "repo",
                head="feat/github-10",
                base="main",
                title="My PR",
                body="Some description",
                issue_number=10,
            )

    assert "Closes #10" in captured[0]["body"]


@pytest.mark.asyncio
async def test_create_draft_pr_no_duplicate_closes() -> None:
    """create_draft_pr does NOT append Closes #N if already present."""
    captured: list[dict] = []

    async def _capture(request: httpx.Request) -> httpx.Response:
        import json as _json
        captured.append(_json.loads(request.content))
        return httpx.Response(201, json={"id": 1, "html_url": "https://x", "draft": True})

    with respx.mock(base_url=API) as mock:
        mock.post("/repos/owner/repo/pulls").mock(side_effect=_capture)

        async with GitHubClient("test-token") as client:
            await client.create_draft_pr(
                "owner", "repo",
                head="feat/github-10",
                base="main",
                title="My PR",
                body="Description\n\nCloses #10",
                issue_number=10,
            )

    assert captured[0]["body"].count("Closes #10") == 1


@pytest.mark.asyncio
async def test_create_draft_pr_failure() -> None:
    """Non-success status raises GitHubAPIError."""
    with respx.mock(base_url=API) as mock:
        mock.post("/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(422, json={"message": "Validation Failed"})
        )

        async with GitHubClient("test-token") as client:
            with pytest.raises(GitHubAPIError) as exc_info:
                await client.create_draft_pr(
                    "owner", "repo", "feat/x", "main", "Title", "Body"
                )

    assert exc_info.value.status_code == 422


# ── close_issue ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_issue_success() -> None:
    """Happy-path: close_issue returns API response."""
    with respx.mock(base_url=API) as mock:
        mock.patch("/repos/owner/repo/issues/3").mock(
            return_value=httpx.Response(200, json={"state": "closed", "number": 3})
        )

        async with GitHubClient("test-token") as client:
            result = await client.close_issue("owner", "repo", 3)

    assert result["state"] == "closed"


@pytest.mark.asyncio
async def test_close_issue_failure() -> None:
    """Non-success status raises GitHubAPIError."""
    with respx.mock(base_url=API) as mock:
        mock.patch("/repos/owner/repo/issues/3").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )

        async with GitHubClient("test-token") as client:
            with pytest.raises(GitHubAPIError) as exc_info:
                await client.close_issue("owner", "repo", 3)

    assert exc_info.value.status_code == 404


# ── context manager guard ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_client_requires_context_manager() -> None:
    """Calling a method without entering the context manager raises RuntimeError."""
    client = GitHubClient("test-token")
    with pytest.raises(RuntimeError, match="async context manager"):
        await client.read_issue("owner", "repo", 1)


# ── exception hierarchy ───────────────────────────────────────────────────────


def test_auth_error_is_client_error() -> None:
    err = GitHubAuthError("bad token")
    assert isinstance(err, GitHubClientError)


def test_api_error_is_client_error() -> None:
    err = GitHubAPIError("failed", status_code=500)
    assert isinstance(err, GitHubClientError)
    assert err.status_code == 500
