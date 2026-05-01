"""Test the dispatcher's file-claim logic via the helper functions."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from claw_forge.cli import _try_claim_files


@pytest.mark.asyncio
async def test_try_claim_files_returns_true_on_200() -> None:
    http = MagicMock()
    response = MagicMock(status_code=200)
    response.json.return_value = {"claimed": True, "conflicts": []}
    http.post = AsyncMock(return_value=response)
    ok, conflicts = await _try_claim_files(
        http, "http://localhost:8420", "sess-1", "task-1", ["a.py"],
    )
    assert ok is True
    assert conflicts == []
    http.post.assert_called_once()


@pytest.mark.asyncio
async def test_try_claim_files_returns_false_on_409() -> None:
    http = MagicMock()
    response = MagicMock(status_code=409)
    response.json.return_value = {"claimed": False, "conflicts": ["a.py"]}
    http.post = AsyncMock(return_value=response)
    ok, conflicts = await _try_claim_files(
        http, "http://localhost:8420", "sess-1", "task-1", ["a.py"],
    )
    assert ok is False
    assert conflicts == ["a.py"]


@pytest.mark.asyncio
async def test_try_claim_files_short_circuits_when_empty_list() -> None:
    """No POST is issued when the task declares no files."""
    http = MagicMock()
    http.post = AsyncMock()
    ok, conflicts = await _try_claim_files(
        http, "http://x", "sess-1", "task-1", [],
    )
    assert ok is True
    assert conflicts == []
    http.post.assert_not_called()
