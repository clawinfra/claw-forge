"""Agent-type-specific tool lists — mirrors AutoForge's per-agent tool scoping."""
from __future__ import annotations

# Built-in Claude Code tools available to all agents
BUILTIN_TOOLS = [
    "Read", "Write", "Edit", "Glob", "Grep", "Bash",
    "WebFetch", "WebSearch",  # Agents can look up live docs
]

# Feature MCP tools per agent type
CODING_AGENT_TOOLS = [
    "mcp__features__feature_get_stats",
    "mcp__features__feature_get_by_id",
    "mcp__features__feature_get_summary",
    "mcp__features__feature_get_ready",
    "mcp__features__feature_get_blocked",
    "mcp__features__feature_get_graph",
    "mcp__features__feature_claim_and_get",
    "mcp__features__feature_mark_in_progress",
    "mcp__features__feature_mark_passing",
    "mcp__features__feature_mark_failing",
    "mcp__features__feature_skip",
    "mcp__features__feature_clear_in_progress",
]

TESTING_AGENT_TOOLS = [
    "mcp__features__feature_get_stats",
    "mcp__features__feature_get_by_id",
    "mcp__features__feature_get_summary",
    "mcp__features__feature_get_ready",
    "mcp__features__feature_get_blocked",
    "mcp__features__feature_get_graph",
    "mcp__features__feature_mark_passing",
    "mcp__features__feature_mark_failing",
]

INITIALIZER_AGENT_TOOLS = [
    "mcp__features__feature_get_stats",
    "mcp__features__feature_get_ready",
    "mcp__features__feature_get_blocked",
    "mcp__features__feature_get_graph",
    "mcp__features__feature_create_bulk",
    "mcp__features__feature_create",
    "mcp__features__feature_add_dependency",
    "mcp__features__feature_set_dependencies",
]

# Max turns per agent type
MAX_TURNS = {
    "coding": 300,
    "testing": 100,
    "initializer": 300,
}


def get_tools_for_agent(agent_type: str) -> list[str]:
    """Get the full tool list for an agent type (builtin + feature MCP)."""
    feature_tools = {
        "coding": CODING_AGENT_TOOLS,
        "testing": TESTING_AGENT_TOOLS,
        "initializer": INITIALIZER_AGENT_TOOLS,
    }.get(agent_type, CODING_AGENT_TOOLS)
    return [*BUILTIN_TOOLS, *feature_tools]


def get_max_turns(agent_type: str) -> int:
    """Get the max turns for an agent type."""
    return MAX_TURNS.get(agent_type, 300)
