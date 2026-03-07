# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test

```bash
uv sync --extra dev          # install all deps including dev tools
uv run pytest tests/ -q      # full test suite
uv run pytest tests/path/to/test_file.py::ClassName::test_name -v  # single test
uv run pytest tests/ -q --cov=claw_forge --cov-report=term-missing  # with coverage (must reach 90%)
uv run ruff check claw_forge/ tests/  # lint (CI uses this exact command)
uv run ruff check claw_forge/ tests/ --fix  # auto-fix lint errors
uv run mypy claw_forge/ --ignore-missing-imports  # type check
```

CI runs `uv sync --extra dev` (not plain `uv sync`) — plain sync omits pytest and ruff.

## Release Process

1. Push to `main`
2. Create a GitHub Release with a tag (e.g. `v0.1.0a64`)
3. The `Publish to PyPI` workflow triggers automatically — it re-runs tests, builds the UI, patches the version from the tag, and publishes the wheel

The publish workflow is **not** triggered by CI passing — only by a GitHub Release publication.

**Version in `pyproject.toml` is a static `0.0.0.dev0` placeholder** — do NOT bump it manually. The publish workflow overwrites it with the version from the release tag at build time.

## Architecture Overview

claw-forge is a **multi-provider autonomous coding agent harness**. It reads an app spec, decomposes it into a feature DAG, then orchestrates parallel AI agents to implement features, fix bugs, and run tests — all tracked via a local REST+WebSocket state service.

### Three-Layer Stack

```
CLI (Typer)  ──────────────────────────────────────────
  claw_forge/cli.py — 12+ commands (plan, run, add, fix, ui, status …)

State Service (FastAPI + SQLite via aiosqlite)  ────────
  claw_forge/state/service.py  — REST API + WebSocket /ws + SSE /events
  claw_forge/state/models.py   — Session, Task, Event ORM models
  claw_forge/state/scheduler.py — topological DAG scheduler

Orchestrator + Agent Execution + Provider Pool  ────────
  claw_forge/orchestrator/dispatcher.py — asyncio.TaskGroup parallel dispatch
  claw_forge/agent/runner.py            — wraps claude-agent-sdk query()
  claw_forge/pool/manager.py            — multi-provider rotation + circuit breaker
```

### How a `claw-forge run` Works

1. **State service** (`localhost:8888`) is started (subprocess) and manages all task state in SQLite
2. **Dispatcher** pulls "ready" tasks from the scheduler (tasks whose dependencies are all completed)
3. Each task is handed to the matching **plugin** (coding, testing, reviewer, bugfix)
4. The plugin calls `run_agent()` which wraps `claude_agent_sdk.query()` and yields messages
5. Task result is PATCHed back to the state service; WebSocket broadcasts updates to the UI
6. On failure: exponential backoff retry (up to `retry_attempts`); dependent tasks become "blocked"

### Provider Pool (`claw_forge/pool/`)

`ProviderPoolManager` wraps 8 provider implementations (Anthropic, Bedrock, Azure, Vertex, OpenAI-compat, Anthropic-compat, Ollama, OAuth). Each request:
- Routes through `Router` (5 strategies: PRIORITY, ROUND_ROBIN, WEIGHTED_RANDOM, LEAST_COST, LEAST_LATENCY)
- Respects per-provider `CircuitBreaker` (CLOSED → OPEN after N failures → HALF_OPEN after timeout)
- Tracks cost/tokens/latency in `UsageTracker`
- Falls through the full chain before raising `ProviderPoolExhausted`

### Agent Runner (`claw_forge/agent/runner.py`)

`run_agent()` is the main entrypoint for agent execution. It adds on top of the raw SDK:
- **Auto-injected MCP servers**: SDK MCP (in-process, zero cold-start) for features; LSP servers detected from file types (`.py` → pyright, `.ts` → typescript-language-server)
- **Auto-injected skills**: role-specific + task-keyword matched skills from `skills/` directory
- **Thinking strategy**: varies by `agent_type` (initializer = deep, coding = adaptive, testing = medium)
- **Security hooks**: `CanUseTool` callbacks blocking dangerous bash commands; filesystem writes restricted to `project_dir`

`collect_structured_result()` is used when structured JSON output (code review verdicts, feature summaries) is required.

### Plugin System (`claw_forge/plugins/`)

Plugins are discovered via Python entry points (`[project.entry-points."claw_forge.plugins"]` in `pyproject.toml`). Each implements the `AgentPlugin` protocol: `name`, `description`, `get_system_prompt(context)`, `execute(context) -> PluginResult`. Built-in plugins: `initializer`, `coding`, `testing`, `reviewer`, `bugfix`.

### MCP Servers (`claw_forge/mcp/`)

Two MCP surfaces:
- **`sdk_server.py`** (`create_feature_mcp_server`) — in-process SDK MCP, used by default (`use_sdk_mcp=True`)
- **`feature_mcp.py`** — subprocess FastMCP server (legacy fallback). Exposes `claim_feature`, `update_feature`, `list_features`, `get_feature` tools to agents.

### State Service API (default `localhost:8888`)

All CLI commands communicate with the state service via HTTP. Key endpoints:
- `POST /sessions`, `GET /sessions`, `GET /sessions/{id}`
- `POST /sessions/{id}/tasks`, `PATCH /sessions/{id}/tasks/{id}` (status, cost, tokens)
- `POST /sessions/{id}/tasks/{id}/human-input`
- `WebSocket /ws` — real-time broadcast of feature updates, cost events, pool health
- `GET /pool/status`
- `POST /shutdown`

### UI (`ui/`)

React + Vite + TypeScript Kanban board. Built with `npm --prefix ui run build`; output copied to `claw_forge/ui_dist/` before wheel packaging. In development, served via `claw-forge ui`. Connects to the state service WebSocket for real-time updates.

### spec/parser.py

Parses `app_spec.txt` or `app_spec.xml` (greenfield or brownfield) into a `ProjectSpec` with a list of features and dependency edges. The `initializer` plugin calls this to seed the task DAG in the state service.

## Key Conventions

- **Async throughout**: pure `asyncio`, no threads. `asyncio.TaskGroup` for structured concurrency in the dispatcher.
- **No DB migrations**: state service creates tables fresh on startup (`CREATE TABLE IF NOT EXISTS`).
- **`uv run`** is always used to execute Python tools — never activate the venv manually.
- **Coverage gate**: CI enforces `fail_under = 90` (branch coverage). Adding new source files without tests will fail CI.
- **Version in `pyproject.toml`** is a static `0.0.0.dev0` placeholder — never bump it manually. The publish workflow sets the real version from the release tag.
- **`.claw-forge/state.log`** is a runtime file, gitignored. Do not commit it.
