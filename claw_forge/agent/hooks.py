"""SDK hooks for claw-forge agents."""
from __future__ import annotations

from claude_agent_sdk.types import HookContext, HookInput, HookMatcher, SyncHookJSONOutput

from .security import bash_security_hook


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


def get_default_hooks() -> dict:
    """Return the default hooks dict for ClaudeAgentOptions."""
    return {
        "PreToolUse": [
            HookMatcher(matcher="Bash", hooks=[bash_security_hook]),
        ],
        "PreCompact": [
            HookMatcher(hooks=[pre_compact_hook]),
        ],
    }
