"""Tests for claw_forge.mcp.sdk_server — in-process MCP feature server."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

# ---------------------------------------------------------------------------
# Mock out claude_agent_sdk before importing sdk_server so tests run without
# the optional dependency installed.
# ---------------------------------------------------------------------------

_mock_tool_registry: list[Any] = []


def _fake_tool(name: str, description: str, schema: Any) -> Any:  # type: ignore[return]
    """Decorator factory that registers a mock tool."""

    def decorator(fn: Any) -> Any:
        fn._tool_name = name
        fn._tool_description = description
        _mock_tool_registry.append(fn)
        return fn

    return decorator


_mock_mcp_config = Mock()
_mock_create_sdk = Mock(return_value=_mock_mcp_config)

_sdk_mock = Mock()
_sdk_mock.tool = _fake_tool
_sdk_mock.McpSdkServerConfig = Mock
_sdk_mock.create_sdk_mcp_server = _mock_create_sdk

_sdk_types_mock = Mock()
sys.modules["claude_agent_sdk"] = _sdk_mock
sys.modules["claude_agent_sdk.types"] = _sdk_types_mock

# Force reimport to pick up our custom mock (not a stale Mock from
# another test module that may have imported first).
import importlib  # noqa: E402

import claw_forge.mcp.sdk_server as _sdk_server_mod  # noqa: E402

importlib.reload(_sdk_server_mod)

from claw_forge.mcp.sdk_server import (  # noqa: E402
    _get_engine_for_dir,
    _make_tools,
    create_feature_mcp_server,
)

# Restore the real claude_agent_sdk modules so that test files collected
# afterward (e.g. tests/test_lsp.py, tests/test_skills.py) import
# claw_forge.lsp with the real SdkPluginConfig TypedDict, not a Mock.
for _key in ("claude_agent_sdk", "claude_agent_sdk.types"):
    sys.modules.pop(_key, None)
importlib.import_module("claude_agent_sdk")
importlib.import_module("claude_agent_sdk.types")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


def _tool_name(t: Any) -> str:
    """Get the name of a tool, handling both real SdkMcpTool and mock-decorated functions."""
    if hasattr(t, "name"):
        return str(t.name)
    return str(getattr(t, "_tool_name", ""))


async def _call_tool(t: Any, args: dict[str, Any]) -> Any:
    """Call a tool, handling both real SdkMcpTool (has .handler) and plain async functions."""
    if hasattr(t, "handler"):
        return await t.handler(args)
    return await t(args)


# ---------------------------------------------------------------------------
# _get_engine_for_dir
# ---------------------------------------------------------------------------


class TestGetEngineForDir:
    def test_creates_db_file(self, tmp_path: Path) -> None:
        engine = _get_engine_for_dir(tmp_path)
        db_path = tmp_path / ".claw-forge" / "state.db"
        assert db_path.exists()
        engine.dispose()

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b"
        engine = _get_engine_for_dir(nested)
        assert (nested / ".claw-forge" / "state.db").exists()
        engine.dispose()

    def test_returns_engine(self, tmp_path: Path) -> None:
        from sqlalchemy.engine import Engine

        engine = _get_engine_for_dir(tmp_path)
        assert isinstance(engine, Engine)
        engine.dispose()


# ---------------------------------------------------------------------------
# _make_tools
# ---------------------------------------------------------------------------


class TestMakeTools:
    def test_returns_list_of_tools(self, tmp_path: Path) -> None:
        tools = _make_tools(tmp_path)
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_tool_count(self, tmp_path: Path) -> None:
        tools = _make_tools(tmp_path)
        # Should have at least 10 tools
        assert len(tools) >= 10


# ---------------------------------------------------------------------------
# Individual tool functions
# ---------------------------------------------------------------------------


class TestToolFunctions:
    @pytest.mark.asyncio
    async def test_feature_get_stats_empty(self, tmp_path: Path) -> None:
        tools = _make_tools(tmp_path)
        stats_fn = next(t for t in tools if _tool_name(t) == "feature_get_stats")
        result = await _call_tool(stats_fn, {})
        text = result["content"][0]["text"]
        data = eval(text)  # it's a dict repr
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_feature_create_and_get_by_id(self, tmp_path: Path) -> None:
        tools = _make_tools(tmp_path)
        create_fn = next(t for t in tools if _tool_name(t) == "feature_create")
        get_fn = next(t for t in tools if _tool_name(t) == "feature_get_by_id")

        result = await _call_tool(create_fn, {"name": "My Feature", "category": "core"})
        feature = json.loads(result["content"][0]["text"])
        assert feature["name"] == "My Feature"
        feature_id = feature["id"]

        result2 = await _call_tool(get_fn, {"feature_id": feature_id})
        loaded = json.loads(result2["content"][0]["text"])
        assert loaded is not None
        assert loaded["id"] == feature_id

    @pytest.mark.asyncio
    async def test_feature_get_by_id_missing(self, tmp_path: Path) -> None:
        tools = _make_tools(tmp_path)
        get_fn = next(t for t in tools if _tool_name(t) == "feature_get_by_id")
        result = await _call_tool(get_fn, {"feature_id": "00000000-0000-0000-0000-000000000000"})
        loaded = json.loads(result["content"][0]["text"])
        assert loaded is None

    @pytest.mark.asyncio
    async def test_feature_get_ready_empty(self, tmp_path: Path) -> None:
        tools = _make_tools(tmp_path)
        ready_fn = next(t for t in tools if _tool_name(t) == "feature_get_ready")
        result = await _call_tool(ready_fn, {})
        data = json.loads(result["content"][0]["text"])
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_feature_get_ready_with_features(self, tmp_path: Path) -> None:
        tools = _make_tools(tmp_path)
        create_fn = next(t for t in tools if _tool_name(t) == "feature_create")
        ready_fn = next(t for t in tools if _tool_name(t) == "feature_get_ready")

        await _call_tool(create_fn, {"name": "F1", "category": "core"})
        result = await _call_tool(ready_fn, {})
        data = json.loads(result["content"][0]["text"])
        assert len(data) >= 1

    @pytest.mark.asyncio
    async def test_feature_claim_and_get(self, tmp_path: Path) -> None:
        tools = _make_tools(tmp_path)
        create_fn = next(t for t in tools if _tool_name(t) == "feature_create")
        claim_fn = next(t for t in tools if _tool_name(t) == "feature_claim_and_get")

        await _call_tool(create_fn, {"name": "Claimable", "category": "core"})
        result = await _call_tool(claim_fn, {"agent_id": "agent-1"})
        data = json.loads(result["content"][0]["text"])
        assert data is not None
        assert data["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_feature_claim_and_get_empty(self, tmp_path: Path) -> None:
        tools = _make_tools(tmp_path)
        claim_fn = next(t for t in tools if _tool_name(t) == "feature_claim_and_get")
        result = await _call_tool(claim_fn, {})
        data = json.loads(result["content"][0]["text"])
        assert data is None

    @pytest.mark.asyncio
    async def test_feature_mark_passing(self, tmp_path: Path) -> None:
        tools = _make_tools(tmp_path)
        create_fn = next(t for t in tools if _tool_name(t) == "feature_create")
        pass_fn = next(t for t in tools if _tool_name(t) == "feature_mark_passing")

        res = await _call_tool(create_fn, {"name": "PassMe"})
        fid = json.loads(res["content"][0]["text"])["id"]

        result = await _call_tool(pass_fn, {"feature_id": fid})
        data = json.loads(result["content"][0]["text"])
        assert data["status"] == "passing"

    @pytest.mark.asyncio
    async def test_feature_mark_passing_missing(self, tmp_path: Path) -> None:
        tools = _make_tools(tmp_path)
        pass_fn = next(t for t in tools if _tool_name(t) == "feature_mark_passing")
        result = await _call_tool(pass_fn, {"feature_id": "ghost-id"})
        data = json.loads(result["content"][0]["text"])
        assert data is None

    @pytest.mark.asyncio
    async def test_feature_mark_failing(self, tmp_path: Path) -> None:
        tools = _make_tools(tmp_path)
        create_fn = next(t for t in tools if _tool_name(t) == "feature_create")
        fail_fn = next(t for t in tools if _tool_name(t) == "feature_mark_failing")

        res = await _call_tool(create_fn, {"name": "FailMe"})
        fid = json.loads(res["content"][0]["text"])["id"]

        result = await _call_tool(fail_fn, {"feature_id": fid, "reason": "test failed"})
        data = json.loads(result["content"][0]["text"])
        assert data["status"] == "failing"

    @pytest.mark.asyncio
    async def test_feature_mark_failing_missing(self, tmp_path: Path) -> None:
        tools = _make_tools(tmp_path)
        fail_fn = next(t for t in tools if _tool_name(t) == "feature_mark_failing")
        result = await _call_tool(fail_fn, {"feature_id": "ghost", "reason": "x"})
        data = json.loads(result["content"][0]["text"])
        assert data is None

    @pytest.mark.asyncio
    async def test_feature_create_bulk(self, tmp_path: Path) -> None:
        tools = _make_tools(tmp_path)
        bulk_fn = next(t for t in tools if _tool_name(t) == "feature_create_bulk")

        features_json = json.dumps(
            [
                {"name": "Bulk A", "category": "core"},
                {"name": "Bulk B", "category": "ui"},
            ]
        )
        result = await _call_tool(bulk_fn, {"features_json": features_json})
        data = json.loads(result["content"][0]["text"])
        assert len(data) == 2
        names = {d["name"] for d in data}
        assert names == {"Bulk A", "Bulk B"}

    @pytest.mark.asyncio
    async def test_feature_get_stats_after_create(self, tmp_path: Path) -> None:
        tools = _make_tools(tmp_path)
        create_fn = next(t for t in tools if _tool_name(t) == "feature_create")
        stats_fn = next(t for t in tools if _tool_name(t) == "feature_get_stats")

        await _call_tool(create_fn, {"name": "F1"})
        await _call_tool(create_fn, {"name": "F2"})
        result = await _call_tool(stats_fn, {})
        data = eval(result["content"][0]["text"])
        assert data["total"] >= 2
        assert data["pending"] >= 2

    @pytest.mark.asyncio
    async def test_feature_mark_in_progress(self, tmp_path: Path) -> None:
        tools = _make_tools(tmp_path)
        create_fn = next(t for t in tools if _tool_name(t) == "feature_create")
        ip_fn = next(t for t in tools if _tool_name(t) == "feature_mark_in_progress")

        res = await _call_tool(create_fn, {"name": "InProg"})
        fid = json.loads(res["content"][0]["text"])["id"]

        result = await _call_tool(ip_fn, {"feature_id": fid})
        data = json.loads(result["content"][0]["text"])
        assert data["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_feature_clear_in_progress(self, tmp_path: Path) -> None:
        tools = _make_tools(tmp_path)
        create_fn = next(t for t in tools if _tool_name(t) == "feature_create")
        ip_fn = next(t for t in tools if _tool_name(t) == "feature_mark_in_progress")
        clear_fn = next(t for t in tools if _tool_name(t) == "feature_clear_in_progress")

        res = await _call_tool(create_fn, {"name": "ClearMe"})
        fid = json.loads(res["content"][0]["text"])["id"]
        await _call_tool(ip_fn, {"feature_id": fid})

        result = await _call_tool(clear_fn, {"feature_id": fid})
        data = json.loads(result["content"][0]["text"])
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_feature_add_dependency(self, tmp_path: Path) -> None:
        tools = _make_tools(tmp_path)
        create_fn = next(t for t in tools if _tool_name(t) == "feature_create")
        dep_fn = next(t for t in tools if _tool_name(t) == "feature_add_dependency")

        r1 = await _call_tool(create_fn, {"name": "Base"})
        r2 = await _call_tool(create_fn, {"name": "Dependent"})
        fid1 = json.loads(r1["content"][0]["text"])["id"]
        fid2 = json.loads(r2["content"][0]["text"])["id"]

        result = await _call_tool(dep_fn, {"feature_id": fid2, "depends_on_id": fid1})
        assert "True" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_feature_add_dependency_missing_feature(self, tmp_path: Path) -> None:
        tools = _make_tools(tmp_path)
        dep_fn = next(t for t in tools if _tool_name(t) == "feature_add_dependency")
        result = await _call_tool(dep_fn, {"feature_id": "ghost", "depends_on_id": "also-ghost"})
        assert "False" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# create_feature_mcp_server
# ---------------------------------------------------------------------------


class TestCreateFeatureMcpServer:
    def test_returns_mcp_config(self, tmp_path: Path) -> None:
        config = create_feature_mcp_server(tmp_path)
        assert config is not None
