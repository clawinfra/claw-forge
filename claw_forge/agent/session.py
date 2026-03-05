"""ClaudeSDKClient session manager with mid-session intervention support.

Provides a stateful bidirectional agent session on top of ClaudeSDKClient.
Key capabilities vs bare query():
- Mid-session follow-ups without restarting
- Dynamic model switching (e.g. Sonnet → Opus for complex sub-tasks)
- Permission escalation mid-session
- Interrupt support
- File checkpointing + rewind
- MCP health checks
- In-process server-info introspection
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import claude_agent_sdk
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient


class AgentSession:
    """Stateful bidirectional agent session.

    Supports:
    - Mid-session follow-ups (send new prompts in same session)
    - Model switching mid-session (e.g. Sonnet → Opus for hard parts)
    - Permission escalation (switch to bypassPermissions on-the-fly)
    - Interrupt (stop current generation)
    - File checkpointing + rewind (restore files to earlier state)
    - MCP health checks
    - Server info introspection

    Usage::

        options = ClaudeAgentOptions(model="claude-sonnet-4-5", ...)
        async with AgentSession(options) as session:
            async for msg in session.run("Implement feature X"):
                print(msg)
            # Follow up in same session — no cold start
            async for msg in session.follow_up("Now add tests"):
                print(msg)
    """

    def __init__(self, options: ClaudeAgentOptions) -> None:
        self.options = options
        self._client: ClaudeSDKClient | None = None
        # Stores user-message UUIDs for rewind support
        self._checkpoints: list[str] = []

    async def __aenter__(self) -> AgentSession:
        self._client = ClaudeSDKClient(self.options)
        await self._client.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.disconnect()
            self._client = None

    # ── Core messaging ────────────────────────────────────────────────────────

    async def run(self, prompt: str) -> AsyncIterator[claude_agent_sdk.Message]:
        """Send *prompt* and stream the response.

        Tracks user-message UUIDs as checkpoints for potential rewind.
        """
        assert self._client is not None, "AgentSession not connected — use async with"
        await self._client.query(prompt)
        async for msg in self._client.receive_response():
            if msg.__class__.__name__ == "UserMessage" and msg.uuid:  # type: ignore[union-attr]
                self._checkpoints.append(msg.uuid)  # type: ignore[union-attr]
            yield msg

    async def follow_up(self, message: str) -> AsyncIterator[claude_agent_sdk.Message]:
        """Send a follow-up message in the same session without re-initialising.

        This is the key advantage over bare query() — zero cold-start cost for
        multi-turn workflows.
        """
        assert self._client is not None, "AgentSession not connected — use async with"
        await self._client.query(message)
        async for msg in self._client.receive_response():
            yield msg

    # ── Control flow ──────────────────────────────────────────────────────────

    async def interrupt(self) -> None:
        """Interrupt the current generation immediately."""
        assert self._client is not None
        await self._client.interrupt()

    async def escalate_permissions(self) -> None:
        """Switch to bypassPermissions mode for trusted operations.

        Useful when the agent encounters a permission prompt mid-task that
        would otherwise require user interaction.
        """
        assert self._client is not None
        await self._client.set_permission_mode("bypassPermissions")

    async def switch_model(self, model: str) -> None:
        """Dynamically switch the active model mid-session.

        Example: start with Sonnet for fast coding, switch to Opus for
        a particularly complex architectural sub-task.
        """
        assert self._client is not None
        await self._client.set_model(model)

    # ── Checkpoint / rewind ───────────────────────────────────────────────────

    async def rewind(self, steps_back: int = 1) -> None:
        """Rewind files to N checkpoints ago.

        Each user message sent via run() is recorded as a checkpoint. Calling
        rewind(1) restores files to the state they were in before the last
        message was processed.

        Args:
            steps_back: How many checkpoints to rewind. Defaults to 1 (last
                message). Silently no-ops if fewer checkpoints exist.
        """
        assert self._client is not None
        if len(self._checkpoints) >= steps_back:
            checkpoint = self._checkpoints[-steps_back]
            await self._client.rewind_files(checkpoint)

    # ── Health / introspection ────────────────────────────────────────────────

    async def mcp_health(self) -> dict[str, Any]:
        """Return the current MCP server health status dict."""
        assert self._client is not None
        # SDK ≥0.1.46 returns McpStatusResponse (TypedDict); dict() normalises both
        return dict(await self._client.get_mcp_status())

    async def get_server_info(self) -> dict[str, Any] | None:
        """Return server info from the connected Claude CLI instance."""
        assert self._client is not None
        return await self._client.get_server_info()
