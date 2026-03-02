# claw-forge Architecture

## System Overview

```
┌─────────────────────────────────────────────────────┐
│                    CLI (Typer)                        │
│  claw-forge run | init | pool-status | state         │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                  Orchestrator                         │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │ Dispatcher   │  │ Pool Runner  │  │   Hooks     │ │
│  │ (TaskGroup)  │  │ (Semaphore)  │  │ PreToolUse  │ │
│  │              │  │              │  │ PreCompact  │ │
│  └──────┬──────┘  └──────┬───────┘  └─────────────┘ │
└─────────┼────────────────┼──────────────────────────┘
          │                │
┌─────────▼────────────────▼──────────────────────────┐
│              Provider Pool Manager                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │  Router   │  │ Circuit  │  │  Usage   │           │
│  │ Strategy  │  │ Breakers │  │ Tracker  │           │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘           │
│       │              │              │                 │
│  ┌────▼──────────────▼──────────────▼───────────┐    │
│  │              Provider Registry                │    │
│  │  ┌───────┐ ┌───────┐ ┌─────┐ ┌──────┐       │    │
│  │  │Anthro │ │Bedrock│ │Azure│ │Vertex│ │OAI│  │    │
│  │  └───────┘ └───────┘ └─────┘ └──────┘ └───┘  │    │
│  └───────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
          │
┌─────────▼────────────────────────────────────────────┐
│              State Service (FastAPI)                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │ Sessions  │  │  Tasks   │  │  Events  │           │
│  │  REST     │  │ Sched.   │  │ SSE + WS │           │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘           │
│       └──────────────┼──────────────┘                 │
│              ┌───────▼────────┐                       │
│              │  SQLite/Postgres│                       │
│              └────────────────┘                       │
└──────────────────────────────────────────────────────┘
```

## Core Components

### 1. Provider Pool Manager

The central innovation. Manages a pool of API providers with:

**Routing Strategies:**
- `priority` — sorted by priority field (default)
- `round_robin` — rotate evenly across providers
- `weighted_random` — probability-weighted selection
- `least_cost` — prefer cheapest providers
- `least_latency` — prefer fastest recent providers

**Circuit Breaker (per provider):**
```
CLOSED ──[N failures]──> OPEN ──[timeout]──> HALF_OPEN
  ▲                                              │
  └──────────[success]───────────────────────────┘
  HALF_OPEN ──[failure]──> OPEN
```

- Configurable failure threshold (default: 5)
- Configurable recovery timeout (default: 60s)
- Half-open state allows single test request

**Rate Limit Detection:**
- Per-provider request counting with sliding 60s window
- Automatic skip when provider hits max_rpm
- Respects `Retry-After` headers

**Cost Tracking:**
- Per-request cost calculation (input + output tokens × rates)
- Per-provider accumulation
- Latency tracking (rolling average of last 100 requests)

### 2. Plugin System

Plugins are agent types discovered via Python entry points:

```python
class AgentPlugin(Protocol):
    name: str
    description: str
    version: str
    def get_system_prompt(self, context: PluginContext) -> str: ...
    async def execute(self, context: PluginContext) -> PluginResult: ...
```

Built-in plugins:
- **Initializer** — project analysis, manifest generation
- **Coding** — implement features, fix bugs
- **Testing** — run tests, analyze failures
- **Reviewer** — code review, quality gates

### 3. Orchestrator

Pure asyncio orchestration using TaskGroup + Semaphore:

```python
async with asyncio.TaskGroup() as tg:
    for task in wave:
        tg.create_task(run_bounded(task))
```

**Dispatcher** executes tasks in dependency-ordered waves.
**Pool Runner** bounds concurrent API calls with semaphore.

### 4. State Service

FastAPI REST API replacing MCP-as-state-store:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/sessions` | POST | Create session |
| `/sessions/{id}` | GET | Get session |
| `/sessions/{id}/tasks` | POST/GET | Create/list tasks |
| `/tasks/{id}` | PATCH | Update task status |
| `/sessions/{id}/events` | GET (SSE) | Stream events |
| `/ws/{id}` | WebSocket | Real-time updates |

### 5. Session Manifest

Eliminates cold-start by pre-loading:
- Project metadata (language, framework, build system)
- Key files with role annotations
- Active skills configuration
- Prior decisions and context
- Environment variables

### 6. Hooks

**PreToolUse** — security gate before every tool invocation:
- Command blocklist (rm -rf, mkfs, etc.)
- Path blocklist (/etc/shadow, ~/.ssh/)
- Command length limits
- Optional tool allowlist

**PreCompact** — state flush before context compaction:
- Persists critical state to DB
- Prevents loss of decisions and progress

## Data Flow

```
User Request
    │
    ▼
CLI parses config + creates ProviderPoolManager
    │
    ▼
Orchestrator creates tasks from request
    │
    ▼
Scheduler orders by dependency + priority
    │
    ▼
For each wave:
    │
    ├─> Task 1 ──> Plugin.execute() ──> PoolManager.execute()
    │                                        │
    ├─> Task 2 ──> Plugin.execute() ──> PoolManager.execute()
    │                                        │
    └─> Task N ──> ...                       ▼
                                    Router selects provider
                                        │
                                    ┌───▼───┐
                                    │Try P1  │──fail──> Try P2 ──fail──> ... ──> PoolExhausted
                                    └───┬───┘
                                        │ success
                                        ▼
                                    Track usage + cost
                                        │
                                        ▼
                                    Return response
```

## Kanban UI

A real-time React/Vite/TailwindCSS board at `ui/` for monitoring feature progress.

```
Browser (http://localhost:5173)
    │
    ├── GET /api/*  ──proxy──>  claw-forge State Service (port 8888)
    └── WS  /ws    ──proxy──>  ws://localhost:8888/ws
                                        │
                                ConnectionManager.broadcast()
                                        │
                                   SSE + WS events
```

**Columns:** Pending | In Progress | Passing | Failed | Blocked

**Header:** project name, provider pool status dots, progress bar (X/Y passing),
live agent count, total cost tracker.

**Real-time events** (pushed over `/ws`):

| Event type | Payload |
|---|---|
| `feature_update` | `{feature: {...}}` — full feature state change |
| `pool_update` | `{providers: [...]}` — provider health snapshot |
| `agent_started` | `{session_id, feature_id}` |
| `agent_completed` | `{session_id, feature_id, passed}` |
| `cost_update` | `{total_cost, session_cost}` |

### ConnectionManager

Added to `claw_forge/state/service.py`. Tracks active `/ws` WebSocket connections
and exposes typed broadcast helpers.  Dead connections are pruned automatically
on send error.  The `AgentStateService` holds a public `ws_manager` attribute so
orchestrator components can push events directly.

### Running the UI

```bash
cd ui
npm install
npm run dev   # http://localhost:5173/?session=<uuid>
```

## Provider Types

| Type | Auth header | Endpoint | Use case |
|---|---|---|---|
| `anthropic` | `x-api-key` | `/v1/messages` | Direct Anthropic API |
| `anthropic_compat` | `x-api-key` (or none) | `/v1/messages` | Anthropic-format proxy |
| `anthropic_oauth` | `Authorization: Bearer` | `/v1/messages` | Claude CLI OAuth token |
| `openai_compat` | `Authorization: Bearer` | `/v1/chat/completions` | OpenAI-format proxy/Groq |
| `bedrock` | AWS SigV4 | Bedrock endpoint | AWS Bedrock |
| `azure` | `api-key` | Azure endpoint | Azure AI Foundry |
| `vertex` | Google OAuth | Vertex endpoint | Google Vertex AI |

### anthropic_compat

Use when your proxy exposes the **Anthropic wire format** (same headers and
endpoint as `api.anthropic.com`) at a custom `base_url`.  Differs from
`openai_compat` by using `x-api-key` instead of `Authorization: Bearer` and
hitting `/v1/messages` instead of `/v1/chat/completions`.

Supports `model_map` for proxy-specific model name remapping, and `api_key: null`
for no-auth internal proxies.

### anthropic_oauth

Auto-reads the Claude CLI OAuth token from `~/.claude/.credentials.json` (and
other standard paths) so users just run `claude login` once.  The token is
injected into an `AnthropicProvider` as a `Bearer` credential.  On 401, the
token file is re-read (handles background `claude login` token refresh).

## Technology Choices

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python 3.11+ | AI ecosystem, type hints, asyncio |
| Package manager | uv | Fast, reliable, single tool |
| CLI | Typer | Type-safe, auto-docs |
| HTTP client | httpx | Async, HTTP/2 |
| API framework | FastAPI | Async, auto-OpenAPI |
| ORM | SQLAlchemy 2.0 | Async, type-safe |
| Database | SQLite (default) | Zero-config, portable |
| Config | YAML | Human-readable, env var interpolation |
