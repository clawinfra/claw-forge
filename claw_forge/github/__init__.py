"""GitHub integration for issue-triggered claw-forge runs.

This module provides:
- :class:`GitHubClient`: async API client for issue reading, comment posting,
  and draft PR creation.
- :class:`IssueSpec`: dataclass for converting a GitHub issue into a spec.
- :class:`GitHubContext`: frozen dataclass holding connection context.
- :class:`ProgressReporter`: hooks into the orchestrator to post real-time
  status updates to the issue as agents work.
"""

from claw_forge.github.client import GitHubAPIError, GitHubAuthError, GitHubClient, GitHubClientError
from claw_forge.github.models import GitHubContext, IssueSpec
from claw_forge.github.reporter import ProgressReporter

__all__ = [
    "GitHubClient",
    "GitHubClientError",
    "GitHubAuthError",
    "GitHubAPIError",
    "IssueSpec",
    "GitHubContext",
    "ProgressReporter",
]
