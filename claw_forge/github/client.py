"""Async GitHub API client for issue-triggered claw-forge runs.

Supports:
- Reading issues (title, description, comments)
- Posting comments
- Creating draft PRs
- Closing issues

Uses GitHub REST API v3.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class GitHubClientError(Exception):
    """Base exception for GitHub client errors."""


class GitHubAuthError(GitHubClientError):
    """Raised when authentication fails (401)."""


class GitHubAPIError(GitHubClientError):
    """Raised when a GitHub API request fails."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GitHubClient:
    """Async GitHub API client.

    Uses Personal Access Token (PAT) or GitHub App token for authentication.
    Must be used as an async context manager:

    Example::

        async with GitHubClient(token="ghp_...") as client:
            issue = await client.read_issue("clawinfra", "claw-forge", 15)
            await client.post_comment("clawinfra", "claw-forge", 15, "Working on it...")
    """

    API_BASE = "https://api.github.com"

    def __init__(self, token: str, *, timeout: float = 30.0) -> None:
        """Initialise the GitHub client.

        Args:
            token: GitHub Personal Access Token or built-in GITHUB_TOKEN.
            timeout: Per-request timeout in seconds.
        """
        self.token = token
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> GitHubClient:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "claw-forge/0.x",
        }
        self._client = httpx.AsyncClient(
            base_url=self.API_BASE,
            headers=headers,
            timeout=self.timeout,
        )
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "GitHubClient must be used as an async context manager. "
                "Use: async with GitHubClient(...) as client: ..."
            )
        return self._client

    # ── Public API methods ────────────────────────────────────────────────────

    async def read_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
    ) -> dict[str, Any]:
        """Read issue data from GitHub.

        Returns a dict with keys:
        - ``title``: str
        - ``body``: str
        - ``number``: int
        - ``user``: dict (login, ...)
        - ``labels``: list[str]
        - ``comments``: list[str]

        Raises:
            GitHubAuthError: if the token is invalid (HTTP 401).
            GitHubAPIError: if the request fails for any other reason.
        """
        client = self._get_client()

        response = await client.get(f"/repos/{owner}/{repo}/issues/{issue_number}")

        if response.status_code == 401:
            raise GitHubAuthError("Invalid GitHub token (HTTP 401)")
        if response.status_code == 404:
            raise GitHubAPIError(
                f"Issue #{issue_number} not found in {owner}/{repo}",
                status_code=404,
            )
        if not response.is_success:
            raise GitHubAPIError(
                f"Failed to read issue: {response.text}",
                status_code=response.status_code,
            )

        issue = response.json()

        # Fetch comments (best-effort — silently skip on failure)
        comments: list[str] = []
        try:
            comments_resp = await client.get(
                f"/repos/{owner}/{repo}/issues/{issue_number}/comments"
            )
            if comments_resp.is_success:
                comments = [c["body"] for c in comments_resp.json() if c.get("body")]
        except httpx.HTTPError:
            logger.warning("Could not fetch comments for issue #%d", issue_number)

        return {
            "title": issue["title"],
            "body": issue.get("body") or "",
            "number": issue["number"],
            "user": issue["user"],
            "labels": [label["name"] for label in issue.get("labels", [])],
            "comments": comments,
        }

    async def post_comment(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        body: str,
    ) -> dict[str, Any]:
        """Post a comment to an issue or PR.

        Args:
            owner: Repository owner.
            repo: Repository name.
            issue_number: Issue or PR number.
            body: Comment body (markdown).

        Returns:
            API response dict.

        Raises:
            GitHubAPIError: if the request fails.
        """
        client = self._get_client()

        response = await client.post(
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json={"body": body},
        )

        if not response.is_success:
            raise GitHubAPIError(
                f"Failed to post comment: {response.text}",
                status_code=response.status_code,
            )

        return response.json()  # type: ignore[no-any-return]

    async def create_draft_pr(
        self,
        owner: str,
        repo: str,
        head: str,
        base: str,
        title: str,
        body: str,
        issue_number: int | None = None,
    ) -> dict[str, Any]:
        """Create a draft pull request.

        Args:
            owner: Repository owner.
            repo: Repository name.
            head: Source branch (e.g. ``feat/github-15``).
            base: Target branch (e.g. ``main``).
            title: PR title.
            body: PR description (markdown).
            issue_number: If provided, appends ``Closes #N`` to body.

        Returns:
            API response dict with PR details (includes ``html_url``).

        Raises:
            GitHubAPIError: if the request fails.
        """
        client = self._get_client()

        if issue_number is not None:
            closes = f"\n\nCloses #{issue_number}"
            if closes not in body:
                body = f"{body}{closes}"

        payload: dict[str, Any] = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
            "draft": True,
        }

        response = await client.post(
            f"/repos/{owner}/{repo}/pulls",
            json=payload,
        )

        if not response.is_success:
            raise GitHubAPIError(
                f"Failed to create PR: {response.text}",
                status_code=response.status_code,
            )

        return response.json()  # type: ignore[no-any-return]

    async def close_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
    ) -> dict[str, Any]:
        """Close an issue.

        Args:
            owner: Repository owner.
            repo: Repository name.
            issue_number: Issue number.

        Returns:
            API response dict.

        Raises:
            GitHubAPIError: if the request fails.
        """
        client = self._get_client()

        response = await client.patch(
            f"/repos/{owner}/{repo}/issues/{issue_number}",
            json={"state": "closed"},
        )

        if not response.is_success:
            raise GitHubAPIError(
                f"Failed to close issue: {response.text}",
                status_code=response.status_code,
            )

        return response.json()  # type: ignore[no-any-return]
