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


def test_task_dict_to_node_reads_merged_to_main() -> None:
    """The DB→TaskNode mapper preserves merged_to_main."""
    from claw_forge.cli import _task_dict_to_node

    payload = {
        "id": "t1", "plugin_name": "coding", "priority": 0,
        "depends_on": [], "status": "completed",
        "merged_to_main": False, "description": "X", "category": "c",
        "steps": [],
    }
    node = _task_dict_to_node(payload)
    assert node.merged_to_main is False
    # Backward-compat: missing key defaults to True.
    payload2 = dict(payload)
    payload2.pop("merged_to_main")
    node2 = _task_dict_to_node(payload2)
    assert node2.merged_to_main is True
