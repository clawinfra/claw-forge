"""Tests for optional PostgreSQL backend support.

All tests run against SQLite (CI has no PostgreSQL) but verify that
the backend detection logic and SQLite-specific guards work correctly.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from claw_forge.state.backend import (
    default_sqlite_url,
    is_postgres,
    is_sqlite,
    mask_url_password,
    resolve_database_url,
)


class TestBackendDetection:
    def test_sqlite_url(self) -> None:
        assert is_sqlite("sqlite+aiosqlite:///./state.db")

    def test_sqlite_memory(self) -> None:
        assert is_sqlite("sqlite+aiosqlite:///:memory:")

    def test_postgres_asyncpg(self) -> None:
        assert is_postgres("postgresql+asyncpg://user:pw@host/db")

    def test_postgres_plain(self) -> None:
        assert is_postgres("postgresql://localhost/db")

    def test_not_postgres(self) -> None:
        assert not is_postgres("sqlite+aiosqlite:///./state.db")

    def test_not_sqlite(self) -> None:
        assert not is_sqlite("postgresql+asyncpg://host/db")


class TestResolveUrl:
    def test_cli_override_wins(self, tmp_path: Path) -> None:
        url = resolve_database_url(
            cli_override="postgresql+asyncpg://a/b",
            env_override="sqlite+aiosqlite:///c",
            config={"database_url": "sqlite+aiosqlite:///d"},
            project_path=tmp_path,
        )
        assert url == "postgresql+asyncpg://a/b"

    def test_env_override_second(self, tmp_path: Path) -> None:
        url = resolve_database_url(
            env_override="postgresql+asyncpg://env/db",
            config={"database_url": "sqlite+aiosqlite:///d"},
            project_path=tmp_path,
        )
        assert url == "postgresql+asyncpg://env/db"

    def test_config_third(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("CLAW_FORGE_DB_URL", None)
            url = resolve_database_url(
                config={"database_url": "postgresql+asyncpg://cfg/db"},
                project_path=tmp_path,
            )
        assert url == "postgresql+asyncpg://cfg/db"

    def test_default_sqlite(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {}, clear=True):
            url = resolve_database_url(project_path=tmp_path)
        assert "sqlite" in url
        assert str(tmp_path) in url

    def test_env_var_fallback(self, tmp_path: Path) -> None:
        with patch.dict(
            "os.environ",
            {"CLAW_FORGE_DB_URL": "postgresql+asyncpg://env2/db"},
        ):
            url = resolve_database_url(project_path=tmp_path)
        assert url == "postgresql+asyncpg://env2/db"


class TestDefaultSqliteUrl:
    def test_creates_parent_dir(self, tmp_path: Path) -> None:
        url = default_sqlite_url(tmp_path)
        assert "sqlite+aiosqlite:///" in url
        assert (tmp_path / ".claw-forge").is_dir()


class TestMaskPassword:
    def test_masks_password(self) -> None:
        assert mask_url_password(
            "postgresql+asyncpg://user:secret@host/db"
        ) == "postgresql+asyncpg://user:***@host/db"

    def test_no_password(self) -> None:
        url = "sqlite+aiosqlite:///./state.db"
        assert mask_url_password(url) == url

    def test_no_at_sign(self) -> None:
        url = "sqlite+aiosqlite:///:memory:"
        assert mask_url_password(url) == url


_HAS_ASYNCPG = False
try:
    import asyncpg  # noqa: F401
    _HAS_ASYNCPG = True
except ModuleNotFoundError:
    pass

_skip_no_asyncpg = pytest.mark.skipif(
    not _HAS_ASYNCPG, reason="asyncpg not installed",
)


class TestSqliteGuards:
    """Verify SQLite-specific code is skipped for PostgreSQL URLs."""

    @_skip_no_asyncpg
    def test_no_atexit_for_postgres(self) -> None:
        from claw_forge.state.service import AgentStateService

        with patch("atexit.register") as mock_reg:
            AgentStateService(
                "postgresql+asyncpg://user:pw@localhost/db"
            )
            mock_reg.assert_not_called()

    def test_atexit_registered_for_sqlite(self, tmp_path: Path) -> None:
        from claw_forge.state.service import AgentStateService

        db_path = tmp_path / "test.db"
        with patch("atexit.register") as mock_reg:
            AgentStateService(f"sqlite+aiosqlite:///{db_path}")
            mock_reg.assert_called_once()

    @_skip_no_asyncpg
    def test_is_sqlite_flag_postgres(self) -> None:
        from claw_forge.state.service import AgentStateService

        svc = AgentStateService(
            "postgresql+asyncpg://user:pw@localhost/db"
        )
        assert svc._is_sqlite is False

    def test_is_sqlite_flag_sqlite(self, tmp_path: Path) -> None:
        from claw_forge.state.service import AgentStateService

        svc = AgentStateService(
            f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        )
        assert svc._is_sqlite is True

    @_skip_no_asyncpg
    def test_project_path_explicit(self) -> None:
        """PostgreSQL: project_path must be passed explicitly."""
        from claw_forge.state.service import AgentStateService

        svc = AgentStateService(
            "postgresql+asyncpg://user:pw@localhost/db",
            project_path=Path("/my/project"),
        )
        assert svc._project_path == Path("/my/project")

    def test_is_sqlite_detection_without_engine(self) -> None:
        """Backend detection works via URL string, no driver needed."""
        from claw_forge.state.backend import is_postgres, is_sqlite
        pg_url = "postgresql+asyncpg://user:pw@localhost/db"
        assert is_postgres(pg_url)
        assert not is_sqlite(pg_url)

    @pytest.mark.asyncio
    async def test_init_db_skips_pragma_for_postgres_url(
        self, tmp_path: Path,
    ) -> None:
        """init_db doesn't run PRAGMA quick_check for non-SQLite."""
        from claw_forge.state.service import AgentStateService

        # Use SQLite but set _is_sqlite=False to simulate PG path
        db_path = tmp_path / "test.db"
        svc = AgentStateService(f"sqlite+aiosqlite:///{db_path}")
        svc._is_sqlite = False
        try:
            await svc.init_db()
        finally:
            await svc.dispose()
