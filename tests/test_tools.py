"""Tests for claw_forge.agent.tools."""
from __future__ import annotations

import pytest

from claw_forge.agent.tools import (
    BUILTIN_TOOLS,
    CODING_AGENT_TOOLS,
    INITIALIZER_AGENT_TOOLS,
    MAX_TURNS,
    TESTING_AGENT_TOOLS,
    get_max_turns,
    get_tools_for_agent,
)


class TestGetToolsForAgent:
    def test_coding_agent_includes_builtin_tools(self):
        tools = get_tools_for_agent("coding")
        for tool in BUILTIN_TOOLS:
            assert tool in tools

    def test_coding_agent_includes_coding_tools(self):
        tools = get_tools_for_agent("coding")
        for tool in CODING_AGENT_TOOLS:
            assert tool in tools

    def test_testing_agent_includes_builtin_tools(self):
        tools = get_tools_for_agent("testing")
        for tool in BUILTIN_TOOLS:
            assert tool in tools

    def test_testing_agent_includes_testing_tools(self):
        tools = get_tools_for_agent("testing")
        for tool in TESTING_AGENT_TOOLS:
            assert tool in tools

    def test_initializer_agent_includes_initializer_tools(self):
        tools = get_tools_for_agent("initializer")
        for tool in INITIALIZER_AGENT_TOOLS:
            assert tool in tools

    def test_unknown_agent_type_falls_back_to_coding(self):
        tools = get_tools_for_agent("unknown-type")
        for tool in CODING_AGENT_TOOLS:
            assert tool in tools

    def test_testing_agent_does_not_have_claim_tool(self):
        tools = get_tools_for_agent("testing")
        assert "mcp__features__feature_claim_and_get" not in tools

    def test_coding_agent_has_claim_tool(self):
        tools = get_tools_for_agent("coding")
        assert "mcp__features__feature_claim_and_get" in tools

    def test_returns_list(self):
        result = get_tools_for_agent("coding")
        assert isinstance(result, list)

    def test_no_duplicates(self):
        tools = get_tools_for_agent("coding")
        assert len(tools) == len(set(tools))


class TestGetMaxTurns:
    def test_coding_max_turns(self):
        assert get_max_turns("coding") == 300

    def test_testing_max_turns(self):
        assert get_max_turns("testing") == 100

    def test_initializer_max_turns(self):
        assert get_max_turns("initializer") == 300

    def test_unknown_type_defaults_to_300(self):
        assert get_max_turns("unknown") == 300

    def test_returns_int(self):
        assert isinstance(get_max_turns("coding"), int)
