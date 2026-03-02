"""Agent runner — wraps claude-agent-sdk query() for claw-forge execution."""
from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator

import claude_agent_sdk
from claude_agent_sdk import McpServerConfig, PermissionMode, query

from claw_forge.pool.providers.base import ProviderConfig


async def run_agent(
    prompt: str,
    *,
    model: str = "claude-sonnet-4-5",
    cwd: Path | None = None,
    allowed_tools: list[str] | None = None,
    mcp_servers: dict[str, McpServerConfig] | None = None,
    max_turns: int = 50,
    permission_mode: PermissionMode = "default",
    system_prompt: str | None = None,
    provider_config: ProviderConfig | None = None,
) -> AsyncIterator[claude_agent_sdk.Message]:
    """
    Run a Claude agent via claude-agent-sdk query().

    Yields Message objects (AssistantMessage, ResultMessage, etc.)
    Provider config is used to set API key / OAuth token / base URL overrides
    via the env dict passed to ClaudeAgentOptions.
    """
    env: dict[str, str] = {}

    # Apply provider config overrides via environment variables
    if provider_config:
        if provider_config.api_key:
            env["ANTHROPIC_API_KEY"] = provider_config.api_key
        if provider_config.base_url:
            env["ANTHROPIC_BASE_URL"] = provider_config.base_url
        if getattr(provider_config, "oauth_token", None):
            env["CLAUDE_OAUTH_TOKEN"] = provider_config.oauth_token  # type: ignore[assignment]

    options = claude_agent_sdk.ClaudeAgentOptions(
        model=model,
        max_turns=max_turns,
        permission_mode=permission_mode,
        cwd=str(cwd) if cwd else None,
        allowed_tools=allowed_tools or [],
        mcp_servers=mcp_servers or {},
        system_prompt=system_prompt,
        env=env,
    )

    async for message in query(prompt=prompt, options=options):
        yield message


async def collect_result(
    prompt: str,
    **kwargs: Any,
) -> str:
    """Run agent and return the final text result."""
    result_text = ""
    async for message in run_agent(prompt, **kwargs):
        if isinstance(message, claude_agent_sdk.ResultMessage):
            result_text = message.result or ""
    return result_text
