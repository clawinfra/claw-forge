"""SDK hooks for claw-forge agents."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from claude_agent_sdk.types import HookContext, HookInput, HookMatcher, SyncHookJSONOutput

from .security import bash_security_hook

# ── Pre-compact hook ──────────────────────────────────────────────────────────


async def pre_compact_hook(
    input_data: HookInput,
    tool_use_id: str | None,
    context: HookContext,
) -> SyncHookJSONOutput:
    """Preserve critical workflow state during context compaction."""
    trigger = input_data.get("trigger", "auto") if isinstance(input_data, dict) else "auto"
    print(f"[Context] {'Auto' if trigger == 'auto' else 'Manual'}-compaction triggered")

    compaction_guidance = "\n".join([
        "## PRESERVE (critical workflow state)",
        "- Current feature ID, name, and status (pending/in_progress/passing/failing)",
        "- All files created or modified during this session with their paths",
        "- Last test/lint/type-check results: command, pass/fail, key errors",
        "- Current step in workflow (implementing, testing, fixing lint errors)",
        "- Dependency information (which features block this one)",
        "- Git operations performed (commits, branches)",
        "- MCP tool call results (feature_claim_and_get, feature_mark_passing, etc.)",
        "- Key architectural decisions made this session",
        "",
        "## DISCARD (verbose content safe to drop)",
        "- Full screenshot base64 data",
        "- Long grep/find/glob output listings (summarize to: searched X, found Y files)",
        "- Repeated file reads of the same file",
        "- Full file contents from Read tool",
        "- Verbose npm/pip install output",
        "- Full lint output when passing",
        "- Browser console message dumps",
        "- Redundant [Done] markers",
    ])

    return SyncHookJSONOutput(
        hookSpecificOutput={  # type: ignore[typeddict-item]
            "hookEventName": "PreCompact",
            "customInstructions": compaction_guidance,
        }
    )


# ── PostToolUse hook ──────────────────────────────────────────────────────────


async def post_tool_hook(
    input_data: HookInput,
    tool_use_id: str | None,
    context: HookContext,
) -> SyncHookJSONOutput:
    """Inject additional context to Claude after every tool execution.

    Can be extended via closure to inject token-budget remaining, feature
    progress, or other metrics alongside the tool result.
    """
    return SyncHookJSONOutput(
        hookSpecificOutput={  # type: ignore[typeddict-item]
            "hookEventName": "PostToolUse",
            "additionalContext": "",  # populated by caller via closure/subclass
        }
    )


# ── PostToolUseFailure hook ───────────────────────────────────────────────────


async def post_tool_failure_hook(
    input_data: HookInput,
    tool_use_id: str | None,
    context: HookContext,
) -> SyncHookJSONOutput:
    """Auto-log tool failures and inject recovery guidance into the context."""
    data = input_data if isinstance(input_data, dict) else {}
    error = data.get("error", "")
    tool_name = data.get("tool_name", "")
    print(f"[Tool failure] {tool_name}: {error[:200]}")
    return SyncHookJSONOutput(
        hookSpecificOutput={  # type: ignore[typeddict-item]
            "hookEventName": "PostToolUseFailure",
            "additionalContext": (
                f"The {tool_name} tool failed. Consider alternative approaches."
            ),
        }
    )


# ── UserPromptSubmit hook factory ─────────────────────────────────────────────


def make_prompt_enrichment_hook(
    context_fn: Callable[[], str] | str,
) -> Callable[..., Any]:
    """Factory for UserPromptSubmit hooks that auto-inject project context.

    Args:
        context_fn: Either a zero-argument callable that returns the context
            string (called fresh on each hook invocation), or a static string.

    Returns:
        Async hook function compatible with HookMatcher hooks list.

    Example::

        def get_project_context():
            stats = get_current_stats()
            return f"Active features: {stats['in_progress']}, Passing: {stats['passing']}"

        hooks = {
            "UserPromptSubmit": [
                HookMatcher(hooks=[make_prompt_enrichment_hook(get_project_context)]),
            ],
        }
    """
    async def hook(
        input_data: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> SyncHookJSONOutput:
        extra = context_fn() if callable(context_fn) else str(context_fn)
        return SyncHookJSONOutput(
            hookSpecificOutput={  # type: ignore[typeddict-item]
                "hookEventName": "UserPromptSubmit",
                "additionalContext": extra,
            }
        )
    return hook


# ── Stop hook factory ─────────────────────────────────────────────────────────


def make_stop_hook(
    should_continue_fn: Callable[[], bool],
) -> Callable[..., Any]:
    """Factory for Stop hooks that prevent premature agent termination.

    When the agent signals it wants to stop, this hook checks whether there is
    remaining work and, if so, injects a continuation instruction.

    Args:
        should_continue_fn: Zero-argument callable returning True if the agent
            should continue working (e.g. "are there pending features?").

    Returns:
        Async hook function compatible with HookMatcher hooks list.

    Example::

        def has_pending_features():
            return get_stats()["pending"] > 0

        hooks = {
            "Stop": [HookMatcher(hooks=[make_stop_hook(has_pending_features)])],
        }
    """
    async def hook(
        input_data: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> SyncHookJSONOutput:
        data = input_data if isinstance(input_data, dict) else {}
        if data.get("stop_hook_active") and should_continue_fn():
            return SyncHookJSONOutput(
                continue_=True,
                hookSpecificOutput={  # type: ignore[typeddict-item]
                    "hookEventName": "Stop",
                    "additionalContext": "Continue working — there are remaining tasks.",
                },
            )
        return SyncHookJSONOutput(
            continue_=False,
            hookSpecificOutput={  # type: ignore[typeddict-item]
                "hookEventName": "Stop",
            },
        )
    return hook


# ── Notification hook factory ─────────────────────────────────────────────────


def make_notification_hook(
    broadcast_fn: Callable[[dict[str, Any]], Any] | None = None,
) -> Callable[..., Any]:
    """Factory for Notification hooks that bridge agent alerts to WebSocket/Kanban.

    Args:
        broadcast_fn: Optional async callable that receives a notification dict
            ``{"type": "agent_notification", "title": ..., "message": ...}``.
            If provided, it's scheduled as a background asyncio task.

    Returns:
        Async hook function compatible with HookMatcher hooks list.

    Example::

        async def ws_broadcast(payload):
            await websocket_manager.broadcast(payload)

        hooks = {
            "Notification": [HookMatcher(hooks=[make_notification_hook(ws_broadcast)])],
        }
    """
    async def hook(
        input_data: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> SyncHookJSONOutput:
        data = input_data if isinstance(input_data, dict) else {}
        msg = data.get("message", "")
        title = data.get("title", "Agent")
        print(f"[{title}] {msg}")
        if broadcast_fn:
            asyncio.create_task(
                broadcast_fn(
                    {"type": "agent_notification", "title": title, "message": msg}
                )
            )
        return SyncHookJSONOutput(
            hookSpecificOutput={  # type: ignore[typeddict-item]
                "hookEventName": "Notification",
                "additionalContext": "",
            }
        )
    return hook


# ── SubagentStart hook ────────────────────────────────────────────────────────


async def subagent_start_hook(
    input_data: HookInput,
    tool_use_id: str | None,
    context: HookContext,
) -> SyncHookJSONOutput:
    """Log and inject standards into each sub-agent as it starts.

    Automatically injects claw-forge coding standards into the sub-agent's
    context so that every spawned agent starts with the same baseline.
    """
    data = input_data if isinstance(input_data, dict) else {}
    agent_id = data.get("agent_id", "")
    agent_type = data.get("agent_type", "")
    print(f"[SubAgent] Starting: {agent_type} ({agent_id})")
    return SyncHookJSONOutput(
        hookSpecificOutput={  # type: ignore[typeddict-item]
            "hookEventName": "SubagentStart",
            "additionalContext": (
                f"You are a {agent_type} sub-agent. Follow claw-forge coding standards."
            ),
        }
    )


# ── SubagentStop hook ─────────────────────────────────────────────────────────


async def subagent_stop_hook(
    input_data: HookInput,
    tool_use_id: str | None,
    context: HookContext,
) -> SyncHookJSONOutput:
    """Log when a sub-agent finishes."""
    data = input_data if isinstance(input_data, dict) else {}
    agent_id = data.get("agent_id", "")
    agent_type = data.get("agent_type", "")
    print(f"[SubAgent] Stopped: {agent_type} ({agent_id})")
    return SyncHookJSONOutput(
        hookSpecificOutput={  # type: ignore[typeddict-item]
            "hookEventName": "SubagentStop",
            "additionalContext": "",
        }
    )


# ── Default hooks factory ─────────────────────────────────────────────────────


def get_default_hooks() -> dict:
    """Return the default hooks dict for ClaudeAgentOptions.

    Includes:
    - PreToolUse/Bash: security allowlist enforcement
    - PreCompact: workflow-state preservation guidance
    - PostToolUse: context injection after tool calls
    - PostToolUseFailure: failure logging + recovery hints
    - SubagentStart: standards injection for sub-agents
    - SubagentStop: sub-agent lifecycle logging
    """
    return {
        "PreToolUse": [
            HookMatcher(matcher="Bash", hooks=[bash_security_hook]),
        ],
        "PreCompact": [
            HookMatcher(hooks=[pre_compact_hook]),
        ],
        "PostToolUse": [
            HookMatcher(hooks=[post_tool_hook]),
        ],
        "PostToolUseFailure": [
            HookMatcher(hooks=[post_tool_failure_hook]),
        ],
        "SubagentStart": [
            HookMatcher(hooks=[subagent_start_hook]),
        ],
        "SubagentStop": [
            HookMatcher(hooks=[subagent_stop_hook]),
        ],
    }
