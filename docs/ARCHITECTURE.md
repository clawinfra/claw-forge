# Architecture — claw-forge

## Overview

claw-forge is an autonomous multi-agent coding orchestrator. It decomposes project specs into a dependency DAG of tasks, dispatches them to parallel Claude agents (via claude CLI or API pool), manages git worktrees per task, and merges results. The key design decision is phase separation: planning (spec decomposition) is done by a dedicated initializer plugin, while coding/testing/review run as separate agent instances.

## Directory Structure

```
  claw_forge/           # Core library — CLI, orchestrator, agents, plugins, pool
    cli.py              # Typer CLI entry point — run, plan, add, fix, init
    orchestrator/       # Dispatcher + pool runner + reviewer
    agent/              # Claude agent SDK wrappers — session, hooks, permissions
    plugins/            # Task plugins — initializer, coding, testing, reviewer, bugfix
    pool/               # Multi-provider model pool — resolver, router, health, tracker
    state/              # SQLite + FastAPI state service — task lifecycle, manifest
    git/                # Git operations — branching, worktrees, merge, commits
    harness/            # Anthropic harness — handoff, context reset, pivot, adversarial eval
    github/             # GitHub integration — issue client, PR reporter
    spec/               # Spec parser (feature decomposition)
    mcp/                # MCP (Model Context Protocol) server
  docs/                 # Architecture, quality, conventions, plans
  scripts/              # Agent lint, dev server, eval harness
  skills/               # Agent skills (pyright, git-workflow, etc.)
  tests/                # pytest test suite (unit + e2e)
  ui/                   # React + Vite frontend (Kanban board)
```

## Layer Rules

```
CLI (cli.py, typer commands)
  → Orchestrator (dispatcher.py, pool_runner.py)
    → Agent (session.py, hooks.py, runner.py)
      → Plugins (initializer, coding, testing, reviewer, bugfix)
    → Pool (manager.py, router.py, providers/*)
  → State Service (service.py, backend.py, models.py)
  → Git Ops (branching.py, merge.py, commits.py, worktrees)

Allowed:
  cli.py         → orchestrator/, agent/, state/, git/, pool/, plugins/
  orchestrator/  → agent/, pool/, state/, git/
  agent/         → pool/ (for model resolution only)
  plugins/       → (stateless — receive context, return results)
  pool/          → providers/ (internal only)
  state/         → (self-contained — SQLite + FastAPI, no upward deps)
  git/           → (self-contained — subprocess git calls only)

FORBIDDEN:
  state/     → cli.py, orchestrator/, agent/
  git/       → cli.py, orchestrator/, agent/
  plugins/   → state/, git/ (plugins are pure logic)
  pool/      → orchestrator/, cli.py
```

## Key Packages

| Package | Responsibility |
|---------|---------------|
| `claw_forge/cli.py` | Typer CLI — `run`, `plan`, `add`, `fix`, `init` commands; config loading; model resolution |
| `claw_forge/orchestrator/` | Task dispatcher (dependency-aware DAG execution), pool runner (parallel agent management), reviewer |
| `claw_forge/agent/` | Claude agent SDK integration — session lifecycle, hooks (edit mode, loop detection, verify-on-exit), permissions, rate limiting |
| `claw_forge/plugins/` | Task-type plugins: `initializer` (spec decomposition/planning), `coding`, `testing`, `reviewer`, `bugfix` |
| `claw_forge/pool/` | Multi-provider model pool — provider registry (Anthropic, OAuth, Azure, Bedrock, Vertex, Ollama, OpenAI-compat), model resolver (aliases), health checks, usage tracker |
| `claw_forge/state/` | SQLite-backed state service (FastAPI) — task CRUD, manifest tracking, scheduler (DAG topological sort) |
| `claw_forge/git/` | Git operations — worktree creation/cleanup, branch management, merge strategies, commit helpers |
| `claw_forge/harness/` | Anthropic harness patterns — handoff artifacts, context resets, adversarial evaluator, pivot decisions |
| `claw_forge/github/` | GitHub integration — issue fetching, progress comments, draft PR creation |
| `tests/` | pytest suite — unit tests per module, e2e tests for CLI/backend/pool/UI |

## Dependency Injection

- **Config:** YAML-based (`claw-forge.yaml`), loaded via `_load_config()` in `cli.py`. Environment variable substitution (`${VAR:-default}`) handled at load time.
- **Provider pool:** Constructed from config `providers:` section. Each provider implements `BaseProvider` (abstract class in `pool/providers/base.py`). Registry pattern in `pool/providers/registry.py`.
- **State service:** Started as an in-process FastAPI server on a random port. Agents communicate via HTTP to `localhost:{port}`. No direct imports — fully decoupled.
- **Agent hooks:** Constructed via `get_default_hooks()` factory, parameterised by edit_mode, loop detection threshold, verify-on-exit, etc.

## Key Invariants

1. **State service is the single source of truth** for task lifecycle. All status transitions (pending → running → done/failed) go through HTTP PATCH to the state service.
2. **One worktree per task.** Git worktrees are created per-task for isolation. Orphaned worktrees are salvaged on resume (commits preserved, not discarded).
3. **Plugins are stateless.** They receive task context and return results. No side-channel state.
4. **Model resolution is centralised** in `pool/model_resolver.py`. CLI flags, config aliases, and provider hints all flow through `resolve_model()`.
5. **The initializer plugin is the planning phase.** It decomposes specs into task DAGs. All other plugins execute tasks from that DAG.
6. **Pool fallback order:** CLI `--model` → config `agent.default_model` → hardcoded `claude-sonnet-4-6`.

---

*Filled from scaffold template. Reflects actual claw-forge architecture as of 2026-03-28.*
