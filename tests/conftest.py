"""Shared test fixtures and configuration.

BUG-10 fix: Ensure aiosqlite async engines created by AgentStateService are
properly disposed during test teardown, preventing 'Event loop is closed'
RuntimeWarning from the aiosqlite connection worker thread.

Two-pronged approach:
1. AgentStateService now exposes dispose() and __aenter__/__aexit__ for
   explicit cleanup (see service.py changes).
2. This conftest patches AgentStateService.__init__ to track instances and
   synchronously disposes their engine pools in teardown.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _auto_dispose_engines() -> None:  # type: ignore[misc]
    """Track async engines and force-close their pools in teardown."""
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

    import contextlib
    for svc in engines:
        with contextlib.suppress(Exception):
            svc._engine.sync_engine.pool.dispose()  # type: ignore[union-attr]
