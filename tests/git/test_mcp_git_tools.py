"""Tests for checkpoint and task_history MCP tools in sdk_server."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock out claude_agent_sdk before importing sdk_server (same pattern as
# tests/test_sdk_server.py).
# ---------------------------------------------------------------------------

_mock_tool_registry: list[Any] = []


def _fake_tool(name: str, description: str, schema: Any) -> Any:  # type: ignore[return]
    def decorator(fn: Any) -> Any:
        fn._tool_name = name
        _mock_tool_registry.append(fn)
        return fn

    return decorator


_mock_mcp_config = MagicMock()
_mock_create_sdk = MagicMock(return_value=_mock_mcp_config)

_sdk_mock = MagicMock()
_sdk_mock.tool = _fake_tool
_sdk_mock.McpSdkServerConfig = MagicMock
_sdk_mock.create_sdk_mcp_server = _mock_create_sdk

_sdk_types_mock = MagicMock()
sys.modules["claude_agent_sdk"] = _sdk_mock
sys.modules["claude_agent_sdk.types"] = _sdk_types_mock

import importlib  # noqa: E402

import claw_forge.mcp.sdk_server as _sdk_server_mod  # noqa: E402

importlib.reload(_sdk_server_mod)

from claw_forge.mcp.sdk_server import _make_tools  # noqa: E402

# Restore the real claude_agent_sdk modules so that test files collected
# afterward (e.g. tests/test_lsp.py) import claw_forge.lsp with the real
# SdkPluginConfig TypedDict instead of a MagicMock.
for _key in ("claude_agent_sdk", "claude_agent_sdk.types"):
    sys.modules.pop(_key, None)
importlib.import_module("claude_agent_sdk")
importlib.import_module("claude_agent_sdk.types")


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _tool_name(t: Any) -> str:
    if hasattr(t, "name"):
        return str(t.name)
    return str(getattr(t, "_tool_name", ""))


async def _call_tool(t: Any, args: dict[str, Any]) -> Any:
    if hasattr(t, "handler"):
        return await t.handler(args)
    return await t(args)


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    (tmp_path / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    return tmp_path


class TestCheckpointTool:
    def test_checkpoint_creates_commit(self, git_repo: Path) -> None:
        tools = _make_tools(git_repo)
        checkpoint_tool = next(t for t in tools if _tool_name(t) == "checkpoint")
        (git_repo / "new_file.py").write_text("x = 1\n")
        result = _run(_call_tool(checkpoint_tool, {
            "message": "feat: add new file",
            "task_id": "task-1",
            "plugin": "coding",
            "phase": "milestone",
            "session_id": "sess-1",
        }))
        content = json.loads(result["content"][0]["text"])
        assert content["commit_hash"]
        assert content["branch"]

    def test_checkpoint_no_changes_returns_null(self, git_repo: Path) -> None:
        tools = _make_tools(git_repo)
        checkpoint_tool = next(t for t in tools if _tool_name(t) == "checkpoint")
        # First call commits any DB files created by _make_tools
        _run(_call_tool(checkpoint_tool, {
            "message": "feat: db init",
            "task_id": "t1",
            "plugin": "coding",
            "phase": "save",
            "session_id": "s1",
        }))
        # Second call with no new changes should return null
        result = _run(_call_tool(checkpoint_tool, {
            "message": "feat: nothing",
            "task_id": "t1",
            "plugin": "coding",
            "phase": "save",
            "session_id": "s1",
        }))
        content = json.loads(result["content"][0]["text"])
        assert content is None


class TestTaskHistoryTool:
    def test_task_history_returns_commits(self, git_repo: Path) -> None:
        tools = _make_tools(git_repo)
        checkpoint_tool = next(t for t in tools if _tool_name(t) == "checkpoint")
        history_tool = next(t for t in tools if _tool_name(t) == "task_history")

        (git_repo / "a.py").write_text("a = 1\n")
        _run(_call_tool(checkpoint_tool, {
            "message": "feat: step 1",
            "task_id": "task-H",
            "plugin": "coding",
            "phase": "milestone",
            "session_id": "s1",
        }))

        result = _run(_call_tool(history_tool, {"task_id": "task-H"}))
        commits = json.loads(result["content"][0]["text"])
        assert len(commits) >= 1
        assert commits[0]["trailers"]["task_id"] == "task-H"
