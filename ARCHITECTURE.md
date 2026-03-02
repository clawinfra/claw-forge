# claw-forge Architecture

## System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                        CLI  (Typer)                               │
│   run | init | status | pause | resume | input | pool-status | state │
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

Skills are bundled into the wheel via `force-include` in `pyproject.toml`, and also copied into the project directory on `claw-forge init` (via `claw_forge/scaffold.py`). At runtime, `claw_forge/lsp.py` resolves the skills path: packaged wheel first (`claw_forge/skills/`), falling back to the dev repo root (`skills/`).

### Three-Layer Skill Injection

`claw_forge/lsp.py` exposes two functions that together implement automatic skill injection:

#### Layer 1: LSP by file extension — `detect_lsp_plugins(project_path)`

Scans the project directory recursively for source files. Maps file extensions to LSP skill names:

| Extensions | Skill |
|---|---|
| `.py`, `.pyi` | `pyright` |
| `.ts`, `.tsx`, `.js`, `.jsx` | `typescript-lsp` |
| `.go` | `gopls` |
| `.rs` | `rust-analyzer` |
| `.c`, `.cpp`, `.cc`, `.h`, `.hpp` | `clangd` |
| `.sol` | `solidity-lsp` |

Returns deduplicated `SdkPluginConfig` list — one entry per detected language.

#### Layer 2 + 3: Agent type + task keywords — `skills_for_agent(agent_type, task_description)`

Combines two signal sources:

- **Agent type** (`AGENT_TYPE_SKILLS`): e.g. `coding` → `systematic-debug`, `verification-gate`, `test-driven`; `reviewing` → `code-review`, `security-audit`
- **Task keywords** (`TASK_KEYWORD_SKILLS`): e.g. `"database"` → `database`; `"docker"` → `docker`; `"security"` → `security-audit`; `"api"` / `"rest"` → `api-client`

Both layers are unified into a single deduplicated `SdkPluginConfig` list.

#### Auto-injection on `run_agent()`

Both functions are called automatically when `auto_inject_skills=True` (default) and `auto_detect_lsp=True` (default) are set on `run_agent()`. Skills are merged and passed to `ClaudeAgentOptions.plugins`.

**Pre-installed (18 total):**

| Category | Skills |
|---|---|
| LSP | pyright, gopls, rust-analyzer, typescript-lsp, clangd, solidity-lsp |
| Process | systematic-debug, verification-gate, parallel-dispatch, test-driven, code-review, web-research |
| Integration | git-workflow, api-client, docker, security-audit, performance, database |

---

## Brownfield Mode

Brownfield support enables claw-forge to work on **existing codebases**. It is designed as an analysis → manifest → action pipeline:

```
claw-forge analyze        # scan project → write brownfield_manifest.json
claw-forge add <feature>  # read manifest → implement feature matching conventions
claw-forge fix <bug>      # read manifest → RED-GREEN fix cycle
```

**`BrownfieldAnalyzer`** (planned — see `PLAN.md`):
1. Detect stack (language, framework, package manager)
2. Parse git log → identify hot files
3. Read source → infer naming conventions, test patterns
4. Run test suite → establish passing baseline
5. Identify entry points and architecture layers
6. Write `brownfield_manifest.json`

The manifest is consumed by `add` and `fix` agents to ensure new code matches existing conventions and doesn't break the test baseline.

> **Status:** `analyze`, `add`, and `fix` commands are planned. See [`docs/brownfield.md`](docs/brownfield.md) for the full design.

---

## Technology Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | AI ecosystem, asyncio, type hints |
| Agent runtime | claude-agent-sdk | Official SDK — tool loop, MCP, hooks, streaming |
| Package manager | uv | Fast, isolated, single binary |
| CLI | Typer + type-safe commands | Type-safe, auto-docs, shell completion |
| HTTP client | httpx | Async, HTTP/2, clean API |
| API framework | FastAPI | Async, auto-OpenAPI, WebSocket |
| ORM | SQLAlchemy 2.0 | Async, type-safe |
| Database | SQLite (default) / PostgreSQL | Zero-config local; scalable cloud |
| Config | YAML + env var interpolation | Human-readable, 12-factor friendly |
| UI | React 18 + Vite + Tailwind | Fast build, small bundle, no framework overhead |
| Testing | pytest + pytest-asyncio | 584 tests, 90%+ coverage enforced in CI |
| Type checking | mypy | Clean — 0 errors across 54 files |

---

## Key Source Files

| File | Description |
|---|---|
| `claw_forge/cli.py` | Typer CLI — all commands: `run`, `init`, `status`, `pause`, `resume`, `input`, `pool-status`, `state`, `ui` |
| `claw_forge/lsp.py` | 3-layer skill injection: `detect_lsp_plugins()` (file ext → LSP), `skills_for_agent()` (agent type + task keywords) |
| `claw_forge/scaffold.py` | Project scaffolding — detects stack, generates `CLAUDE.md`, copies `.claude/commands/` on `claw-forge init` |
| `claw_forge/commands/help_cmd.py` | `claw-forge status` command — shows project progress bars, phase state, active agents, next action |
| `claw_forge/agent/` | Agent layer: `AgentSession`, runner, hooks, permissions, tools, thinking, output schemas |
| `claw_forge/pool/` | Provider pool: router, circuit breaker, usage tracker, provider registry |
| `claw_forge/mcp/sdk_server.py` | In-process MCP server — feature management tools |
| `claw_forge/state/service.py` | FastAPI state service — REST + WebSocket + SSE |
| `claw_forge/plugins/base.py` | Plugin protocol — entry-point-based agent type extensions |

## Further Reading

- [`docs/sdk-api-guide.md`](docs/sdk-api-guide.md) — All 20 Claude Agent SDK APIs with claw-forge examples
- [`docs/brownfield.md`](docs/brownfield.md) — Brownfield mode design: analyze → manifest → add/fix
- [`website/features.html`](website/features.html) — Full feature list
- [`website/tutorial.html`](website/tutorial.html) — End-to-end quickstart
- [`claw-forge.yaml`](claw-forge.yaml) — Annotated configuration reference
