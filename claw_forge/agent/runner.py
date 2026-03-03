"""Agent runner — wraps claude-agent-sdk query() for claw-forge execution."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal, cast

import claude_agent_sdk
from claude_agent_sdk import McpServerConfig, PermissionMode, query
from claude_agent_sdk.types import HookEvent, HookMatcher, SdkPluginConfig, ThinkingConfig

from claw_forge.pool.providers.base import ProviderConfig

from .hooks import get_default_hooks
from .tools import get_max_turns, get_tools_for_agent


async def run_agent(
    prompt: str,
    *,
    model: str = "claude-sonnet-4-5",
    cwd: Path | None = None,
    allowed_tools: list[str] | None = None,
    mcp_servers: dict[str, McpServerConfig] | None = None,
    max_turns: int | None = None,
    permission_mode: PermissionMode = "default",
    system_prompt: str | None = None,
    provider_config: ProviderConfig | None = None,
    agent_type: str = "coding",
    project_dir: Path | None = None,
    hooks: dict[HookEvent, list[HookMatcher]] | None = None,
    # ── New SDK options ──────────────────────────────────────────────────
    thinking: ThinkingConfig | None = None,
    output_format: dict[str, Any] | None = None,
    fallback_model: str | None = None,
    max_budget_usd: float | None = None,
    effort: Literal["low", "medium", "high", "max"] | None = None,
    include_partial_messages: bool = False,
    use_sdk_mcp: bool = True,
    lsp_plugins: list[SdkPluginConfig] | None = None,
    auto_detect_lsp: bool = True,
    auto_inject_skills: bool = True,
) -> AsyncIterator[claude_agent_sdk.Message]:
    """
    Run a Claude agent via claude-agent-sdk query().

    Yields Message objects (AssistantMessage, ResultMessage, etc.)

    Provider config is used to set API key / OAuth token / base URL overrides
    via the env dict passed to ClaudeAgentOptions.

    Args:
        prompt: The prompt to send to the agent.
        model: Model name to use.
        cwd: Working directory for the agent.
        allowed_tools: Explicit tool list. If None, uses agent_type to determine tools.
        mcp_servers: MCP server configs. Features MCP is auto-injected if project_dir given.
        max_turns: Max conversation turns. If None, uses agent_type default.
        permission_mode: Claude permission mode.
        system_prompt: Optional system prompt override.
        provider_config: Provider config for API key / OAuth / base URL.
        agent_type: Agent type ("coding", "testing", "initializer"). Controls tool list
            and max_turns defaults.
        project_dir: If provided, auto-injects the features MCP server config.
        hooks: SDK hooks dict. If None, uses default hooks (bash security + pre-compact).
        thinking: ThinkingConfig preset (enabled/adaptive/disabled). Controls extended
            thinking behaviour for the agent.
        output_format: JSON Schema output format dict. When set, the agent's final
            response will conform to the given schema. Use with collect_structured_result().
        fallback_model: Fallback model to use if primary model is unavailable.
        max_budget_usd: Maximum USD budget for the entire agent session.
        effort: Effort level hint — "low", "medium", "high", or "max".
        include_partial_messages: If True, yield StreamEvent messages for real-time
            token-by-token output.
        use_sdk_mcp: If True and project_dir is given, use in-process SDK MCP server
            (zero cold-start) instead of the subprocess MCP. Defaults to True.
        lsp_plugins: Explicit list of LSP SdkPluginConfig entries. When provided,
            used as-is (auto-detection is skipped).
        auto_detect_lsp: If True and lsp_plugins is not provided, scan cwd for source
            files and auto-inject matching LSP skill plugins. Defaults to True.
        auto_inject_skills: If True, automatically inject non-LSP skills based on
            agent_type and keywords found in the prompt. Defaults to True.
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

    # Resolve tool list from agent_type if not explicitly provided
    if allowed_tools is None:
        allowed_tools = get_tools_for_agent(agent_type)

    # Resolve max_turns from agent_type if not explicitly provided
    if max_turns is None:
        max_turns = get_max_turns(agent_type)

    # Auto-inject features MCP server when project_dir is given
    resolved_mcp: dict[str, McpServerConfig] = dict(mcp_servers or {})
    if project_dir is not None and "features" not in resolved_mcp:
        if use_sdk_mcp:
            # In-process SDK MCP — zero subprocess overhead
            from claw_forge.mcp.sdk_server import create_feature_mcp_server
            resolved_mcp["features"] = create_feature_mcp_server(project_dir)
        else:
            # Legacy subprocess MCP
            from claw_forge.mcp.feature_mcp import mcp_server_config
            features_config = mcp_server_config(project_dir)
            resolved_mcp.update(features_config)

    # Use default hooks if not provided
    if hooks is None:
        hooks = get_default_hooks()  # type: ignore[assignment]  # compatible at runtime  # type: ignore[assignment]

    # Resolve LSP plugins
    resolved_lsp_plugins: list[SdkPluginConfig]
    if lsp_plugins is not None:
        resolved_lsp_plugins = lsp_plugins
    elif auto_detect_lsp and cwd is not None:
        from claw_forge.lsp import detect_lsp_plugins
        resolved_lsp_plugins = detect_lsp_plugins(cwd)
    else:
        resolved_lsp_plugins = []

    # Merge in agent-type + keyword-based skill plugins when requested
    if auto_inject_skills:
        from claw_forge.lsp import skills_for_agent
        task_desc = prompt if isinstance(prompt, str) else ""
        skill_plugins = skills_for_agent(agent_type, task_desc)
        # Deduplicate by path — lsp_plugins take precedence (listed first)
        existing_paths: set[str] = {p["path"] for p in resolved_lsp_plugins}
        for sp in skill_plugins:
            if sp["path"] not in existing_paths:
                existing_paths.add(sp["path"])
                resolved_lsp_plugins.append(sp)

    options = claude_agent_sdk.ClaudeAgentOptions(
        model=model,
        max_turns=max_turns,
        permission_mode=permission_mode,
        cwd=str(cwd) if cwd else None,
        allowed_tools=allowed_tools,
        mcp_servers=resolved_mcp,
        system_prompt=system_prompt,
        env=env,
        setting_sources=["project"],          # enables CLAUDE.md, skills, commands per project
        max_buffer_size=10 * 1024 * 1024,     # 10MB for screenshots
        betas=["context-1m-2025-08-07"],      # 1M token context window
        hooks=hooks,
        # New SDK options
        thinking=thinking,
        output_format=output_format,
        fallback_model=fallback_model,
        max_budget_usd=max_budget_usd,
        effort=effort,
        include_partial_messages=include_partial_messages,
        plugins=resolved_lsp_plugins,
    )

    async for message in query(prompt=prompt, options=options):
        yield message


async def collect_result(
    prompt: str,
    *,
    max_turns: int = 300,
    **kwargs: Any,
) -> str:
    """Run agent and return the final text result."""
    result_text = ""
    async for message in run_agent(prompt, max_turns=max_turns, **kwargs):
        if message.__class__.__name__ == "ResultMessage":
            result_text = message.result or ""  # type: ignore[union-attr]
    return result_text


async def collect_structured_result(
    prompt: str,
    *,
    output_format: dict[str, Any],
    max_turns: int = 300,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Run agent with structured output and return the parsed result dict.

    Uses the ``output_format`` JSON schema to constrain the agent's final
    response. The result is parsed from the ResultMessage's text content.

    Args:
        prompt: The prompt to send to the agent.
        output_format: A JSON Schema output format dict (e.g.
            ``FEATURE_SUMMARY_SCHEMA`` from ``claw_forge.agent.output``).
        max_turns: Maximum conversation turns.
        **kwargs: Additional keyword arguments passed to ``run_agent()``.

    Returns:
        The parsed dict if a ResultMessage was received, or None if the
        agent didn't produce a final result.

    Example::

        from claw_forge.agent.output import CODE_REVIEW_SCHEMA
        result = await collect_structured_result(
            "Review the code in src/",
            output_format=CODE_REVIEW_SCHEMA,
            model="claude-sonnet-4-5",
        )
        if result and result["verdict"] == "approve":
            print("Code approved!")
    """
    result_text = ""
    async for message in run_agent(
        prompt, output_format=output_format, max_turns=max_turns, **kwargs
    ):
        if message.__class__.__name__ == "ResultMessage":
            result_text = message.result or ""  # type: ignore[union-attr]

    if not result_text:
        return None

    try:
        return cast(dict[str, Any], json.loads(result_text))
    except (json.JSONDecodeError, TypeError):
        return None
