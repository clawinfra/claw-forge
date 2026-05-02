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
  claw_forge/cli.py — 18+ commands (plan, run, add, fix, ui, status, export …)
  claw_forge/boundaries/cli.py — Typer subapp: boundaries audit | apply | status
  claw_forge/git/cli.py — Typer subapp: worktrees list | prune (cleans up .claw-forge/worktrees/)
  claw_forge/git/cleanup.py — smart-mode startup cleanup (preserve/salvage/remove per task state)
  claw_forge/git/conflict_advisor.py — opt-in LLM advisor that drafts CONFLICT_PROPOSAL.md on salvage conflict

State Service (FastAPI + SQLite via aiosqlite)  ────────
  claw_forge/state/service.py  — REST API + WebSocket /ws + SSE /events
  claw_forge/state/models.py   — Session, Task, Event ORM models
  claw_forge/state/scheduler.py — topological DAG scheduler

Orchestrator + Agent Execution + Provider Pool  ────────
  claw_forge/orchestrator/dispatcher.py — asyncio.TaskGroup parallel dispatch
  claw_forge/agent/runner.py            — wraps claude-agent-sdk query()
  claw_forge/pool/manager.py            — multi-provider rotation + circuit breaker

Git Workspace Tracking  ────────────────────────────────
  claw_forge/git/slug.py     — centralized slug generation (make_slug, make_branch_name)
  claw_forge/git/branching.py — feature branch create/switch/delete
  claw_forge/git/commits.py  — checkpoint commits with structured trailers
  claw_forge/git/merge.py    — squash-merge feature branches to main

Spec & Export  ──────────────────────────────────────────
  claw_forge/spec/parser.py  — XML/plain-text spec → ProjectSpec; honours <feature index, depends_on>
  claw_forge/exporter.py     — read-only CSV/SQL/JSON export of session+task data from state.db

Boundaries Harness  ─────────────────────────────────────
  claw_forge/boundaries/walker.py    — git ls-files-driven source enumeration
  claw_forge/boundaries/signals.py   — dispatch / import / churn / function signals
  claw_forge/boundaries/scorer.py    — composite weighted score + threshold ranker
  claw_forge/boundaries/audit.py     — top-level audit pipeline (read-only)
  claw_forge/boundaries/classifier.py — subagent that labels hotspots with refactor pattern
  claw_forge/boundaries/report.py    — boundaries_report.md emit/parse round-trip
  claw_forge/boundaries/refactor.py  — pattern-specific subagent prompts
  claw_forge/boundaries/apply.py     — per-hotspot apply lifecycle (gate → merge or revert)
```

### How a `claw-forge run` Works

1. **State service** (`localhost:8420`) is started (subprocess) and manages all task state in SQLite
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

### State Service Auto-Start (`cli.py` `_ensure_state_service`)

Both `claw-forge run` and `claw-forge ui` auto-start the state service via `_ensure_state_service()`:
- **Project-aware**: passes `--config` pointing to the project directory's `claw-forge.yaml` so the subprocess finds the correct config even when CWD differs from the project dir
- **Project verification**: after starting, verifies `/info` returns a `project_path` matching the intended project (not just non-null)
- **Port fallback**: if the configured port is occupied, tries port+1 … port+4
- **Version check**: restarts the service if the running version differs from the CLI version

### Session Resolution (`cli.py` `_resolve_latest_session`)

All session auto-detection (ui prod, ui dev, dev command) uses `_resolve_latest_session()`:
- **Project-filtered**: queries `WHERE project_path = ?` to avoid picking up stale test sessions or sessions from other projects sharing the same DB
- **Centralized**: all inline session queries have been consolidated into this single function

### State Service API (default `localhost:8420`)

All CLI commands communicate with the state service via HTTP. Key endpoints:
- `POST /sessions`, `GET /sessions`, `GET /sessions/{id}`
- `POST /sessions/{id}/tasks` (accepts optional `touches_files: list[str]` for file-lock declaration), `PATCH /sessions/{id}/tasks/{id}` (status, cost, tokens, merged_to_target_branch)
- `POST /sessions/{id}/tasks/{id}/human-input`
- `POST /sessions/{id}/tasks/stop-all`, `POST /sessions/{id}/tasks/resume-all` — pause/resume in-flight tasks
- `POST /sessions/{id}/tasks/requeue` — batch reset failed/blocked tasks to pending. Body: `{statuses: list[str] = ["failed", "blocked"], error_pattern?: str}`. Optional ``error_pattern`` is a SQL ``LIKE`` filter on ``error_message`` (e.g. ``"%rate_limit%"`` to reset only rate-limit failures). Used by the Kanban UI's "Reset All" button on the Failed and Blocked column headers.
- `POST /sessions/{id}/file-claims` — atomic file-lock claim for a task; returns 200 on success or 409 with conflict list
- `DELETE /sessions/{id}/file-claims/{task_id}` — release all claims held by a task
- `GET /sessions/{id}/file-claims` — list current claims (for debugging)
- `WebSocket /ws` — real-time broadcast of feature updates, cost events, pool health
- `GET /pool/status`
- `POST /shutdown`

### UI (`ui/`)

React + Vite + TypeScript Kanban board. Built with `npm --prefix ui run build`; output copied to `claw_forge/ui_dist/` before wheel packaging. In development, served via `claw-forge ui`. Connects to the state service WebSocket for real-time updates.

**`claw-forge ui` production mode init order** (ordering matters — `state_port` must be resolved before anything that depends on it):
1. `_ensure_state_service()` — discover or start the state service, resolve final port
2. `_resolve_latest_session()` — read session from DB filtered by project path
3. Patch `index.html` with runtime JS config (port, session)
4. Build reverse proxy client (`httpx.AsyncClient`) targeting the resolved port
5. Construct Starlette app with proxy routes and static file serving

### spec/parser.py

Parses `app_spec.txt` or `app_spec.xml` (greenfield or brownfield) into a `ProjectSpec` with a list of features and dependency edges. The `initializer` plugin calls this to seed the task DAG in the state service.

The XML schema accepts two forms within a `<category>`:
- **Legacy bullets** (still supported): `- User can register` lines in the category text.
- **`<feature>` elements** with optional `index` and `depends_on` attributes:
  ```xml
  <feature index="14"><description>System displays parse errors</description></feature>
  <feature index="18" depends_on="14"><description>System displays side-by-side diff</description></feature>
  ```
  Both forms coexist within the same `<category>`. The parser resolves `depends_on` (1-based feature numbers) into 0-based positional indices that match the convention used by `_assign_dependencies` and `_write_plan_to_db`. `/create-spec` Phase 3.5 (overlap analysis) emits the `<feature>` form when the user serializes a flagged pair.

### Export (`claw_forge/exporter.py`)

`claw-forge export` reads `.claw-forge/state.db` directly via `sqlite3` (no state-service dependency, safe to run while a session is active) and emits CSV (flat or per-table), SQL dump (sqlite-importable), or JSON. Supports `--scope session|all`, `--csv-mode flat|split`, and explicit `--session UUID`. Used for stakeholder reports, spreadsheet analysis, and DB migration round-trips.

### Boundaries Harness (`claw_forge/boundaries/`)

`claw-forge boundaries audit | apply | status` identifies and refactors plugin-extension hotspots in target codebases. Two phases:

**Audit (read-only):** walker enumerates source files via `git ls-files`; signals scorer rates each on dispatch density, import centrality, recent-branch churn, and function centrality; weighted composite score ranks hotspots; classifier subagent labels each with one of four canonical patterns (`registry`, `split`, `extract_collaborators`, `route_table`); emits `boundaries_report.md`.

**Apply (modifies repo):** for each confirmed hotspot, spawns a coding subagent on its own feature branch under `.claw-forge/worktrees/`, runs the project's test command inside the worktree, and squash-merges to main on green or reverts on red. Reuses the existing `git/branching.py` + `git/merge.py` plumbing, so it inherits the merge-conflict handling, no-op detection, and worktree cleanup that `claw-forge run` ships.

Refactors run **serially** (not parallel): refactor B may depend on refactor A's output, and they share files. Use `apply --hotspot <path>` for one-at-a-time runs and `apply --auto` for fully-autonomous batch refactoring.

### Git Branch Naming (`claw_forge/git/slug.py`)

Feature branches use semantic names derived from the task's category and description:
- **Format**: `feat/{category}-{description-slug}` (e.g. `feat/auth-jwt-authentication`)
- **Verb stripping**: leading action verbs (add, implement, create, build, fix, …) are removed so branch names read as noun phrases
- **Centralized**: `make_slug()` and `make_branch_name()` replace all ad-hoc slug patterns; all call sites in `cli.py` use these functions
- **Squash merge**: each feature branch is squash-merged to main with a semantic commit message including completed steps, task-ID, and session trailers

### Git Worktree Lifecycle (`claw_forge/git/branching.py`)

Each concurrent agent gets an isolated git worktree under `.claw-forge/worktrees/`. Worktrees share the same `.git` object store (no repo duplication) — only the working-tree files are checked out separately. Cleanup is automatic via three layers:
- **Post-merge** (`merge.py`): `squash_merge()` calls `remove_worktree()` then `delete_branch()` — disk reclaimed immediately after the feature lands
- **Startup sweep** (`prune_worktrees()`): removes all directories under `.claw-forge/worktrees/` and runs `git worktree prune` — catches stale worktrees from crashed runs
- **Pre-create guard** (`create_worktree()`): if the target path already exists, it is force-removed before creating the new worktree
- **Failure preservation**: on task failure, the worktree is preserved if the branch has checkpoint commits so the retry can resume from partial work
- **Orphan scan** (`scan_orphaned_branches()`): when `merge_strategy: manual`, lists orphaned branches with committed work and shows copy-pasteable git commands for manual resolution
- **Manual cleanup** (`claw-forge worktrees [list|prune]`, `claw_forge/git/cli.py`): inspect or clean up residual worktrees outside the `claw-forge run` flow — useful for terminally-failed tasks (no further retry will land) and for completed tasks whose squash-merge itself failed, neither of which trigger the startup salvage path. `prune` salvage-merges then removes; `prune --discard` force-removes everything without salvage.
- **Smart-mode startup cleanup** (`claw_forge/git/cleanup.py`, opt-in via `git.cleanup_orphan_worktrees: smart`): walks every worktree directory at `claw-forge run` startup and dispatches preserve / salvage / remove per-slug based on the corresponding task's status in the DB. Replaces both the legacy `orphans_reset > 0` gate AND the unconditional `prune_worktrees` sweep — smart mode owns the cleanup so the unconditional sweep would otherwise nuke the worktrees it deliberately preserved. Decision matrix: `pending` + has commits → preserve (resume substrate for `prefer_resumable`); `failed` or `completed` + has commits → salvage (terminal or v0.5.35 bug class); no matching task + has commits → salvage (orphan); empty → remove. Conflicts on salvage preserve the worktree and are reported to the user.
- **LLM conflict advisor** (`claw_forge/git/conflict_advisor.py`, opt-in via `git.llm_conflict_proposals: true`): when smart-mode salvage hits a real merge conflict, drafts a `CONFLICT_PROPOSAL.md` inside the preserved worktree using `claude_agent_sdk`. Advisory only — never lands on `main`. The user reads, edits, and applies it manually. Off by default; the asymmetric cost of a wrong silent resolution outweighs the convenience.

### Periodic Auto-Checkpoint (`cli.py` task_handler)

A background `asyncio.Task` periodically commits dirty worktree files during agent execution to minimize data loss on crash:
- **Config**: `git.auto_checkpoint_interval_seconds` in `claw-forge.yaml` (default `300` = 5 minutes, `0` to disable)
- **Phase trailer**: commits use `Phase: auto-save` to distinguish from agent-initiated checkpoints
- **Best-effort**: all checkpoint commits (periodic, boundary, and completion) are best-effort — `commit_checkpoint()` catches `git commit` failures (e.g. pre-commit hooks in the target project) and returns `None` instead of crashing the task
- **Lifecycle**: started after worktree creation, cancelled in the finally block on task completion/failure/cancel

### Emergency Commit on Signals (`cli.py` + `commits.py`)

SIGTERM and SIGINT signal handlers do a best-effort `git add -A && git commit` on all active worktrees before the process exits:
- **`emergency_commit()`** (`commits.py`): synchronous, fast, catches all exceptions — safe to call from signal handlers
- **`_active_worktrees` registry**: task handler registers/deregisters worktree paths so the signal handler knows what to commit
- **Signal restoration**: original handlers are restored after the dispatcher loop completes

### Resume Context on Retry (`cli.py` task_handler)

When a task is retried after failure, the agent receives a structured resume preamble prepended to its prompt:
- **Prior work**: commit subjects from the feature branch (via `branch_commit_subjects()`)
- **Previous failure**: the `error_message` from the prior attempt (stored in the DB)
- **Handoff artifact**: contents of `HANDOFF.md` if it exists in the worktree
- **Instructions**: tells the agent not to redo completed work and to focus on fixing the prior failure

### SQLite Crash Safety

The state service uses SQLite WAL mode with multi-layer corruption defense:
- **`synchronous=FULL`**: every WAL page is fsynced before ack — crash-safe even on dirty kills
- **Lifespan teardown**: async `PRAGMA wal_checkpoint(PASSIVE)` runs on clean FastAPI shutdown
- **atexit handler**: synchronous `PRAGMA wal_checkpoint(TRUNCATE)` via plain `sqlite3` — runs on any normal Python exit (KeyboardInterrupt, SIGTERM), needs no event loop
- **SafeJSON columns**: `TypeDecorator` on all JSON columns catches `JSONDecodeError` from truncated payloads and returns a fallback value instead of crashing
- **Tiered recovery on startup**: Level 1 drops WAL/SHM files → Level 2 uses `sqlite3 .recover` → Level 3 raises actionable error
- **Graceful shutdown**: both `dev.sh` and `claw-forge ui` POST `/shutdown` before sending SIGTERM to give the lifespan teardown time to run

## Key Conventions

- **Async throughout**: pure `asyncio`, no threads. `asyncio.TaskGroup` for structured concurrency in the dispatcher.
- **No DB migrations**: state service creates tables fresh on startup (`CREATE TABLE IF NOT EXISTS`).
- **`uv run`** is always used to execute Python tools — never activate the venv manually.
- **Coverage gate**: CI enforces `fail_under = 90` (branch coverage). Adding new source files without tests will fail CI.
- **Version in `pyproject.toml`** is a static `0.0.0.dev0` placeholder — never bump it manually. The publish workflow sets the real version from the release tag.
- **`.claw-forge/state.log`** is a runtime file, gitignored. Do not commit it.
- **Default state port is `8420`** — configurable via `--port` flag or `state.port` in `claw-forge.yaml`.
- **Merge-gating** (`merged_to_target_branch` flag on tasks): a dependent task is unblocked only when its parent is `status=completed AND merged_to_target_branch=True`. The dispatcher PATCHes `merged_to_target_branch=False` when starting a task on a feature branch with `merge_strategy: auto`, and back to `True` after a successful squash. If the squash fails, the task stays "completed but not merged" and its descendants stay blocked until a manual merge or retry resolves the conflict — preventing dependents from running against a stale target branch (defaults to `main`, configurable via `git.target_branch`).
- **File-claim locks** (`touches_files` on tasks): a task may declare a list of files it intends to edit. Before starting an agent, the dispatcher POSTs a claim to `/file-claims`; if any file is held by another running task, the dispatcher defers this task to the next dispatch cycle. Claims auto-release on task transition to `completed`/`failed`/`paused`. Tasks that don't declare `touches_files` participate in no locking — full backward compatibility.
- **Resume preference** (`git.prefer_resumable: true`, default on): the scheduler prefers pending tasks whose feature branch already has committed work over fresh pending tasks within the same priority tier. Priority still dominates — a higher-priority task always wins — but a tied-priority resumable task is dispatched first so the agent picks up where the previous run left off rather than starting from scratch. A staleness gate (`git.resume_stale_threshold: 50`) skips the preference when `target_branch` has moved more than N commits ahead of the feature branch, on the assumption that catching up that much will likely conflict.
