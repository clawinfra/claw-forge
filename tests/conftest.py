"""Shared test fixtures and configuration.

BUG-10 fix: Ensure aiosqlite async engines created by AgentStateService are
properly disposed during test teardown, preventing 'Event loop is closed'
RuntimeWarning from the aiosqlite connection worker thread.

Strategy: Monkey-patch ``AgentStateService.__init__`` to track all created
instances.  In teardown, synchronously close the underlying aiosqlite
connections via the engine's pool.  This avoids the asyncio event loop
entirely and prevents the worker thread from encountering a closed loop.
"""

from __future__ import annotations

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

    # Synchronously dispose the SQLAlchemy pool to close aiosqlite connections.
    # The sync_engine.pool.dispose() terminates the connection-worker threads
    # without needing a running asyncio event loop.
    for svc in engines:
        try:
            sync_engine = svc._engine.sync_engine  # type: ignore[union-attr]
            sync_engine.pool.dispose()
        except Exception:
            pass
