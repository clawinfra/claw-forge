# claw-forge Architecture

## System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                        CLI  (Typer)                               │
│   run | init | pause | resume | input | pool-status | state      │
└─────────────────────────────┬────────────────────────────────────┘
                               │
┌──────────────────────────────▼────────────────────────────────────┐
│                        Orchestrator                                │
│  ┌───────────────┐  ┌────────────────┐  ┌──────────────────────┐  │
│  │  Dispatcher    │  │  Pool Runner   │  │       Hooks          │  │
│  │  (TaskGroup)   │  │  (Semaphore)   │  │  PreToolUse (bash)   │  │
│  │  dep-ordered   │  │  concurrency   │  │  PostToolUse         │  │
│  │  waves         │  │  bounds        │  │  PostToolUseFailure  │  │
│  └───────┬───────┘  └───────┬────────┘  │  UserPromptSubmit    │  │
│          │                   │           │  Stop / SubagentStart│  │
│          └─────────┬─────────┘           │  Notification        │  │
│                    │                     │  PreCompact          │  │
└────────────────────┼─────────────────────┴──────────────────────┘  │
                     │
┌────────────────────▼──────────────────────────────────────────────┐
│                   Agent Layer  (claw_forge/agent/)                 │
│                                                                    │
│  ┌───────────────────────────────────────────────────────────┐    │
│  │  AgentSession  (ClaudeSDKClient — bidirectional)           │    │
│  │    run() · follow_up() · interrupt() · switch_model()     │    │
│  │    escalate_permissions() · rewind() · mcp_health()       │    │
│  └───────────────────────────┬───────────────────────────────┘    │
│                               │                                    │
│  ┌───────────────┐  ┌─────────▼──────────┐  ┌──────────────────┐  │
│  │  runner.py    │  │   hooks.py         │  │  permissions.py  │  │
│  │  query() wrap │  │  all SDK hooks     │  │  CanUseTool CB   │  │
│  │  collect_     │  │  get_default_hooks │  │  project-scoped  │  │
│  │  structured_  │  │  factories         │  │  input mutation  │  │
│  └───────────────┘  └────────────────────┘  └──────────────────┘  │
│                                                                    │
│  ┌───────────────┐  ┌────────────────────┐  ┌──────────────────┐  │
│  │  tools.py     │  │  thinking.py       │  │  output.py       │  │
│  │  per-type     │  │  ThinkingConfig    │  │  JSON Schema     │  │
│  │  tool lists   │  │  presets           │  │  presets         │  │
│  │  max_turns    │  │  effort levels     │  │  structured_out  │  │
│  └───────────────┘  └────────────────────┘  └──────────────────┘  │
│                                                                    │
│  ┌───────────────┐  ┌────────────────────┐                        │
│  │  rate_limit   │  │  lock.py           │                        │
│  │  backoff      │  │  .claw-forge.lock  │                        │
│  │  retry_after  │  │  no duplicate      │                        │
│  └───────────────┘  └────────────────────┘                        │
└────────────────────────────────┬──────────────────────────────────┘
                                 │
┌────────────────────────────────▼──────────────────────────────────┐
│               In-Process MCP Server  (claw_forge/mcp/)            │
│                                                                    │
│  create_sdk_mcp_server() — zero subprocess overhead               │
│                                                                    │
│  feature_get_stats  · feature_get_ready   · feature_get_blocked   │
│  feature_claim_and_get  (atomic)          · feature_mark_passing  │
│  feature_mark_failing   · feature_create_bulk  · feature_create   │
│  feature_add_dependency · feature_clear_in_progress               │
└────────────────────────────────┬──────────────────────────────────┘
                                 │
┌────────────────────────────────▼──────────────────────────────────┐
│                   Provider Pool Manager                            │
│  ┌───────────────┐  ┌────────────────┐  ┌─────────────────────┐   │
│  │    Router     │  │    Circuit     │  │   Usage Tracker     │   │
│  │  priority     │  │    Breaker     │  │  rpm · cost · lat   │   │
│  │  round_robin  │  │  closed →      │  │  sliding 60s window │   │
│  │  weighted     │  │  half_open →   │  │  per-provider       │   │
│  │  least_cost   │  │  open          │  └─────────────────────┘   │
│  │  least_latency│  └────────────────┘                            │
│  └───────────────┘                                                 │
│                                                                    │
│  Provider Registry                                                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ ┌──────────┐  │
│  │anthropic │ │ compat   │ │  oauth   │ │bedrock │ │ azure    │  │
│  └──────────┘ └──────────┘ └──────────┘ └────────┘ └──────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                           │
│  │ vertex   │ │  groq/   │ │  ollama  │                           │
│  │          │ │ cerebras │ │  local   │                           │
│  └──────────┘ └──────────┘ └──────────┘                           │
└────────────────────────────────┬──────────────────────────────────┘
                                 │
┌────────────────────────────────▼──────────────────────────────────┐
│                  State Service  (FastAPI)                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │  Sessions    │  │    Tasks     │  │  Events                  │ │
│  │  REST CRUD   │  │  Scheduler   │  │  SSE  + WebSocket        │ │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘ │
│                                                                    │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  ConnectionManager  (ws_manager)                           │   │
│  │  broadcast_feature_update · broadcast_pool_update          │   │
│  │  broadcast_agent_started · broadcast_cost_update           │   │
│  └────────────────────────────────────────────────────────────┘   │
│                 ┌────────────────┐                                 │
│                 │ SQLite/Postgres │                                 │
│                 └────────────────┘                                 │
└────────────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. Provider Pool Manager

Manages multiple AI providers with automatic failover, rate-limit awareness, and cost tracking.

**Routing Strategies:**

| Strategy | Description |
|---|---|
| `priority` | Sorted by `priority` field (default) |
| `round_robin` | Rotate evenly across available providers |
| `weighted_random` | Probability-weighted selection by priority |
| `least_cost` | Prefer cheapest provider per token |
| `least_latency` | Prefer lowest avg latency in last 100 requests |

**Circuit Breaker (per provider):**

```
CLOSED ──[N failures]──> OPEN ──[timeout]──> HALF_OPEN
  ▲                                               │
  └──────────────[success]───────────────────────┘
  HALF_OPEN ──[failure]──> OPEN
```

- Configurable failure threshold (default: 5)
- Configurable recovery timeout (default: 60s)
- Half-open state allows one test request through

**Provider Types:**

| Type | Auth | Endpoint |
|---|---|---|
| `anthropic` | `x-api-key` | `/v1/messages` |
| `anthropic_compat` | `x-api-key` or none | `/v1/messages` (custom base_url) |
| `anthropic_oauth` | `Authorization: Bearer` | `/v1/messages` (auto-reads `~/.claude/.credentials.json`) |
| `openai_compat` | `Authorization: Bearer` | `/v1/chat/completions` |
| `bedrock` | AWS SigV4 | Bedrock regional endpoint |
| `azure` | `api-key` | Azure AI Foundry endpoint |
| `vertex` | Google OAuth | Vertex AI endpoint |
| `ollama` | optional Bearer | `http://localhost:11434/v1/chat/completions` |

### 2. Agent Layer

Built on [`claude-agent-sdk`](https://pypi.org/project/claude-agent-sdk/) as the core execution engine. All agent execution flows through the SDK — no raw HTTP calls or subprocess management.

#### `AgentSession` — Bidirectional Control

```
AgentSession (ClaudeSDKClient)
  ├── run(prompt)           →  send prompt, stream ResultMessage
  ├── follow_up(message)   →  mid-session guidance without restart
  ├── interrupt()          →  stop a runaway session
  ├── switch_model(model)  →  escalate to Opus for hard problems
  ├── escalate()           →  bypassPermissions for bulk ops
  ├── rewind(steps_back)   →  restore files to N checkpoints ago
  └── mcp_health()         →  live MCP server status for Kanban UI
```

Key `ClaudeAgentOptions` configuration applied by claw-forge:

| Option | Value | Why |
|---|---|---|
| `setting_sources` | `["project"]` | Load CLAUDE.md, skills, commands per project |
| `betas` | `["context-1m-2025-08-07"]` | 1M token context window |
| `max_buffer_size` | `10 * 1024 * 1024` | Handle large screenshots |
| `enable_file_checkpointing` | `True` | Rewind support |
| `thinking` | per task type | Adaptive vs deep vs disabled |
| `output_format` | schema dict | Structured JSON from review/plan agents |
| `fallback_model` | `claude-haiku-4-5` | Automatic model-level failover |
| `max_budget_usd` | per agent type | Hard cost cap per session |

#### `tools.py` — Per-Agent Tool Lists

Each agent type gets a scoped tool list:

| Agent type | Max turns | Extra tools |
|---|---|---|
| `coding` | 300 | All feature MCP tools + WebFetch + WebSearch |
| `testing` | 100 | Feature mark tools only (read + mark passing/failing) |
| `initializer` | 300 | Feature create + dependency tools |

#### `hooks.py` — Default Hook Stack

All hooks are applied by default via `get_default_hooks()`:

| Hook event | Purpose |
|---|---|
| `PreToolUse(Bash)` | Bash security — hardcoded blocklist + allowlist |
| `PostToolUse` | Inject progress/budget context after each tool |
| `PostToolUseFailure` | Log failure + inject recovery hints |
| `UserPromptSubmit` | Auto-inject project context to every prompt |
| `Stop` | Prevent premature exit while features remain |
| `SubagentStart` | Inject coding standards into sub-agents |
| `SubagentStop` | Log transcript path + broadcast to Kanban UI |
| `Notification` | Bridge agent notifications to WebSocket |
| `PreCompact` | Custom compaction instructions to preserve feature state |

#### `permissions.py` — `CanUseTool` Callback

Programmatic per-request permission control (used when `ClaudeSDKClient` is in streaming mode):

- Block hardcoded dangerous commands (`sudo`, `dd`, `shutdown`, etc.)
- Restrict `Write`/`Edit`/`MultiEdit` to project directory
- Supports input mutation via `PermissionResultAllow(updated_input={...})`

#### `output.py` — Structured Output Schemas

Three pre-built JSON Schema output formats:

| Schema | Used by | Key fields |
|---|---|---|
| `FEATURE_SUMMARY_SCHEMA` | Coding agent | `features_implemented`, `tests_passing`, `files_modified`, `blockers` |
| `CODE_REVIEW_SCHEMA` | Reviewer agent | `verdict` (approve/request_changes/block), `blockers`, `security_issues` |
| `PLAN_SCHEMA` | Planner agent | `steps[]` (order/description/files/tests), `complexity`, `risks` |

#### `thinking.py` — Thinking Config Presets

| Task type | Config | Token budget |
|---|---|---|
| `planning`, `architecture` | `ThinkingConfigEnabled` | 20,000 |
| `review` | `ThinkingConfigEnabled` | 10,000 |
| `coding`, `debugging` | `ThinkingConfigAdaptive` | model decides |
| `testing`, `monitoring` | `ThinkingConfigDisabled` | — |

### 3. In-Process MCP Server

`claw_forge/mcp/sdk_server.py` uses `create_sdk_mcp_server()` + `@tool` decorator to expose feature management as an **in-process** MCP server. No subprocess spawn — tools run as `async def` functions with direct SQLAlchemy access.

```
External MCP (AutoForge pattern)        claw-forge pattern
  Agent                                    Agent
    │ tool call                              │ tool call
    │ ──[IPC]──> MCP subprocess              │ ──[in-process]──>
    │ <──[IPC]── response                   │ <── async return
    ~400ms cold start                        ~0ms (already running)
```

Available tools: `feature_get_stats`, `feature_get_ready`, `feature_get_blocked`,
`feature_claim_and_get` (atomic), `feature_mark_passing`, `feature_mark_failing`,
`feature_mark_in_progress`, `feature_clear_in_progress`, `feature_create_bulk`,
`feature_create`, `feature_add_dependency`.

### 4. Security Model

Three-layer defence:

```
Layer 1: CanUseTool callback    →  Python function, runs before every tool
          │                        can block, allow, or mutate inputs
          │
Layer 2: Bash security hook     →  hooks.py PreToolUse(Bash)
          │                        hardcoded blocklist + project allowlist
          │
Layer 3: SandboxSettings        →  OS-level bash isolation (macOS/Linux)
                                    filesystem + network restrictions
```

**Agent lock file** (`.claw-forge.lock`) — prevents duplicate agents from running on the same project simultaneously.

### 5. Orchestrator

Pure asyncio using `TaskGroup` + `Semaphore` — no subprocess+threading mix:

```python
async with asyncio.TaskGroup() as tg:
    for task in current_wave:
        tg.create_task(bounded_execute(task, semaphore))
```

**Dispatcher** builds dependency-ordered waves using Kahn's topological sort.  
**Pool Runner** bounds concurrent API calls via semaphore.  
**Scheduler** handles time-based triggers (APScheduler).

**YOLO mode** (`--yolo`): CPU-count concurrency, 5 retries, human-input auto-approval.  
**Pause/resume**: drain mode finishes active features then stops gracefully.

### 6. Plugin System

Agent types discovered via `pyproject.toml` entry points — no forking the core:

```python
class AgentPlugin(Protocol):
    name: str
    description: str
    version: str
    def get_system_prompt(self, context: PluginContext) -> str: ...
    async def execute(self, context: PluginContext) -> PluginResult: ...
```

Built-in: `initializer`, `coding`, `testing`, `reviewer`

All built-in plugins call `collect_result()` from `claw_forge.agent` — they don't make HTTP calls directly.

### 7. State Service

FastAPI REST API + WebSocket + SSE. Replaces MCP-as-state-store anti-pattern.

| Endpoint | Method | Description |
|---|---|---|
| `/sessions` | POST | Create session |
| `/sessions/{id}` | GET | Get session with manifest |
| `/sessions/{id}/tasks` | POST/GET | Create / list tasks |
| `/tasks/{id}` | PATCH | Update task status, progress, cost |
| `/sessions/{id}/events` | GET (SSE) | Server-sent events stream |
| `/ws` | WebSocket | Global Kanban board updates |
| `/ws/{session_id}` | WebSocket | Per-session updates |
| `/sessions/{id}/pause` | POST | Pause (drain mode) |
| `/sessions/{id}/resume` | POST | Resume from pause |
| `/sessions/{id}/input` | POST | Provide human input for blocked agent |

**ConnectionManager** in `service.py` tracks active WebSocket connections and exposes typed broadcast helpers (`broadcast_feature_update`, `broadcast_pool_update`, `broadcast_agent_started`, `broadcast_cost_update`).

### 8. Session Manifest

Eliminates cold-start by pre-loading context into each new session:

```json
{
  "project_path": "/path/to/project",
  "language": "python",
  "framework": "fastapi",
  "key_files": [
    {"path": "src/auth.py", "role": "authentication module"},
    {"path": "tests/test_auth.py", "role": "auth test suite"}
  ],
  "active_skills": ["pyright-lsp", "verification-gate"],
  "prior_decisions": ["Using JWT over sessions for stateless API"],
  "env": {"PYTHONPATH": "src"}
}
```

### 9. Rate Limit Handling

`claw_forge/agent/rate_limit.py` handles API-level rate limits:

- `is_rate_limit_error(text)` — detects 429, 529, "rate limit", "too many requests"
- `parse_retry_after(text)` — extracts seconds from error text or headers
- `calculate_rate_limit_backoff(attempt)` — exponential backoff with jitter (max 15min)
- `calculate_error_backoff(attempt)` — linear backoff for non-rate-limit errors

---

## Data Flow

```
User: claw-forge run my-project
         │
         ▼
CLI reads claw-forge.yaml → builds ProviderPoolManager + AgentSession options
         │
         ▼
Orchestrator: load tasks from DB, build dependency graph, order into waves
         │
         ▼
Wave 1: [task-A, task-B]  (no dependencies)
  │
  ├──> Task A
  │      └──> AgentSession.run(coding_prompt)
  │               └──> ClaudeSDKClient.query(prompt)
  │                        └──> SDK streams AssistantMessage, ToolUseBlock, ResultMessage
  │                                 └──> ResultMessage → mark task A passing
  │
  └──> Task B  (parallel)
         └──> same flow
         │
         ▼
Wave 2: [task-C]  (depends on A + B — starts only after both pass)
  └──> ...
         │
         ▼
All tasks passing → session complete
```

---

## Kanban UI

React 18 + Vite + TailwindCSS + @tanstack/react-query + lucide-react.

```
Browser  http://localhost:5173/?session=<uuid>
    │
    ├── GET /api/*  ──proxy──>  State Service (port 8888)
    └── WS  /ws    ──proxy──>  ws://localhost:8888/ws
                                       │
                             ConnectionManager.broadcast()
```

**5 columns:** Pending | In Progress | Passing | Failed | Blocked

**Header:** project name · provider pool health dots · progress bar (X/Y passing) · live agent count · cost tracker

**WebSocket events pushed by state service:**

| Event | Payload |
|---|---|
| `feature_update` | Full feature state |
| `pool_update` | All provider health snapshots |
| `agent_started` | `session_id`, `feature_id` |
| `agent_completed` | `session_id`, `feature_id`, `passed` |
| `cost_update` | `total_cost`, `session_cost` |
| `agent_notification` | Title + message from SDK Notification hook |
| `mcp_health` | Live MCP server connection status |

---

## Skills System

Skills live in `skills/<name>/SKILL.md`. The agent reads them at runtime for context.

If a skill includes a `skill.yaml` with an `mcp` section, `load_skills_as_mcp()` can convert it to an `McpServerConfig` for tool-use access.

**Pre-installed (18 total):**

| Category | Skills |
|---|---|
| LSP | pyright, gopls, rust-analyzer, typescript-lsp, clangd, solidity-lsp |
| Process | systematic-debug, verification-gate, parallel-dispatch |
| Integration | web-research, git-workflow, api-client, docker, security-audit, performance, database, frontend-design, playwright-cli |

---

## Technology Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | AI ecosystem, asyncio, type hints |
| Agent runtime | claude-agent-sdk | Official SDK — tool loop, MCP, hooks, streaming |
| Package manager | uv | Fast, isolated, single binary |
| CLI | Typer | Type-safe, auto-docs, shell completion |
| HTTP client | httpx | Async, HTTP/2, clean API |
| API framework | FastAPI | Async, auto-OpenAPI, WebSocket |
| ORM | SQLAlchemy 2.0 | Async, type-safe |
| Database | SQLite (default) / PostgreSQL | Zero-config local; scalable cloud |
| Config | YAML + env var interpolation | Human-readable, 12-factor friendly |
| UI | React 18 + Vite + Tailwind | Fast build, small bundle, no framework overhead |
| Testing | pytest + pytest-asyncio | 427 tests, 90%+ coverage enforced in CI |

---

## Further Reading

- [`docs/sdk-api-guide.md`](docs/sdk-api-guide.md) — All 20 Claude Agent SDK APIs with claw-forge examples
- [`website/features.html`](website/features.html) — Full feature list
- [`website/tutorial.html`](website/tutorial.html) — End-to-end quickstart
- [`claw-forge.yaml`](claw-forge.yaml) — Annotated configuration reference
