# Claude Agent SDK — API Guide for claw-forge

This document covers all 20 Claude Agent SDK APIs we leverage in claw-forge,
with concrete examples tied to our use cases: multi-agent coding pipelines,
feature state management, provider pool routing, and the Kanban UI.

---

## Table of Contents

1. [In-Process MCP Server](#1-in-process-mcp-server)
2. [ClaudeSDKClient — Bidirectional Sessions](#2-claudesdkclient--bidirectional-sessions)
3. [File Checkpointing + Rewind](#3-file-checkpointing--rewind)
4. [CanUseTool — Programmatic Permissions](#4-canusetool--programmatic-permissions)
5. [AgentDefinition — Named Sub-Agents](#5-agentdefinition--named-sub-agents)
6. [PostToolUse Hook — Result Interception](#6-posttooluse-hook--result-interception)
7. [PostToolUseFailure Hook — Auto Recovery](#7-posttoolusefailure-hook--auto-recovery)
8. [UserPromptSubmit Hook — Prompt Enrichment](#8-userpromptsubmit-hook--prompt-enrichment)
9. [Stop Hook — Prevent Premature Exit](#9-stop-hook--prevent-premature-exit)
10. [SubagentStart / SubagentStop Hooks](#10-subagentstart--subagentsthop-hooks)
11. [Notification Hook — Kanban Bridge](#11-notification-hook--kanban-bridge)
12. [ThinkingConfig — Adaptive Reasoning](#12-thinkingconfig--adaptive-reasoning)
13. [output_format — Structured JSON](#13-output_format--structured-json)
14. [fallback_model — Automatic Failover](#14-fallback_model--automatic-failover)
15. [max_budget_usd — Cost Cap](#15-max_budget_usd--cost-cap)
16. [StreamEvent — Token-Level Streaming](#16-streamevent--token-level-streaming)
17. [continue_conversation / resume / fork_session](#17-continue_conversation--resume--fork_session)
18. [SandboxSettings — OS-Level Isolation](#18-sandboxsettings--os-level-isolation)
19. [get_mcp_status() — Live MCP Health](#19-get_mcp_status--live-mcp-health)
20. [PermissionUpdate — Dynamic Rule Changes](#20-permissionupdate--dynamic-rule-changes)

---

## 1. In-Process MCP Server

**SDK APIs:** `create_sdk_mcp_server()`, `@tool` decorator, `McpSdkServerConfig`

### Why It Matters for claw-forge

AutoForge restarts a Python subprocess as an MCP server for every agent session — adding ~400ms cold-start overhead per session. The SDK's `create_sdk_mcp_server()` runs MCP tools **inside the same Python process**, with direct access to the DB session and zero IPC cost.

### How We Use It

```python
# claw_forge/mcp/sdk_server.py
from claude_agent_sdk import tool, create_sdk_mcp_server
from claw_forge.state.service import get_db  # direct DB access, no subprocess

@tool(
    name="feature_claim_and_get",
    description="Atomically claim the next available feature for this agent",
    input_schema={"agent_id": str},
)
async def feature_claim_and_get(args: dict) -> dict:
    async with get_db() as db:
        feature = await db.claim_next_feature(args["agent_id"])
        if not feature:
            return {"content": [{"type": "text", "text": "no_features_available"}]}
        return {"content": [{"type": "text", "text": json.dumps(feature.to_dict())}]}

@tool(
    name="feature_mark_passing",
    description="Mark a feature as passing after tests succeed",
    input_schema={"feature_id": int},
)
async def feature_mark_passing(args: dict) -> dict:
    async with get_db() as db:
        await db.mark_feature_passing(args["feature_id"])
    return {"content": [{"type": "text", "text": "ok"}]}

# Create once — reuse across all agent sessions
FEATURE_MCP_SERVER = create_sdk_mcp_server(
    name="features",
    version="1.0.0",
    tools=[
        feature_claim_and_get,
        feature_mark_passing,
        feature_mark_failing,
        feature_get_stats,
        feature_get_ready,
        feature_get_blocked,
        feature_create_bulk,
        feature_add_dependency,
    ],
)

# Use in ClaudeAgentOptions
options = ClaudeAgentOptions(
    mcp_servers={"features": FEATURE_MCP_SERVER},  # type: "sdk" — in-process
    allowed_tools=["mcp__features__feature_claim_and_get", "mcp__features__feature_mark_passing"],
)
```

### Key Points
- The `McpSdkServerConfig` has `type: "sdk"` — the SDK routes tool calls in-process
- Tool handlers are `async def` — they can `await` DB calls, HTTP requests, anything
- The server instance is created **once** and reused — no per-session startup cost
- `input_schema` accepts `{param: type}` shorthand or full JSON Schema

---

## 2. ClaudeSDKClient — Bidirectional Sessions

**SDK APIs:** `ClaudeSDKClient`, `client.query()`, `client.receive_response()`, `client.interrupt()`, `client.set_model()`, `client.set_permission_mode()`

### Why It Matters for claw-forge

`query()` is fire-and-forget — all input upfront, no mid-session control. `ClaudeSDKClient` gives us a persistent bidirectional connection where we can:
- Send follow-up messages based on Claude's responses
- Escalate permissions mid-session (default → bypassPermissions)
- Switch to Opus when Claude hits a hard problem
- Interrupt runaway sessions

### How We Use It

```python
# claw_forge/agent/session.py
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, ResultMessage, TextBlock

class AgentSession:
    """Stateful bidirectional coding session with mid-run control."""

    def __init__(self, options: ClaudeAgentOptions):
        self._client = ClaudeSDKClient(options)
        self._checkpoints: list[str] = []

    async def __aenter__(self):
        await self._client.connect()
        return self

    async def __aexit__(self, *args):
        await self._client.disconnect()

    async def run(self, prompt: str):
        """Primary coding prompt."""
        await self._client.query(prompt)
        async for msg in self._client.receive_response():
            # Save checkpoints for rewind (see API #3)
            if isinstance(msg, UserMessage) and msg.uuid:
                self._checkpoints.append(msg.uuid)
            yield msg

    async def guide(self, message: str):
        """Send mid-session guidance when Claude goes off-track."""
        await self._client.query(message)
        async for msg in self._client.receive_response():
            yield msg

    async def escalate(self):
        """Switch to bypassPermissions for trusted bulk operations."""
        await self._client.set_permission_mode("bypassPermissions")

    async def upgrade_model(self):
        """Switch to Opus when Claude encounters a hard architectural problem."""
        await self._client.set_model("claude-opus-4-6")

    async def stop(self):
        """Interrupt a runaway session."""
        await self._client.interrupt()
```

**Usage in parallel orchestrator:**
```python
async with AgentSession(options) as session:
    async for msg in session.run(f"Implement feature #{feature_id}"):
        handle_message(msg)

    # Tests failed — guide without restarting
    if tests_failed:
        async for msg in session.guide("Focus on fixing the test failures in test_auth.py"):
            handle_message(msg)
```

### Key Points
- `ClaudeSDKClient` uses streaming mode internally — all messages arrive via `receive_response()`
- `set_model()` takes effect on the NEXT turn — not the current one
- `interrupt()` only works in streaming (bidirectional) mode
- `can_use_tool` callback (API #4) requires `AsyncIterable` prompt, not a string

---

## 3. File Checkpointing + Rewind

**SDK APIs:** `ClaudeAgentOptions(enable_file_checkpointing=True)`, `extra_args={"replay-user-messages": None}`, `client.rewind_files(user_message_id)`

### Why It Matters for claw-forge

When a coding agent makes destructive changes (large refactor, wrong approach), we can rewind all files to their state at any prior checkpoint — without git stash or manual recovery. Each user message exchange gets a UUID that serves as the rewind target.

### How We Use It

```python
# In AgentSession — extend from API #2
options = ClaudeAgentOptions(
    enable_file_checkpointing=True,
    extra_args={"replay-user-messages": None},  # gives us UserMessage.uuid in stream
    # ... other options
)

# During session — checkpoints are saved automatically in run()
async with AgentSession(options) as session:
    checkpoint_before_refactor = None

    async for msg in session.run("Refactor the authentication module"):
        if isinstance(msg, UserMessage) and msg.uuid:
            checkpoint_before_refactor = msg.uuid  # save before each major step
        handle_message(msg)

    # Run tests
    result = run_tests()
    if result.failed:
        # Undo the entire refactor — restore all files
        await session.rewind(steps_back=1)
        # Or target a specific checkpoint:
        # await session._client.rewind_files(checkpoint_before_refactor)

        # Try a different approach
        async for msg in session.guide("The refactor broke tests. Try a more conservative approach."):
            handle_message(msg)
```

**In `AgentSession.rewind()`:**
```python
async def rewind(self, steps_back: int = 1):
    """Rewind files to N user-message checkpoints ago."""
    if len(self._checkpoints) >= steps_back:
        target = self._checkpoints[-steps_back]
        await self._client.rewind_files(target)
        self._checkpoints = self._checkpoints[:-steps_back]  # pop rewound checkpoints
```

### Key Points
- Requires both `enable_file_checkpointing=True` AND `extra_args={"replay-user-messages": None}`
- `rewind_files()` restores **all tracked files** to their state at that message UUID
- Works at the file system level — no git required
- Only available in `ClaudeSDKClient` (not `query()`)

---

## 4. CanUseTool — Programmatic Permissions

**SDK APIs:** `CanUseTool` callback, `PermissionResultAllow`, `PermissionResultDeny`, `ToolPermissionContext`

### Why It Matters for claw-forge

The hook-based bash security (API used by AutoForge) fires as a side effect. `CanUseTool` is a **first-class callback** that runs synchronously in the permission decision path. It also supports **input mutation** — you can rewrite tool inputs before Claude executes them.

### How We Use It

```python
# claw_forge/agent/permissions.py
from pathlib import Path
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny, ToolPermissionContext

ALWAYS_BLOCK = {"dd", "sudo", "su", "shutdown", "reboot", "mkfs", "wipefs"}

def make_project_guard(project_dir: Path):
    """Create a permission callback scoped to a project directory."""

    async def can_use_tool(
        tool_name: str,
        tool_input: dict,
        ctx: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:

        # 1. Block hardcoded dangerous commands
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            for blocked in ALWAYS_BLOCK:
                if blocked in cmd.split():
                    return PermissionResultDeny(
                        behavior="deny",
                        message=f"'{blocked}' is permanently blocked.",
                        interrupt=False,
                    )

        # 2. Restrict file writes to project dir
        if tool_name in ("Write", "Edit", "MultiEdit"):
            file_path = tool_input.get("file_path", "")
            try:
                Path(file_path).resolve().relative_to(project_dir.resolve())
            except ValueError:
                return PermissionResultDeny(
                    behavior="deny",
                    message=f"Write outside project directory: {file_path}",
                )

        # 3. Mutate inputs — force dry_run=False to prevent Claude getting confused
        if tool_name == "Edit":
            return PermissionResultAllow(
                behavior="allow",
                updated_input={**tool_input, "dry_run": False},
            )

        return PermissionResultAllow(behavior="allow")

    return can_use_tool
```

**Wire into `AgentSession`:**
```python
# IMPORTANT: can_use_tool requires AsyncIterable prompt (not string)
async def _prompt_stream(prompt: str):
    yield {"type": "user", "message": {"role": "user", "content": prompt},
           "parent_tool_use_id": None, "session_id": "main"}

options = ClaudeAgentOptions(can_use_tool=make_project_guard(project_dir))
async with ClaudeSDKClient(options) as client:
    await client.connect(prompt=_prompt_stream("Implement feature #5"))
```

### Key Points
- `can_use_tool` and `permission_prompt_tool_name` are mutually exclusive — pick one
- `can_use_tool` **requires** `AsyncIterable` prompt; passing a string raises `ValueError`
- `PermissionResultAllow(updated_input={...})` lets you rewrite inputs before execution
- `PermissionResultDeny(interrupt=True)` stops the entire agent session

---

## 5. AgentDefinition — Named Sub-Agents

**SDK APIs:** `AgentDefinition`, `ClaudeAgentOptions(agents={...})`

### Why It Matters for claw-forge

Instead of spawning separate `sessions_spawn` processes for Planner/Builder/Reviewer, we can define named sub-agents that Claude can invoke directly within the same session. Each sub-agent gets its own system prompt, model, and tool subset.

### How We Use It

```python
# claw_forge/agent/agents.py
from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions

CLAW_FORGE_AGENTS = {
    "planner": AgentDefinition(
        description="Creates step-by-step implementation plans from feature specs",
        prompt="""You are a senior software architect. Given a feature spec, produce a
detailed implementation plan with: ordered steps, files to create/modify,
interfaces to define, test cases to write, and estimated complexity.
Output as structured JSON.""",
        model="opus",  # "sonnet" | "opus" | "haiku" | "inherit"
        tools=["Read", "Grep", "Glob"],  # read-only for planning
    ),
    "coder": AgentDefinition(
        description="Implements features following the plan",
        prompt="""You are an expert full-stack developer. Follow the implementation plan
exactly. Write clean, typed, tested code. Run tests after each file.
Mark features passing only when all tests pass.""",
        model="sonnet",
        tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    ),
    "reviewer": AgentDefinition(
        description="Reviews code for quality, security, and correctness",
        prompt="""You are a senior code reviewer. Check for: correctness, edge cases,
security vulnerabilities, type safety, performance issues, and test coverage.
Output structured verdict: approve | request_changes | block.""",
        model="opus",
        tools=["Read", "Grep", "Glob", "Bash"],
    ),
    "tester": AgentDefinition(
        description="Runs regression tests and reports failures",
        prompt="""You are a QA engineer. Run all tests. For each failure, provide:
root cause, affected feature, reproduction steps, and suggested fix.""",
        model="sonnet",
        tools=["Read", "Bash", "Glob"],
    ),
}

def build_options_with_agents(base_options: ClaudeAgentOptions) -> ClaudeAgentOptions:
    from dataclasses import replace
    return replace(base_options, agents=CLAW_FORGE_AGENTS)
```

### Key Points
- `model` is `"sonnet" | "opus" | "haiku" | "inherit"` — NOT a full model string
- Sub-agents inherit the parent's MCP servers unless `tools` is overridden
- Claude decides when to invoke a sub-agent based on the `description` field — make it specific
- Sub-agents count against `max_turns`

---

## 6. PostToolUse Hook — Result Interception

**SDK APIs:** `PostToolUseHookInput`, `PostToolUseHookSpecificOutput`, `additionalContext`

### Why It Matters for claw-forge

After every tool call, we can inject additional context back to Claude. Use cases: remaining token budget, feature progress bar, auto-suggestions based on tool output, cost warnings.

### How We Use It

```python
# claw_forge/agent/hooks.py
def make_post_tool_hook(progress_fn=None, budget_fn=None):
    """Factory — progress_fn() returns "X/Y features passing", budget_fn() returns tokens left."""

    async def hook(input_data, tool_use_id, context):
        tool_name = input_data.get("tool_name", "")
        extras = []

        if progress_fn:
            extras.append(f"Progress: {progress_fn()}")
        if budget_fn:
            remaining = budget_fn()
            if remaining < 10000:
                extras.append(f"⚠️ Low token budget: {remaining:,} tokens remaining")

        # After Bash — check if tests ran and summarize
        if tool_name == "Bash":
            response = str(input_data.get("tool_response", ""))
            if "PASSED" in response or "FAILED" in response:
                passed = response.count("PASSED")
                failed = response.count("FAILED")
                extras.append(f"Test run: {passed} passed, {failed} failed")

        return SyncHookJSONOutput(hookSpecificOutput={
            "hookEventName": "PostToolUse",
            "additionalContext": " | ".join(extras) if extras else "",
        })

    return hook
```

### Key Points
- `additionalContext` is injected into Claude's context as a system note after the tool result
- Empty string `""` is valid — no context injected, hook fires silently for logging
- Use `updatedMCPToolOutput` to override MCP tool responses (advanced use case)

---

## 7. PostToolUseFailure Hook — Auto Recovery

**SDK APIs:** `PostToolUseFailureHookInput`, `PostToolUseFailureHookSpecificOutput`

### Why It Matters for claw-forge

When a tool fails (command not found, file permission error, test crash), we auto-inject recovery suggestions directly into Claude's context so it can self-correct without another round-trip.

### How We Use It

```python
# claw_forge/agent/hooks.py
RECOVERY_HINTS = {
    "Bash": {
        "command not found": "Install the missing tool first with pip/npm/brew",
        "permission denied": "Check file permissions with `ls -la` and use `chmod` if needed",
        "ModuleNotFoundError": "Run `uv pip install <package>` to install missing dependency",
        "FAILED": "Fix the failing tests before marking the feature as passing",
    },
    "Write": {
        "permission denied": "The file may be read-only. Check with `ls -la` first",
        "No such file or directory": "Create parent directories with `mkdir -p` first",
    },
}

async def post_tool_failure_hook(input_data, tool_use_id, context):
    tool_name = input_data.get("tool_name", "")
    error = str(input_data.get("error", ""))

    # Find matching hint
    hint = ""
    for pattern, suggestion in RECOVERY_HINTS.get(tool_name, {}).items():
        if pattern.lower() in error.lower():
            hint = f" Suggestion: {suggestion}."
            break

    print(f"[Tool failure] {tool_name}: {error[:150]}{' → ' + hint if hint else ''}")

    return SyncHookJSONOutput(hookSpecificOutput={
        "hookEventName": "PostToolUseFailure",
        "additionalContext": f"The {tool_name} tool failed.{hint} Consider an alternative approach.",
    })
```

### Key Points
- `is_interrupt` in the input indicates whether the failure was caused by an interrupt
- Log failures here for the RSI loop to pick up (feeds improvement proposals)

---

## 8. UserPromptSubmit Hook — Prompt Enrichment

**SDK APIs:** `UserPromptSubmitHookInput`, `UserPromptSubmitHookSpecificOutput`, `additionalContext`

### Why It Matters for claw-forge

Automatically inject project context, coding standards, and current feature state into every prompt Claude receives — without duplicating this in every prompt template.

### How We Use It

```python
# claw_forge/agent/hooks.py
def make_prompt_enrichment_hook(project_dir: Path, feature_state_fn=None):
    """Auto-inject project context into every prompt."""

    async def hook(input_data, tool_use_id, context):
        ctx_parts = [
            f"Project: {project_dir.name}",
            f"Working dir: {project_dir}",
        ]
        if feature_state_fn:
            state = feature_state_fn()  # e.g. "12/20 features passing"
            ctx_parts.append(f"Feature progress: {state}")

        # Inject coding standards
        standards_file = project_dir / "CLAUDE.md"
        if standards_file.exists():
            ctx_parts.append("Coding standards: see CLAUDE.md in project root")

        return SyncHookJSONOutput(hookSpecificOutput={
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "\n".join(ctx_parts),
        })

    return hook
```

### Key Points
- `additionalContext` is appended to the user prompt as a system annotation
- Fires on EVERY user message — keep it cheap (no DB calls without caching)
- Use this to enforce consistency without bloating individual prompt templates

---

## 9. Stop Hook — Prevent Premature Exit

**SDK APIs:** `StopHookInput`, `stop_hook_active`, `SyncHookJSONOutput(continue_=True)`

### Why It Matters for claw-forge

Claude sometimes stops mid-task believing it's done when features remain. The Stop hook intercepts this and tells Claude to keep going, injecting remaining work context.

### How We Use It

```python
# claw_forge/agent/hooks.py
def make_stop_hook(remaining_features_fn):
    """Prevent agent from stopping while features remain.
    
    remaining_features_fn() → list of pending feature IDs
    """

    async def hook(input_data, tool_use_id, context):
        if not input_data.get("stop_hook_active"):
            return SyncHookJSONOutput(continue_=False,
                hookSpecificOutput={"hookEventName": "Stop"})

        remaining = remaining_features_fn()
        if remaining:
            feature_list = ", ".join(f"#{fid}" for fid in remaining[:5])
            more = f" and {len(remaining)-5} more" if len(remaining) > 5 else ""
            return SyncHookJSONOutput(
                continue_=True,
                hookSpecificOutput={
                    "hookEventName": "Stop",
                    "additionalContext": (
                        f"Do not stop — {len(remaining)} features still need implementation: "
                        f"{feature_list}{more}. "
                        f"Claim the next feature with feature_claim_and_get."
                    ),
                },
            )

        return SyncHookJSONOutput(continue_=False,
            hookSpecificOutput={"hookEventName": "Stop"})

    return hook
```

### Key Points
- `stop_hook_active` is `True` when the hook is actively preventing a stop — return `continue_=True` to keep going
- When all features are done, return `continue_=False` to allow graceful exit
- The `additionalContext` is injected as a system message that guides the next turn

---

## 10. SubagentStart / SubagentStop Hooks

**SDK APIs:** `SubagentStartHookInput`, `SubagentStopHookInput`, `SubagentStartHookSpecificOutput`

### Why It Matters for claw-forge

When Claude spawns its own sub-agents (via `AgentDefinition`), these hooks fire on start/stop. Use them to inject sub-agent-specific context, log lifecycle events, and update the Kanban UI.

### How We Use It

```python
# claw_forge/agent/hooks.py
def make_subagent_hooks(broadcast_fn=None):

    async def subagent_start(input_data, tool_use_id, context):
        agent_id = input_data.get("agent_id", "unknown")
        agent_type = input_data.get("agent_type", "unknown")

        print(f"[SubAgent ▶] {agent_type} ({agent_id}) starting")
        if broadcast_fn:
            await broadcast_fn({"type": "subagent_started", "agent_id": agent_id, "agent_type": agent_type})

        return SyncHookJSONOutput(hookSpecificOutput={
            "hookEventName": "SubagentStart",
            "additionalContext": (
                f"You are a {agent_type} sub-agent for claw-forge. "
                "Follow the project coding standards. "
                "Write tests for everything you implement."
            ),
        })

    async def subagent_stop(input_data, tool_use_id, context):
        agent_id = input_data.get("agent_id", "unknown")
        transcript = input_data.get("agent_transcript_path", "")

        print(f"[SubAgent ■] {agent_id} stopped. Transcript: {transcript}")
        if broadcast_fn:
            await broadcast_fn({"type": "subagent_stopped", "agent_id": agent_id})

        return SyncHookJSONOutput(continue_=True,
            hookSpecificOutput={"hookEventName": "SubagentStop"})

    return subagent_start, subagent_stop
```

### Key Points
- `agent_transcript_path` gives you the path to the sub-agent's full conversation transcript
- `agent_type` reflects the key used in `AgentDefinition` (e.g. `"planner"`, `"coder"`)

---

## 11. Notification Hook — Kanban Bridge

**SDK APIs:** `NotificationHookInput`, `NotificationHookSpecificOutput`

### Why It Matters for claw-forge

Claude sends notifications during long-running tasks (e.g., "Running tests...", "Implementing auth module"). Pipe these to the Kanban WebSocket for live status updates in the UI.

### How We Use It

```python
# claw_forge/agent/hooks.py
def make_notification_hook(ws_broadcast_fn=None):

    async def hook(input_data, tool_use_id, context):
        message = input_data.get("message", "")
        title = input_data.get("title", "Agent")
        notif_type = input_data.get("notification_type", "info")

        # Always print to console
        print(f"[{title}] {message}")

        # Bridge to Kanban WebSocket
        if ws_broadcast_fn:
            import asyncio
            asyncio.create_task(ws_broadcast_fn({
                "type": "agent_notification",
                "title": title,
                "message": message,
                "notification_type": notif_type,
            }))

        return SyncHookJSONOutput(hookSpecificOutput={
            "hookEventName": "Notification",
            "additionalContext": "",
        })

    return hook
```

### Key Points
- `notification_type` can be `"info"`, `"warning"`, `"error"` — map to Kanban card colours
- Use `asyncio.create_task()` so the hook returns immediately without blocking Claude

---

## 12. ThinkingConfig — Adaptive Reasoning

**SDK APIs:** `ThinkingConfigEnabled`, `ThinkingConfigAdaptive`, `ThinkingConfigDisabled`, `effort`

### Why It Matters for claw-forge

Expensive tasks like architecture planning and security review benefit from extended thinking. Fast tasks like monitoring and test running don't need it. We tune per task type.

### How We Use It

```python
# claw_forge/agent/thinking.py
from claude_agent_sdk import ThinkingConfigEnabled, ThinkingConfigAdaptive, ThinkingConfigDisabled

THINKING_BY_TASK = {
    # Deep analysis — give it a large budget
    "planning":      ThinkingConfigEnabled(type="enabled", budget_tokens=20_000),
    "architecture":  ThinkingConfigEnabled(type="enabled", budget_tokens=20_000),
    "review":        ThinkingConfigEnabled(type="enabled", budget_tokens=10_000),
    # Let Claude decide
    "coding":        ThinkingConfigAdaptive(type="adaptive"),
    "debugging":     ThinkingConfigAdaptive(type="adaptive"),
    # Speed first
    "testing":       ThinkingConfigDisabled(type="disabled"),
    "monitoring":    ThinkingConfigDisabled(type="disabled"),
}

def thinking_for_task(task_type: str):
    return THINKING_BY_TASK.get(task_type, ThinkingConfigAdaptive(type="adaptive"))

# Shorthand via effort level
EFFORT_BY_TASK = {
    "planning": "max",
    "architecture": "max",
    "review": "high",
    "coding": "medium",
    "testing": "low",
}
```

**In runner:**
```python
options = ClaudeAgentOptions(
    thinking=thinking_for_task(agent_type),
    # OR: effort=EFFORT_BY_TASK.get(agent_type, "medium"),
)
```

### Key Points
- `thinking` takes precedence over `max_thinking_tokens` (deprecated)
- `effort` is a shorthand: `"low"` | `"medium"` | `"high"` | `"max"`
- `budget_tokens` is a soft cap — Claude may use less
- `ThinkingBlock` messages appear in the stream when thinking is enabled

---

## 13. output_format — Structured JSON

**SDK APIs:** `ClaudeAgentOptions(output_format={...})`, `ResultMessage.structured_output`

### Why It Matters for claw-forge

Reviewer agents, planning agents, and test reporters need structured output. Instead of parsing Claude's prose, force a JSON schema and access `result.structured_output` directly.

### How We Use It

```python
# claw_forge/agent/output.py

# Reviewer verdict schema
CODE_REVIEW_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["approve", "request_changes", "block"]},
            "blockers": {"type": "array", "items": {"type": "string"}},
            "suggestions": {"type": "array", "items": {"type": "string"}},
            "security_issues": {"type": "array", "items": {"type": "string"}},
            "coverage_gaps": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["verdict", "blockers", "suggestions", "security_issues"],
    },
}

# Implementation summary schema (from coding agent)
FEATURE_SUMMARY_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "features_implemented": {"type": "array", "items": {"type": "string"}},
            "files_modified": {"type": "array", "items": {"type": "string"}},
            "tests_passing": {"type": "integer"},
            "tests_failing": {"type": "integer"},
            "blockers": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["features_implemented", "files_modified", "tests_passing", "tests_failing"],
    },
}

# Plan schema (from planning agent)
PLAN_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "order": {"type": "integer"},
                        "description": {"type": "string"},
                        "files_to_create": {"type": "array", "items": {"type": "string"}},
                        "files_to_modify": {"type": "array", "items": {"type": "string"}},
                        "tests_to_write": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "complexity": {"type": "string", "enum": ["low", "medium", "high"]},
            "risks": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["steps", "complexity"],
    },
}
```

**Usage:**
```python
async def run_reviewer(code_dir: Path, plan: str) -> dict:
    options = ClaudeAgentOptions(
        output_format=CODE_REVIEW_SCHEMA,
        # ... other options
    )
    result = None
    async for msg in query(prompt=f"Review the code in {code_dir}", options=options):
        if isinstance(msg, ResultMessage):
            result = msg
    # structured_output is already parsed — no JSON.loads() needed
    return result.structured_output  # {"verdict": "approve", "blockers": [], ...}
```

### Key Points
- `structured_output` on `ResultMessage` is the parsed dict — no manual JSON parsing
- Schema must be valid JSON Schema; use `"required"` to ensure fields are always present
- Works with both `query()` and `ClaudeSDKClient`

---

## 14. fallback_model — Automatic Failover

**SDK APIs:** `ClaudeAgentOptions(fallback_model=...)`

### Why It Matters for claw-forge

When the primary model is rate-limited or unavailable, the SDK automatically retries with the fallback. This replaces our manual rate-limit backoff logic for model-level failures.

### How We Use It

```python
# claw_forge/agent/runner.py
from claw_forge.pool.base import ProviderConfig

def options_from_provider(config: ProviderConfig, agent_type: str) -> ClaudeAgentOptions:
    """Build ClaudeAgentOptions from a ProviderConfig with automatic fallback."""
    return ClaudeAgentOptions(
        model=config.model or "claude-sonnet-4-6",
        fallback_model="claude-haiku-4-5",    # cheaper fallback when Sonnet is unavailable
        # Our provider pool handles API key rotation separately
        env={"ANTHROPIC_API_KEY": config.api_key} if config.api_key else {},
        thinking=thinking_for_task(agent_type),
        max_turns=get_max_turns(agent_type),
        betas=["context-1m-2025-08-07"],
    )
```

### Key Points
- `fallback_model` is tried when the primary model returns a server error or rate limit
- Our provider pool's circuit breaker handles **API key** rotation; `fallback_model` handles **model** failover — complementary layers

---

## 15. max_budget_usd — Cost Cap

**SDK APIs:** `ClaudeAgentOptions(max_budget_usd=...)`

### Why It Matters for claw-forge

Runaway agents can rack up significant API costs. `max_budget_usd` is a hard cap enforced by the SDK — the session stops when the limit is hit.

### How We Use It

```python
# Per-agent-type cost budgets
COST_BUDGETS = {
    "initializer": 2.00,   # complex, allow more
    "coding": 1.00,        # per feature session
    "testing": 0.25,       # fast checks only
    "reviewer": 0.50,      # focused review
    "planning": 0.75,      # architecture work
}

options = ClaudeAgentOptions(
    max_budget_usd=COST_BUDGETS.get(agent_type, 1.00),
    # ... other options
)
```

**Combined with cost tracking:**
```python
async for msg in query(prompt=prompt, options=options):
    if isinstance(msg, ResultMessage):
        cost = msg.total_cost_usd or 0.0
        await record_session_cost(feature_id=feature_id, cost_usd=cost)
```

### Key Points
- When the budget is exceeded, the session ends with a `ResultMessage(is_error=True)`
- `ResultMessage.total_cost_usd` gives the actual cost of the session — log it
- Combine with per-project budget tracking in the REST API

---

## 16. StreamEvent — Token-Level Streaming

**SDK APIs:** `ClaudeAgentOptions(include_partial_messages=True)`, `StreamEvent`

### Why It Matters for claw-forge

With `include_partial_messages=True`, the stream yields `StreamEvent` objects containing raw Anthropic API streaming events. This enables true typewriter effect in the Kanban terminal, showing Claude's output token by token.

### How We Use It

```python
# claw_forge/agent/streaming.py
from claude_agent_sdk import StreamEvent, AssistantMessage, TextBlock

async def stream_to_terminal(prompt: str, ws_send_fn, options: ClaudeAgentOptions):
    """Stream token-by-token output to Kanban terminal WebSocket."""
    from dataclasses import replace
    streaming_options = replace(options, include_partial_messages=True)

    async for msg in query(prompt=prompt, options=streaming_options):
        if isinstance(msg, StreamEvent):
            event = msg.event
            # Extract delta text from Anthropic streaming event
            if event.get("type") == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    token = delta.get("text", "")
                    await ws_send_fn({"type": "token", "text": token})

        elif isinstance(msg, AssistantMessage):
            # Complete message with all content blocks
            for block in msg.content:
                if isinstance(block, TextBlock):
                    await ws_send_fn({"type": "message_complete", "text": block.text})
```

### Key Points
- `StreamEvent.event` is the raw Anthropic API streaming event dict
- Use `StreamEvent` for the terminal UI; use `AssistantMessage` for structured processing
- Significantly increases message volume — only enable when a UI consumer is connected

---

## 17. continue_conversation / resume / fork_session

**SDK APIs:** `ClaudeAgentOptions(continue_conversation=True)`, `resume="session-id"`, `fork_session=True`

### Why It Matters for claw-forge

When a coding session is paused (user hits `/pause`) and later resumed, we can continue the exact conversation context without starting fresh. `fork_session` creates a branch — useful for trying an alternative approach without losing the original.

### How We Use It

```python
# claw_forge/agent/runner.py

async def resume_session(session_id: str, new_prompt: str, fork: bool = False):
    """Resume a paused coding session."""
    options = ClaudeAgentOptions(
        continue_conversation=False,  # use resume= instead for specific ID
        resume=session_id,
        fork_session=fork,  # True = try alternative approach, False = continue where left off
        # ... other options
    )
    async for msg in query(prompt=new_prompt, options=options):
        yield msg

# In the pause/resume REST endpoints:
# POST /projects/{name}/pause  → save session_id to DB
# POST /projects/{name}/resume → call resume_session(saved_session_id, ...)
```

### Key Points
- `continue_conversation=True` continues the **most recent** session
- `resume="session-id"` continues a **specific** session by ID
- `fork_session=True` creates a new session branched from the resumed one
- Session IDs come from `ResultMessage.session_id` in previous runs

---

## 18. SandboxSettings — OS-Level Isolation

**SDK APIs:** `SandboxSettings`, `SandboxNetworkConfig`, `SandboxIgnoreViolations`

### Why It Matters for claw-forge

Beyond our bash allowlist (which is process-level), `SandboxSettings` provides OS-level isolation — Claude can't escape the project directory even if our allowlist has a gap.

### How We Use It

```python
# claw_forge/agent/runner.py
from claude_agent_sdk import SandboxSettings, SandboxNetworkConfig

def build_sandbox(project_dir: Path, allow_docker: bool = False) -> SandboxSettings:
    excluded = ["git"]  # git commits always run unsandboxed
    if allow_docker:
        excluded.append("docker")  # docker needs host socket access

    return SandboxSettings(
        enabled=True,
        autoAllowBashIfSandboxed=True,
        excludedCommands=excluded,
        allowUnsandboxedCommands=False,  # strict — no bypasses
        network=SandboxNetworkConfig(
            allowLocalBinding=True,                        # dev servers on localhost
            allowUnixSockets=["/var/run/docker.sock"],    # docker socket if needed
        ),
    )

options = ClaudeAgentOptions(
    sandbox=build_sandbox(project_dir, allow_docker=True),
    # ... other options
)
```

### Key Points
- Only available on macOS and Linux (not Windows)
- `excludedCommands` run OUTSIDE the sandbox — use for tools that need host access (git, docker)
- `autoAllowBashIfSandboxed=True` auto-approves bash when sandbox is active
- Filesystem restrictions are still enforced via permission rules (`Read`/`Write`/`Edit` allow lists)

---

## 19. get_mcp_status() — Live MCP Health

**SDK APIs:** `client.get_mcp_status()`, `get_server_info()`

### Why It Matters for claw-forge

The Kanban UI shows provider health dots (green/yellow/red). `get_mcp_status()` gives us live MCP server connection status to display alongside API provider health.

### How We Use It

```python
# claw_forge/agent/session.py — in AgentSession

async def mcp_health(self) -> dict[str, str]:
    """Get live MCP server health for Kanban UI provider dots."""
    status = await self._client.get_mcp_status()
    # Returns: {"mcpServers": [{"name": "features", "status": "connected"}]}
    return {
        server["name"]: server["status"]
        for server in status.get("mcpServers", [])
    }

async def server_capabilities(self) -> dict | None:
    """Get server info including available commands."""
    return await self._client.get_server_info()

# In the WebSocket broadcast loop:
async def health_broadcast_loop(session: AgentSession, ws_broadcast_fn):
    while True:
        health = await session.mcp_health()
        await ws_broadcast_fn({
            "type": "mcp_health",
            "servers": health,  # {"features": "connected", "playwright": "failed"}
        })
        await asyncio.sleep(30)
```

### Key Points
- Status values: `"connected"` | `"pending"` | `"failed"` | `"needs-auth"` | `"disabled"`
- `get_server_info()` returns available slash commands and output styles (useful for UI)
- Only available in `ClaudeSDKClient` (streaming mode), not `query()`

---

## 20. PermissionUpdate — Dynamic Rule Changes

**SDK APIs:** `PermissionUpdate`, `PermissionRuleValue`, `PermissionUpdateDestination`, `PermissionResultAllow(updated_permissions=[...])`

### Why It Matters for claw-forge

Hooks and the `CanUseTool` callback can return `PermissionUpdate` objects that **persistently change** what Claude is allowed to do for the rest of the session. Useful for: unlocking write access to a new directory mid-session, adding a new allowed command when the agent proves it needs it.

### How We Use It

```python
# claw_forge/agent/permissions.py
from claude_agent_sdk import PermissionUpdate, PermissionResultAllow, PermissionRuleValue

async def can_use_tool(tool_name, tool_input, ctx):

    # If Claude wants to install a package, allow it AND permanently allow pip for this session
    if tool_name == "Bash" and "pip install" in tool_input.get("command", ""):
        return PermissionResultAllow(
            behavior="allow",
            updated_permissions=[
                PermissionUpdate(
                    type="addRules",
                    rules=[PermissionRuleValue(tool_name="Bash", rule_content="pip install *")],
                    behavior="allow",
                    destination="session",  # session-scoped, not persisted
                )
            ],
        )

    # If Claude writes to a new test directory, unlock it for the rest of the session
    if tool_name == "Write":
        file_path = tool_input.get("file_path", "")
        if "/tests/" in file_path:
            return PermissionResultAllow(
                behavior="allow",
                updated_permissions=[
                    PermissionUpdate(
                        type="addDirectories",
                        directories=[str(Path(file_path).parent)],
                        destination="session",
                    )
                ],
            )

    return PermissionResultAllow(behavior="allow")
```

### Key Points
- `destination` controls where the rule is stored: `"session"` (temporary) | `"projectSettings"` | `"userSettings"` | `"localSettings"`
- `type` options: `"addRules"` | `"replaceRules"` | `"removeRules"` | `"setMode"` | `"addDirectories"` | `"removeDirectories"`
- `PermissionUpdate` can only be returned from `CanUseTool` callback — not from standard hooks
- Use `"session"` destination for safety — rules don't persist after the session ends

---

## Quick Reference

| API | Mode | Use Case in claw-forge |
|-----|------|------------------------|
| `create_sdk_mcp_server` | both | In-process feature DB — zero cold-start |
| `ClaudeSDKClient` | client | Bidirectional stateful coding sessions |
| `enable_file_checkpointing` | client | Rewind files after bad refactor |
| `CanUseTool` | client | Programmatic security + input mutation |
| `AgentDefinition` | both | Named planner/coder/reviewer sub-agents |
| `PostToolUse` hook | both | Inject progress/budget after each tool |
| `PostToolUseFailure` hook | both | Auto-inject recovery hints on failure |
| `UserPromptSubmit` hook | both | Auto-inject project context to every prompt |
| `Stop` hook | both | Prevent premature exit while features remain |
| `SubagentStart/Stop` hooks | both | Lifecycle logging + Kanban UI updates |
| `Notification` hook | both | Bridge agent notifications to WebSocket |
| `ThinkingConfig` | both | Adaptive reasoning per task type |
| `output_format` | both | Structured JSON from reviewer/planner agents |
| `fallback_model` | both | Automatic model-level failover |
| `max_budget_usd` | both | Hard cost cap per session |
| `StreamEvent` | both | Token-level streaming to terminal UI |
| `continue_conversation/resume` | both | Pause/resume coding sessions |
| `SandboxSettings` | both | OS-level bash isolation |
| `get_mcp_status()` | client | Live MCP health for Kanban health dots |
| `PermissionUpdate` | client | Dynamic per-session permission rules |

**Mode:** `both` = works with `query()` and `ClaudeSDKClient` | `client` = requires `ClaudeSDKClient`
