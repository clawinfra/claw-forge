"""Claude CLI OAuth token reader.

The Claude CLI stores OAuth tokens at standard platform-specific paths after
``claude login``.  This module auto-reads the token so users don't need to
copy it manually — claw-forge picks it up automatically.

Supported credential paths (checked in order):

- ``~/.claude/.credentials.json``           — Linux/Windows default
- ``~/.config/claude/credentials.json``     — XDG config dir
- ``~/Library/Application Support/Claude/credentials.json``  — macOS

Token JSON format stored by the Claude CLI::

    {
        "accessToken": "sk-ant-oat01-...",
        "expiresAt": "2025-12-31T00:00:00Z"
    }

Usage::

    from claw_forge.pool.providers.oauth import read_claude_oauth_token, get_oauth_provider_config

    # Simple token read
    token = read_claude_oauth_token()

    # Build a provider config automatically
    config = get_oauth_provider_config()
    if config:
        # Use config in your provider pool
        ...
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from claw_forge.pool.providers.base import ProviderConfig, ProviderType

logger = logging.getLogger(__name__)

# Standard credential paths used by the Claude CLI across platforms
CLAUDE_CREDENTIALS_PATHS: list[Path] = [
    Path.home() / ".claude" / ".credentials.json",
    Path.home() / ".config" / "claude" / "credentials.json",
    Path.home() / "Library" / "Application Support" / "Claude" / "credentials.json",
]


def read_claude_oauth_token(
    extra_paths: list[Path] | None = None,
) -> str | None:
    """Read the Claude CLI OAuth token from standard credential paths.

    Args:
        extra_paths: Optional additional paths to check before the standard ones.

    Returns:
        The OAuth access token string, or ``None`` if no valid token was found.
    """
    search_paths = list(extra_paths or []) + CLAUDE_CREDENTIALS_PATHS
    for path in search_paths:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.debug("Failed to parse Claude credentials at %s: %s", path, exc)
            continue

        # Claude CLI uses "accessToken" (camelCase) in recent versions.
        # Older builds may use "access_token" (snake_case).
        token: str | None = data.get("accessToken") or data.get("access_token")
        if token:
            logger.debug("Loaded Claude OAuth token from %s", path)
            return token

    return None


def get_oauth_token_optional(
    extra_paths: list[Path] | None = None,
) -> str | None:
    """Return the Claude CLI OAuth token, or ``None`` if not found.

    This is a *safe* variant of :func:`read_claude_oauth_token` that is
    guaranteed never to raise.  It returns ``None`` when the credentials
    file is missing, malformed, or lacks a token — and logs a debug-level
    warning for each non-fatal failure.

    Args:
        extra_paths: Optional additional credential paths to check first.

    Returns:
        The OAuth access token string, or ``None``.
    """
    try:
        return read_claude_oauth_token(extra_paths=extra_paths)
    except Exception as exc:  # pragma: no cover — belt-and-suspenders guard
        logger.debug("Unexpected error reading Claude OAuth token: %s", exc)
        return None


def get_oauth_provider_config(
    name: str = "claude-oauth",
    priority: int = 1,
    extra_paths: list[Path] | None = None,
) -> ProviderConfig | None:
    """Auto-create a :class:`~claw_forge.pool.providers.base.ProviderConfig` from
    the Claude CLI OAuth token.

    This is a convenience helper for the ``anthropic_oauth`` provider type.
    It reads the token from disk and returns a fully configured
    :class:`ProviderConfig` that can be used directly with
    :class:`~claw_forge.pool.providers.anthropic.AnthropicProvider`.

    Args:
        name: Provider name to assign (default: ``"claude-oauth"``).
        priority: Scheduling priority (default: ``1``).
        extra_paths: Additional credential paths to check first.

    Returns:
        A :class:`ProviderConfig` with ``oauth_token`` set, or ``None`` if no
        valid token could be found.
    """
    token = read_claude_oauth_token(extra_paths=extra_paths)
    if not token:
        logger.debug("No Claude OAuth token found; skipping oauth provider '%s'", name)
        return None
    return ProviderConfig(
        name=name,
        provider_type=ProviderType.ANTHROPIC,
        oauth_token=token,
        priority=priority,
    )
