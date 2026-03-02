"""Smart tool permission callback — replaces hook-based security for interactive sessions.

Unlike hook-based security (which only fires PreToolUse), the can_use_tool
callback gives claw-forge programmatic control over every tool invocation with:
- Input inspection and mutation before execution
- Project-directory sandboxing for write operations
- Dangerous command blocking

Note: can_use_tool requires streaming mode — pass prompt as an AsyncIterable
when using ClaudeSDKClient directly, or use AgentSession which handles this
transparently.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_agent_sdk.types import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

# Commands that are always blocked regardless of context
ALWAYS_BLOCK: frozenset[str] = frozenset({
    "dd",
    "sudo",
    "su",
    "shutdown",
    "reboot",
    "rm -rf /",
})

# File-write tools that should be sandboxed to project_dir
WRITE_TOOLS: frozenset[str] = frozenset({"Write", "Edit", "MultiEdit"})


async def smart_can_use_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    context: ToolPermissionContext,
    project_dir: Path | None = None,
) -> PermissionResultAllow | PermissionResultDeny:
    """Programmatic permission control for Claude tool calls.

    Evaluation order:
    1. Bash tool: block any command matching ALWAYS_BLOCK patterns.
    2. Write/Edit/MultiEdit tools: block writes outside project_dir (if given).
    3. Everything else: allow.

    Args:
        tool_name: Name of the tool being invoked (e.g. "Bash", "Write").
        tool_input: The tool's input dict (e.g. {"command": "sudo rm -rf /"}).
        context: SDK ToolPermissionContext (may contain session metadata).
        project_dir: If provided, write operations are sandboxed to this directory.

    Returns:
        PermissionResultAllow if the tool call should proceed.
        PermissionResultDeny with a reason if it should be blocked.
    """
    # ── Bash: block dangerous commands ───────────────────────────────────────
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        for blocked in ALWAYS_BLOCK:
            if blocked in cmd:
                return PermissionResultDeny(
                    behavior="deny",
                    message=f"Blocked: {blocked}",
                )

    # ── Write tools: sandbox to project_dir ──────────────────────────────────
    if tool_name in WRITE_TOOLS and project_dir is not None:
        file_path = tool_input.get("file_path", "")
        if file_path:
            try:
                Path(file_path).resolve().relative_to(project_dir.resolve())
            except ValueError:
                return PermissionResultDeny(
                    behavior="deny",
                    message=f"Write outside project dir: {file_path}",
                )

    return PermissionResultAllow(behavior="allow")


def make_can_use_tool(
    project_dir: Path | None = None,
    extra_blocked: set[str] | None = None,
) -> Any:
    """Create a can_use_tool callback bound to a specific project directory.

    Args:
        project_dir: Root directory to sandbox writes to.
        extra_blocked: Additional Bash command patterns to block.

    Returns:
        Async callable compatible with ClaudeAgentOptions.can_use_tool.

    Example::

        from claw_forge.agent.permissions import make_can_use_tool
        from claude_agent_sdk import ClaudeAgentOptions

        options = ClaudeAgentOptions(
            can_use_tool=make_can_use_tool(project_dir=Path("/my/project")),
            ...
        )
    """
    blocked = ALWAYS_BLOCK | (extra_blocked or set())

    async def _can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        # Bash: check expanded block list
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            for pattern in blocked:
                if pattern in cmd:
                    return PermissionResultDeny(
                        behavior="deny",
                        message=f"Blocked: {pattern}",
                    )

        # Write tools: sandbox to project_dir
        if tool_name in WRITE_TOOLS and project_dir is not None:
            file_path = tool_input.get("file_path", "")
            if file_path:
                try:
                    Path(file_path).resolve().relative_to(project_dir.resolve())
                except ValueError:
                    return PermissionResultDeny(
                        behavior="deny",
                        message=f"Write outside project dir: {file_path}",
                    )

        return PermissionResultAllow(behavior="allow")

    return _can_use_tool
