"""Claude Code hooks — PreToolUse (security) and PreCompact (state flush)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

HookHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]


@dataclass
class HookResult:
    """Result of a hook execution."""

    allow: bool = True
    modified_input: dict[str, Any] | None = None
    reason: str | None = None


@dataclass
class SecurityPolicy:
    """Security policy for PreToolUse hook."""

    blocked_commands: list[str] = field(default_factory=lambda: [
        "rm -rf /",
        "rm -rf ~",
        ":(){ :|:& };:",
        "mkfs",
        "dd if=/dev/zero",
    ])
    blocked_paths: list[str] = field(default_factory=lambda: [
        "/etc/passwd",
        "/etc/shadow",
        "~/.ssh/id_",
    ])
    allowed_tools: list[str] = field(default_factory=lambda: [
        "read_file",
        "write_file",
        "edit_file",
        "execute_command",
        "search_files",
        "list_directory",
    ])
    max_command_length: int = 10_000
    require_tool_allowlist: bool = False


class PreToolUseHook:
    """Security gate that runs before every tool invocation.

    Checks for dangerous commands, blocked paths, and policy violations.
    """

    def __init__(self, policy: SecurityPolicy | None = None) -> None:
        self.policy = policy or SecurityPolicy()
        self._custom_handlers: list[HookHandler] = []

    def add_handler(self, handler: HookHandler) -> None:
        self._custom_handlers.append(handler)

    async def check(self, tool_name: str, tool_input: dict[str, Any]) -> HookResult:
        # Tool allowlist
        if self.policy.require_tool_allowlist and tool_name not in self.policy.allowed_tools:
            return HookResult(allow=False, reason=f"Tool '{tool_name}' not in allowlist")

        # Command safety
        if tool_name == "execute_command":
            cmd = tool_input.get("command", "")
            if len(cmd) > self.policy.max_command_length:
                return HookResult(allow=False, reason="Command too long")
            for blocked in self.policy.blocked_commands:
                if blocked in cmd:
                    return HookResult(allow=False, reason=f"Blocked command pattern: {blocked}")

        # Path safety
        for key in ("path", "file_path", "target"):
            path = tool_input.get(key, "")
            if path:
                for blocked in self.policy.blocked_paths:
                    if blocked in path:
                        return HookResult(allow=False, reason=f"Blocked path: {blocked}")

        # Custom handlers
        for handler in self._custom_handlers:
            result = await handler({"tool": tool_name, "input": tool_input})
            if result and not result.get("allow", True):
                return HookResult(allow=False, reason=result.get("reason", "Blocked by custom hook"))  # noqa: E501

        return HookResult(allow=True)


class PreCompactHook:
    """State flush hook that runs before context compaction.

    Ensures critical state is persisted before the context window
    is compacted, preventing loss of important decisions and progress.
    """

    def __init__(self) -> None:
        self._flush_handlers: list[Callable[[], Awaitable[None]]] = []

    def add_flush_handler(self, handler: Callable[[], Awaitable[None]]) -> None:
        self._flush_handlers.append(handler)

    async def flush(self, context: dict[str, Any]) -> dict[str, Any]:
        """Flush all registered state before compaction."""
        flushed: list[str] = []

        for handler in self._flush_handlers:
            try:
                await handler()
                flushed.append(handler.__name__ if hasattr(handler, "__name__") else "anonymous")
            except Exception:
                logger.exception("Flush handler failed")

        logger.info("PreCompact: flushed %d handlers: %s", len(flushed), flushed)
        return {"flushed": flushed, "context_keys": list(context.keys())}
