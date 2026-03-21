"""Database backend detection and URL resolution.

Centralizes logic for determining whether the configured database is
SQLite (default) or PostgreSQL (opt-in), and for resolving the
database URL from CLI flags, environment variables, and config.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def is_sqlite(database_url: str) -> bool:
    """Return True if *database_url* targets a SQLite database."""
    return "sqlite" in database_url.lower()


def is_postgres(database_url: str) -> bool:
    """Return True if *database_url* targets a PostgreSQL database."""
    lower = database_url.lower()
    return "postgresql" in lower or "postgres" in lower


def default_sqlite_url(project_path: Path) -> str:
    """Return the default SQLite URL for a project directory."""
    db_path = project_path / ".claw-forge" / "state.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{db_path}"


def resolve_database_url(
    *,
    cli_override: str | None = None,
    env_override: str | None = None,
    config: dict[str, Any] | None = None,
    project_path: Path | None = None,
) -> str:
    """Determine the database URL from (in priority order):

    1. *cli_override* — ``--database-url`` CLI flag
    2. *env_override* — ``CLAW_FORGE_DB_URL`` environment variable
    3. *config* — ``state.database_url`` in ``claw-forge.yaml``
    4. Default SQLite at ``{project_path}/.claw-forge/state.db``
    """
    if cli_override:
        return cli_override
    if env_override:
        return env_override
    env_val = os.environ.get("CLAW_FORGE_DB_URL")
    if env_val:
        return env_val
    if config:
        cfg_url = config.get("database_url")
        if cfg_url:
            return str(cfg_url)
    project = project_path or Path(".")
    return default_sqlite_url(project.resolve())


def mask_url_password(url: str) -> str:
    """Replace the password portion of a database URL with ``***``."""
    # postgresql+asyncpg://user:secret@host/db → ...user:***@host/db
    if "@" in url and ":" in url.split("@")[0]:
        before_at, after_at = url.rsplit("@", 1)
        scheme_user, _password = before_at.rsplit(":", 1)
        return f"{scheme_user}:***@{after_at}"
    return url
