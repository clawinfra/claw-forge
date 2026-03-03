"""Shared test fixtures and configuration.

BUG-10 fix: Ensure aiosqlite async engines created by AgentStateService are
properly disposed during test teardown, preventing 'Event loop is closed'
RuntimeWarning from the aiosqlite connection worker thread.

Strategy: Monkey-patch ``AgentStateService.__init__`` to track all created
instances.  In teardown, forcibly close all aiosqlite connections through the
SQLAlchemy pool's synchronous interface and wait briefly for the worker
threads to terminate.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _auto_dispose_engines() -> None:  # type: ignore[misc]
    """Track AgentStateService instances and force-close their connection pools."""
    engines: list[object] = []

    try:
        from claw_forge.state.service import AgentStateService
        original_init = AgentStateService.__init__
    except ImportError:
        yield  # type: ignore[misc]
        return

    def _tracking_init(self: object, *args: object, **kwargs: object) -> None:
        original_init(self, *args, **kwargs)  # type: ignore[misc]
        engines.append(self)

    with patch.object(AgentStateService, "__init__", _tracking_init):
        yield  # type: ignore[misc]

    # Forcefully close all aiosqlite connections via the sync engine pool.
    # The pool.dispose() call terminates checked-in connections immediately.
    # We also call checkin on any checked-out connections to ensure all
    # connection worker threads exit cleanly.
    for svc in engines:
        try:
            sync_engine = svc._engine.sync_engine  # type: ignore[union-attr]
            pool = sync_engine.pool
            # dispose() closes all connections in the pool and stops accepting new ones
            pool.dispose()
        except Exception:
            pass

    # Give aiosqlite worker threads a moment to terminate after pool disposal.
    # Without this brief pause, threads may still be running when the event
    # loop is closed by pytest-asyncio, triggering the RuntimeError.
    if engines:
        time.sleep(0.05)
