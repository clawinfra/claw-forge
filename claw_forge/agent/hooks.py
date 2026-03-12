"""SDK hooks for claw-forge agents."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, cast

try:
    from claude_agent_sdk.types import HookContext, HookInput, HookMatcher, SyncHookJSONOutput
except ImportError:  # pragma: no cover — SDK always installed in production
    HookContext = Any  # type: ignore[assignment,misc]
    HookInput = Any  # type: ignore[assignment,misc]
    HookMatcher = Any  # type: ignore[assignment,misc]
    SyncHookJSONOutput = Any  # type: ignore[assignment,misc]

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
        hookSpecificOutput={
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
    data: dict[str, Any] = cast(dict[str, Any], input_data) if isinstance(input_data, dict) else {}
    error = str(data.get("error", ""))
    tool_name = str(data.get("tool_name", ""))
    print(f"[Tool failure] {tool_name}: {error[:200]}")
    return SyncHookJSONOutput(
        hookSpecificOutput={
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
            hookSpecificOutput={
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
        data: dict[str, Any] = (
            cast(dict[str, Any], input_data)
            if isinstance(input_data, dict)
            else {}
        )
        if data.get("stop_hook_active") and should_continue_fn():
            return SyncHookJSONOutput(
                continue_=True,
                hookSpecificOutput={  # type: ignore[typeddict-item,misc]
                    "hookEventName": "Stop",
                    "additionalContext": "Continue working — there are remaining tasks.",
                },
            )
        return SyncHookJSONOutput(
            continue_=False,
            hookSpecificOutput={  # type: ignore[typeddict-item,misc]
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
        data: dict[str, Any] = (
            cast(dict[str, Any], input_data)
            if isinstance(input_data, dict)
            else {}
        )
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
            hookSpecificOutput={
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
    data: dict[str, Any] = cast(dict[str, Any], input_data) if isinstance(input_data, dict) else {}
    agent_id = data.get("agent_id", "")
    agent_type = data.get("agent_type", "")
    print(f"[SubAgent] Starting: {agent_type} ({agent_id})")
    return SyncHookJSONOutput(
        hookSpecificOutput={
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
    data: dict[str, Any] = cast(dict[str, Any], input_data) if isinstance(input_data, dict) else {}
    agent_id = data.get("agent_id", "")
    agent_type = data.get("agent_type", "")
    print(f"[SubAgent] Stopped: {agent_type} ({agent_id})")
    return SyncHookJSONOutput(
        hookSpecificOutput={  # type: ignore[typeddict-item,misc]
            "hookEventName": "SubagentStop",
            "additionalContext": "",
        }
    )


# ── Auto-push hook factory ────────────────────────────────────────────────────


def auto_push_hook(project_dir: str, remote: str = "origin") -> Any:
    """Return a Stop hook that pushes to remote after agent completion.

    Only pushes if:
    - The project directory is a git repository
    - The specified remote exists
    - There is at least one commit ahead of remote

    Args:
        project_dir: Absolute path to the git repository.
        remote: Remote name to push to (default: "origin").
    """
    from pathlib import Path

    from claw_forge.git.commits import has_remote, push_to_remote

    async def _auto_push_hook(
        input_data: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> SyncHookJSONOutput:
        project_path = Path(project_dir)

        if not (project_path / ".git").is_dir():
            print(f"[AutoPush] Skipped — {project_dir} is not a git repository")
            return SyncHookJSONOutput(
                hookSpecificOutput={  # type: ignore[typeddict-item,misc]
                    "hookEventName": "Stop",
                    "additionalContext": "",
                }
            )

        if not has_remote(project_path, remote):
            print(f"[AutoPush] Skipped — remote '{remote}' not found")
            return SyncHookJSONOutput(
                hookSpecificOutput={  # type: ignore[typeddict-item,misc]
                    "hookEventName": "Stop",
                    "additionalContext": "",
                }
            )

        result = push_to_remote(project_path, remote=remote)
        if result["success"]:
            print(f"[AutoPush] ✅ Pushed {result['branch']} → {remote}")
        else:
            print(f"[AutoPush] ⚠️  Push failed: {result['error']}")

        return SyncHookJSONOutput(
            hookSpecificOutput={  # type: ignore[typeddict-item,misc]
                "hookEventName": "Stop",
                "additionalContext": (
                    f"[AutoPush] {'✅ Pushed' if result['success'] else '⚠️ Push failed'}: "
                    f"{result.get('branch', '')} → {remote}"
                ),
            }
        )

    return _auto_push_hook


# ── Hashline hook factories ───────────────────────────────────────────────────


def hashline_read_hook() -> Any:
    """Return a PostToolUse hook that annotates Read tool results with hashline tags.

    Intercepts the ``Read`` tool result and passes the content through
    ``hashline.annotate()`` before the agent sees it.  Binary files (detected
    by null bytes) are passed through unchanged — the hook is a *filter*, not
    a gate.

    Returns:
        Async hook function compatible with HookMatcher hooks list.
    """
    async def hook(
        input_data: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> SyncHookJSONOutput:
        from claw_forge.hashline import HashlineError, annotate

        data: dict[str, Any] = (
            cast(dict[str, Any], input_data) if isinstance(input_data, dict) else {}
        )
        result_content = str(data.get("output", data.get("content", "")))

        try:
            annotated = annotate(result_content)
        except HashlineError:
            annotated = result_content  # pass through on annotation failure

        return SyncHookJSONOutput(
            hookSpecificOutput={
                "hookEventName": "PostToolUse",
                "additionalContext": annotated,
            }
        )

    return hook


def hashline_edit_hook() -> Any:
    """Return a PreToolUse hook that translates hashline edit references for Edit tool.

    Intercepts Edit tool requests containing ``HASHLINE_EDIT`` markers, parses
    the hashline edit operations via ``parse_edit_ops()``, and translates
    hash-referenced edits into exact text replacements using ``apply_edits()``.

    If no ``HASHLINE_EDIT`` marker is present, the edit passes through unchanged
    (graceful degradation for normal str_replace edits).

    Returns:
        Async hook function compatible with HookMatcher hooks list.
    """
    async def hook(
        input_data: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> SyncHookJSONOutput:
        from pathlib import Path as _Path

        from claw_forge.hashline import HashlineError, apply_edits, parse_edit_ops

        data: dict[str, Any] = (
            cast(dict[str, Any], input_data) if isinstance(input_data, dict) else {}
        )
        tool_input = str(data.get("input", data.get("content", "")))

        # Only intercept if this looks like a hashline edit block
        if "HASHLINE_EDIT" not in tool_input:
            return SyncHookJSONOutput(
                hookSpecificOutput={
                    "hookEventName": "PreToolUse",
                    "additionalContext": "",
                }
            )

        try:
            ops = parse_edit_ops(tool_input)
            if not ops:
                return SyncHookJSONOutput(
                    hookSpecificOutput={
                        "hookEventName": "PreToolUse",
                        "additionalContext": "",
                    }
                )

            # Extract file path from HASHLINE_EDIT block
            import re as _re
            match = _re.search(r"HASHLINE_EDIT\s+(\S+)", tool_input)
            if not match:
                return SyncHookJSONOutput(
                    hookSpecificOutput={
                        "hookEventName": "PreToolUse",
                        "additionalContext": "",
                    }
                )

            file_path = match.group(1)
            p = _Path(file_path)
            if not p.is_absolute():
                _cwd: str | None = getattr(context, "cwd", None)
                if _cwd:
                    p = _Path(_cwd) / file_path

            original = p.read_text(encoding="utf-8") if p.exists() else ""
            apply_edits(original, ops)  # validate; actual write via write_file_with_edits
            return SyncHookJSONOutput(
                hookSpecificOutput={
                    "hookEventName": "PreToolUse",
                    "additionalContext": f"Hashline edits validated for {file_path}",
                }
            )
        except HashlineError as exc:
            return SyncHookJSONOutput(
                hookSpecificOutput={
                    "hookEventName": "PreToolUse",
                    "additionalContext": f"Hashline error: {exc}",
                }
            )
        except Exception as exc:  # noqa: BLE001
            return SyncHookJSONOutput(
                hookSpecificOutput={
                    "hookEventName": "PreToolUse",
                    "additionalContext": f"Hashline hook error: {exc}",
                }
            )

    return hook


def get_hashline_hooks() -> list[Any]:
    """Return the combined list of hashline hooks (Read annotation + Edit translation).

    Returns:
        List of HookMatcher entries for inclusion in the hooks dict.
    """
    return [
        HookMatcher(matcher="Read", hooks=[hashline_read_hook()]),
        HookMatcher(matcher="Edit", hooks=[hashline_edit_hook()]),
    ]


# ── Default hooks factory ─────────────────────────────────────────────────────


def get_default_hooks(
    edit_mode: str = "str_replace",
    loop_detect_threshold: int = 5,
    verify_on_exit: bool = True,
    auto_push: str | None = None,
) -> dict[str, Any]:
    """Return the default hooks dict for ClaudeAgentOptions.

    Includes:
    - PreToolUse/Bash: security allowlist enforcement
    - PreCompact: workflow-state preservation guidance
    - PostToolUse: context injection after tool calls
    - PostToolUseFailure: failure logging + recovery hints
    - SubagentStart: standards injection for sub-agents
    - SubagentStop: sub-agent lifecycle logging

    When edit_mode is "hashline", also includes:
    - PostToolUse/Read: hashline annotation of file content
    - PreToolUse/Edit: hashline edit translation

    When loop_detect_threshold > 0, also includes:
    - PostToolUse: loop detection middleware (doom-loop warning injection)

    When verify_on_exit is True, also includes:
    - Stop: PreCompletionChecklistMiddleware (force verification before exit)

    When auto_push is set, also includes:
    - Stop: auto-push hook (git push to remote after agent completion)

    Args:
        edit_mode: "str_replace" (default) or "hashline".
        loop_detect_threshold: Max edits to a single file before injecting
            a warning. Default 5. Set to 0 to disable.
        verify_on_exit: If True (default), include the PreCompletionChecklistMiddleware
            Stop hook to force verification before agent exit.
        auto_push: If set, path to the git project dir — pushes to origin after
            agent completion. Format: "/path/to/repo" or "/path/to/repo:remote-name".
            Set to None (default) to disable.
    """
    pre_tool_use_hooks: list[Any] = [
        HookMatcher(matcher="Bash", hooks=[bash_security_hook]),
    ]
    post_tool_use_hooks: list[Any] = [
        HookMatcher(hooks=[post_tool_hook]),
    ]

    if edit_mode == "hashline":
        pre_tool_use_hooks.append(HookMatcher(matcher="Edit", hooks=[hashline_edit_hook()]))
        post_tool_use_hooks.append(HookMatcher(matcher="Read", hooks=[hashline_read_hook()]))

    # ── Loop detection middleware ──────────────────────────────────────────────
    if loop_detect_threshold != 0:
        from claw_forge.agent.middleware.loop_detection import loop_detection_hook

        _loop_hook_fn, _loop_ctx = loop_detection_hook(
            threshold=loop_detect_threshold,
            edit_mode=edit_mode,
        )
        post_tool_use_hooks.append(HookMatcher(hooks=[_loop_hook_fn]))

    hooks_dict: dict[str, Any] = {
        "PreToolUse": pre_tool_use_hooks,
        "PreCompact": [
            HookMatcher(hooks=[pre_compact_hook]),
        ],
        "PostToolUse": post_tool_use_hooks,
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

    stop_hooks: list[Any] = []

    if verify_on_exit:
        from claw_forge.agent.middleware.pre_completion import pre_completion_checklist_hook

        stop_hooks.append(HookMatcher(hooks=[pre_completion_checklist_hook()]))

    if auto_push is not None:
        # Format: "/path/to/repo" or "/path/to/repo:remote-name"
        if ":" in auto_push and not auto_push.startswith("//:"):
            _push_path, _push_remote = auto_push.rsplit(":", 1)
        else:
            _push_path, _push_remote = auto_push, "origin"
        stop_hooks.append(HookMatcher(hooks=[auto_push_hook(_push_path, _push_remote)]))

    if stop_hooks:
        hooks_dict["Stop"] = stop_hooks

    return hooks_dict
