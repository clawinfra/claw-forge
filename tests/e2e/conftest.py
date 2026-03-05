"""E2E test fixtures.

Patches _ensure_state_service so that e2e CLI tests don't need an actual
free port. Tests in this directory test CLI behaviour (run, ui, plan, …)
rather than state-service startup logic.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _patch_ensure_state_service() -> None:  # type: ignore[misc]
    """Prevent _ensure_state_service from touching real ports in e2e tests."""
    with patch("claw_forge.cli._ensure_state_service", return_value=8420):
        yield  # type: ignore[misc]
