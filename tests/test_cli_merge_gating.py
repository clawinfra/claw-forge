"""Test that the dispatcher gates dependents on merge success.

These tests exercise the merge_to_main lifecycle directly via the helper
that wraps PATCH calls — exhaustive end-to-end runs are out of scope
because they require provider keys.  We verify the call sequence.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from claw_forge.cli import _set_merged_to_main_after_merge


@pytest.mark.asyncio
async def test_set_merged_to_main_after_merge_calls_patch_true_on_success() -> None:
    http = AsyncMock()
    merge_result = {"merged": True, "commit_hash": "abc1234"}
    base = "http://localhost:8420"
    await _set_merged_to_main_after_merge(http, base, "task-1", merge_result)
    http.patch.assert_called_once()
    args, kwargs = http.patch.call_args
    assert args[0] == f"{base}/tasks/task-1"
    assert kwargs["json"] == {"merged_to_main": True}


@pytest.mark.asyncio
async def test_set_merged_to_main_after_merge_no_patch_on_failure() -> None:
    http = AsyncMock()
    merge_result = {"merged": False, "error": "conflict"}
    await _set_merged_to_main_after_merge(http, "http://x", "task-1", merge_result)
    http.patch.assert_not_called()


@pytest.mark.asyncio
async def test_set_merged_to_main_after_merge_no_patch_when_none() -> None:
    """When merge isn't attempted (manual strategy / git disabled), no PATCH."""
    http = AsyncMock()
    await _set_merged_to_main_after_merge(http, "http://x", "task-1", None)
    http.patch.assert_not_called()
