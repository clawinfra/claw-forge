# 🔥 claw-forge

**Autonomous coding agent harness for serious Python projects.**

Multi-provider API rotation · Claude Agent SDK core · 18 pre-installed skills · Pure asyncio · Zero Node.js

[![CI](https://github.com/clawinfra/claw-forge/actions/workflows/ci.yml/badge.svg)](https://github.com/clawinfra/claw-forge/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/claw-forge)](https://pypi.org/project/claw-forge/)
[![Python](https://img.shields.io/pypi/pyversions/claw-forge)](https://pypi.org/project/claw-forge/)
[![Tests](https://img.shields.io/badge/tests-2029%20passing-brightgreen)](https://github.com/clawinfra/claw-forge/actions)
[![Coverage](https://img.shields.io/badge/coverage-%E2%89%A590%25-brightgreen)](https://github.com/clawinfra/claw-forge/actions)
[![Mypy](https://img.shields.io/badge/mypy-clean-brightgreen)](https://github.com/clawinfra/claw-forge/actions)
[![ClawHub](https://img.shields.io/badge/clawhub-claw--forge--cli-blue)](https://clawhub.com/skills/claw-forge-cli)
[![Benchmark](https://img.shields.io/badge/claw--forge--bench-Config%20E%20100%25-gold)](https://github.com/clawinfra/claw-forge-bench)

---

## What it does

claw-forge runs autonomous coding agents that implement features, fix bugs, write tests, and review code — in parallel, across multiple AI providers, with live progress tracked in a Kanban UI.

It is built on the [Claude Agent SDK](https://pypi.org/project/claude-agent-sdk/) as its execution engine, with a provider pool layer on top for API key rotation, circuit breaking, and cost tracking.

---

## Quick Start

```bash
# 1. Install
pip install --pre claw-forge   # or: uv tool install claw-forge --prerelease allow

# 2. Bootstrap your project (scaffolds .claude/, CLAUDE.md, config, and app_spec.example.xml)
mkdir my-api && cd my-api
claw-forge init
# Output:
# ✓ Created claw-forge.yaml   (edit providers/API keys)
# ✓ Created .env.example      (copy to .env and fill keys)
# ✓ Created .claude/ with settings.json
# ✓ Created app_spec.example.xml  (XML format reference)
# ✓ Scaffolded 8 slash commands → .claude/commands/

# 3. Add your API key
cp .env.example .env
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env

# 4. Create your spec — two options:
#   Option A: Open Claude Code in this dir and run /create-spec
#   Option B: Paste your PRD into Claude with this prompt:
#     "Convert this PRD to claw-forge XML. Use app_spec.example.xml as the template.
#      Write the result to app_spec.txt."

# 5. Parse spec → feature DAG (uses Opus for accurate planning)
claw-forge plan app_spec.txt
# Output:
# ✅ Spec parsed: my-api
# ┌──────────────────────┬───────┐
# │ Authentication       │    8  │
# │ Task Management      │   22  │
# │ Total                │   30  │
# └──────────────────────┴───────┘
# Dependency waves: 3
# Estimated run time: ~12 minutes (at concurrency=5)
# Next: claw-forge run --concurrency 5

# 6. Run agents
claw-forge run --concurrency 5

# 7. Open the Kanban board
claw-forge ui
```

---

---

## Writing a Project Spec

The spec is the single input that drives everything. The initializer agent reads it, breaks it
into atomic tasks, infers dependencies, and creates an execution plan. **The quality of your
spec directly determines the quality of what gets built.**

claw-forge supports **two spec formats**:

| Format | When to use | Command |
|--------|-------------|---------|
| Plain text (`app_spec.txt`) | Quick greenfield projects | `claw-forge plan app_spec.txt` |
| XML (`app_spec.xml`) | Richer greenfield specs with phases, DB schema, API summary | `claw-forge plan app_spec.xml` |
| Brownfield XML (`additions_spec.xml`) | Adding features to an existing codebase | `claw-forge add --spec additions_spec.xml` |

The `/create-spec` slash command generates whichever format is appropriate — it **auto-detects**
whether you're in a greenfield or brownfield project and runs the matching conversational flow.

### 4 ways to create a spec

**Option 1 — Write it yourself** (best control)

```
Project: my-api
Stack:   Python 3.12, FastAPI, SQLAlchemy, pytest

Description:
  A REST API for managing tasks with JWT auth, tag filtering, and reminders.

Features:

1. User authentication
   Description: JWT-based register/login/logout using bcrypt.
     Access tokens expire in 1h, refresh tokens in 7d.
   Acceptance criteria:
   - POST /auth/register creates user, returns 201 with user_id
   - POST /auth/login returns {access_token, refresh_token, expires_in}
   - POST /auth/refresh exchanges refresh_token for new access_token
   - POST /auth/logout invalidates the refresh token
   - Passwords hashed with bcrypt (cost factor 12)
   - 15 unit tests, all passing
   Tech notes: Use python-jose for JWT, passlib for bcrypt.

2. Task CRUD
   Description: Full CRUD for tasks with title, description, status
     (todo/in_progress/done), priority (1–5), due_date, and tags.
   Acceptance criteria:
   - POST /tasks — create, returns 201
   - GET /tasks  — list with pagination (?page=1&per_page=20)
   - PATCH /tasks/{id} — partial update
   - DELETE /tasks/{id} — soft delete (sets deleted_at)
   - All endpoints require valid JWT (401 if missing)
   - Users can only access their own tasks (403 otherwise)
   Depends on: 1

3. Integration test suite
   Description: End-to-end API tests using pytest + httpx AsyncClient.
     Runs against in-memory SQLite — no external dependencies.
   Acceptance criteria:
   - Coverage ≥ 90% across all modules
   - Tests cover auth flow, CRUD, and error cases
   - All tests pass: pytest tests/ -v
   Depends on: 1, 2
```

**Option 2 — XML spec** (recommended for complex projects)

XML gives you richer structure: implementation phases, DB schema, API endpoint summary, design
system, and success criteria. The parser generates 100–400 granular features automatically.

```xml
<!-- app_spec.xml -->
<project_specification>
  <project_name>my-api</project_name>
  <overview>A REST API for task management with JWT auth.</overview>
  <technology_stack>Python 3.12, FastAPI, SQLAlchemy, PostgreSQL, pytest</technology_stack>

  <core_features>
    User can register with email and password
    System validates email format and enforces password strength
    User can log in and receive JWT access + refresh tokens
    User can create tasks with title, description, status, and priority
    User can list their tasks with pagination
  </core_features>

  <database_schema>
    Users: id, email, password_hash, created_at
    Tasks: id, owner_id, title, description, status, priority, created_at
  </database_schema>

  <implementation_steps>
    <phase name="Auth">User registration, login, JWT tokens</phase>
    <phase name="Tasks">Task CRUD endpoints</phase>
    <phase name="Tests">Integration test suite, coverage ≥ 90%</phase>
  </implementation_steps>

  <success_criteria>
    All endpoints tested, coverage ≥ 90%, ruff + mypy clean
  </success_criteria>
</project_specification>
```

```bash
claw-forge plan app_spec.xml
```

Use `app_spec.example.xml` as your starting point — `claw-forge init` copies it into your project automatically.

**Option 3 — Brownfield XML spec** (adding features to an existing project)

When you want to add a set of related features to an existing codebase, use
`additions_spec.xml`. The `mode="brownfield"` attribute tells claw-forge to load
`brownfield_manifest.json` and inject existing conventions into agent context.

```xml
<!-- additions_spec.xml -->
<project_specification mode="brownfield">
  <project_name>my-api — Stripe Integration</project_name>
  <addition_summary>Add Stripe payment processing to the existing FastAPI app.</addition_summary>

  <existing_context>
    <!-- Auto-populated by /create-spec when brownfield_manifest.json exists -->
    <stack>Python / FastAPI / PostgreSQL</stack>
    <test_baseline>47 tests passing, 87% coverage</test_baseline>
    <conventions>snake_case, async handlers, pydantic v2 models</conventions>
  </existing_context>

  <features_to_add>
    User can add a payment method via Stripe Elements
    System charges stored payment method on subscription creation
    Admin can issue refunds from the dashboard
  </features_to_add>

  <integration_points>
    Extends User model with stripe_customer_id field
    Adds /payments router alongside existing /auth and /tasks routers
  </integration_points>

  <constraints>
    Must not modify existing auth flow
    All 47 existing tests must stay green
    Follow existing async handler pattern in routers/
  </constraints>

  <implementation_steps>
    <phase name="Stripe Setup">Stripe client, webhook handler, config</phase>
    <phase name="Payment Methods">Add/remove cards, default card</phase>
    <phase name="Subscriptions">Create, cancel, webhook events</phase>
  </implementation_steps>
</project_specification>
```

```bash
claw-forge add --spec additions_spec.xml
```

Use `skills/app_spec.brownfield.template.xml` as a starting point.

**Option 4 — Interactive with `/create-spec`** (easiest)

Open Claude Code in your project directory and type `/create-spec`. It **auto-detects** the
mode:

- **No `brownfield_manifest.json`** → greenfield flow: walks through project name, stack, features,
  DB schema, API endpoints — outputs `app_spec.xml` + `claw-forge.yaml`
- **`brownfield_manifest.json` exists** → brownfield flow: pre-populates `<existing_context>`
  from the manifest, asks what to add and what constraints apply — outputs `additions_spec.xml`

```bash
# In Claude Code (greenfield — new project):
/create-spec

# In Claude Code (brownfield — after claw-forge analyze):
claw-forge analyze     # generates brownfield_manifest.json first
/create-spec           # detects manifest → runs brownfield flow automatically
```

**Option 5 — From an existing doc**

Paste a PRD, Notion export, or detailed README into Claude and ask:

> "Convert this into a claw-forge `app_spec.txt`. Break each requirement into a concrete feature with acceptance criteria and `Depends on:` links."

### Spec format reference

**Plain text fields:**

| Field | Required | Description |
|---|---|---|
| `Project:` | ✅ | Project name |
| `Stack:` | ✅ | Languages, frameworks, databases |
| `Description:` | optional | One paragraph overview |
| `Features:` | ✅ | List of numbered features |
| `Acceptance criteria:` | ✅ | Bullet list — each item is a verifiable condition |
| `Depends on:` | optional | Comma-separated feature numbers |
| `Tech notes:` | optional | Library preferences, patterns, constraints |

**XML elements (greenfield `app_spec.xml`):**

| Element | Required | Description |
|---|---|---|
| `<project_name>` | ✅ | Project name |
| `<overview>` | ✅ | One paragraph summary |
| `<technology_stack>` | ✅ | Languages, frameworks, databases |
| `<core_features>` | ✅ | One feature per line, action-verb format |
| `<database_schema>` | optional | Table definitions |
| `<api_endpoints_summary>` | optional | Route list |
| `<ui_layout>` | optional | Page/component structure |
| `<implementation_steps>` | optional | `<phase name="...">` blocks — features grouped by phase |
| `<success_criteria>` | optional | Done conditions |

**XML elements (brownfield `additions_spec.xml`, `mode="brownfield"`):**

| Element | Required | Description |
|---|---|---|
| `<project_name>` | ✅ | Project + addition name |
| `<addition_summary>` | ✅ | What you're adding and why |
| `<existing_context>` | optional | `<stack>`, `<test_baseline>`, `<conventions>` — auto-populated by `/create-spec` |
| `<features_to_add>` | ✅ | One feature per line (same format as `<core_features>`) |
| `<integration_points>` | optional | Where new code hooks into existing code |
| `<constraints>` | optional | What must NOT change |
| `<implementation_steps>` | optional | `<phase name="...">` blocks |

### Tips for a good spec

- **One feature = one atomic unit of work.** If it would take >2 hours to implement, split it.
- **Acceptance criteria are tests.** Write them as if the agent must tick each one before marking done.
- **Use `Depends on:` for real hard dependencies.** Features with no dependencies run in parallel in Wave 1.
- **Start with 5–10 features.** Add more with `/expand-project` once the first wave is running.
- **Be specific about libraries.** "Use python-jose for JWT" beats "implement JWT".
- **Include test count targets.** "15 unit tests" gives the agent a concrete goal.

### Adding features to a running project

`claw-forge plan` **reconciles by default** — it matches spec features against existing tasks by description, keeps completed/pending/failed tasks untouched, and only inserts new features as pending tasks. Dependencies are wired correctly across old and new tasks.

```bash
# Option A — /expand-project slash command in Claude Code
/expand-project
# Claude lists current features, asks what to add, POSTs them atomically

# Option B — edit spec and re-plan (only new features are added)
echo "
4. Email reminders
   Description: Send due-date reminders 24h before via SendGrid.
   Acceptance criteria:
   - Celery task runs hourly, finds tasks due in next 24h
   - Sends email via SendGrid with task title and due date
   - Emails only sent once per task per due date
   Depends on: 2
" >> app_spec.txt
claw-forge plan app_spec.txt --project my-api
# Output:
# Reconciled with existing session:
#   3 completed  (kept)
#   1 new        (added)

# Use --fresh to ignore existing state and start from scratch
claw-forge plan app_spec.txt --project my-api --fresh
```

---

## Provider Pool

Never hit a rate limit again. Configure multiple providers with automatic failover:

```yaml
# claw-forge.yaml
providers:
  # Use your `claude login` token — no API key needed
  claude-oauth:
    type: anthropic_oauth
    priority: 1

  # Direct API key as primary fallback
  anthropic-primary:
    type: anthropic
    api_key: ${ANTHROPIC_KEY_1}
    priority: 2

  # Second API key for burst capacity
  anthropic-secondary:
    type: anthropic
    api_key: ${ANTHROPIC_KEY_2}
    priority: 2

  # Cloud providers for enterprise scale
  aws-bedrock:
    type: bedrock
    region: us-east-1
    priority: 3

  azure-ai:
    type: azure
    endpoint: https://my-resource.openai.azure.com
    api_key: ${AZURE_KEY}
    priority: 4

  # Free-tier providers for lightweight tasks
  groq-free:
    type: openai_compat
    base_url: https://api.groq.com/openai/v1
    api_key: ${GROQ_KEY}
    priority: 5

  # Local model via Ollama
  local-ollama:
    type: ollama
    base_url: http://localhost:11434
    model: qwen2.5-coder
    priority: 6
```

The pool automatically:
- Routes requests through providers in priority order
- Backs off per-provider when rate limited (parses `Retry-After` headers)
- Opens per-provider circuit breakers on persistent failures
- Tracks cost, latency, and RPM per provider
- Falls through the entire chain before giving up

**5 routing strategies:** `priority` (default) · `round_robin` · `weighted_random` · `least_cost` · `least_latency`

---

## Supported Providers

| Provider | Type | Auth |
|---|---|---|
| Anthropic direct | `anthropic` | API key |
| Claude OAuth | `anthropic_oauth` | Auto-reads `~/.claude/.credentials.json` |
| Anthropic-format proxy | `anthropic_compat` | `x-api-key` or none (internal proxies) |
| AWS Bedrock | `bedrock` | IAM / instance role |
| Azure AI Foundry | `azure` | API key |
| Google Vertex AI | `vertex` | Application Default Credentials |
| Groq / Cerebras | `openai_compat` | API key |
| Any OpenAI-compat endpoint | `openai_compat` | Optional API key |
| Ollama (local) | `ollama` | Optional (usually none) |

---

## Agent Runtime

claw-forge uses the Claude Agent SDK for all agent execution. The SDK handles the tool-use loop, MCP server connections, permission hooks, streaming — claw-forge adds the orchestration, state management, and provider rotation layer on top.

### Bidirectional sessions

```python
from pathlib import Path
from claw_forge.agent import AgentSession
from claw_forge.agent.thinking import thinking_for_task
from claw_forge.agent.output import CODE_REVIEW_SCHEMA
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage

options = ClaudeAgentOptions(
    model="claude-sonnet-4-6",
    cwd=Path("./my-project"),
    thinking=thinking_for_task("coding"),      # adaptive by default
    max_budget_usd=1.00,                        # hard cost cap
    betas=["context-1m-2025-08-07"],            # 1M token context
)

async with AgentSession(options) as session:
    # Primary task
    async for msg in session.run("Implement the OAuth2 login flow"):
        handle_message(msg)

    # Tests failed — guide without restarting the session
    async for msg in session.follow_up("Focus on fixing test_auth.py first"):
        handle_message(msg)

    # Refactor went wrong — rewind files to before the last step
    await session.rewind(steps_back=1)

    # Escalate to Opus for the hard security review
    await session.switch_model("claude-opus-4-6")
```

### One-shot queries

```python
from claw_forge.agent import collect_result, collect_structured_result

# Simple text result
result = await collect_result(
    "Write unit tests for src/auth.py",
    cwd=Path("./my-project"),
    agent_type="testing",   # gets correct tool list + max_turns
)

# Structured JSON output (schema enforced)
review = await collect_structured_result(
    "Review the PR diff for security issues",
    cwd=Path("./my-project"),
    agent_type="reviewer",
    output_format=CODE_REVIEW_SCHEMA,
)
# review = {"verdict": "request_changes", "blockers": [...], "security_issues": [...]}
```

### Provider pool + agent

```python
from claw_forge.pool import ProviderPoolManager
from claw_forge.agent import collect_result

pool = ProviderPoolManager.from_config("claw-forge.yaml")
provider = await pool.acquire("claude-sonnet-4-6")

result = await collect_result(
    "Fix the failing integration tests",
    cwd=Path("./project"),
    provider_config=provider,  # routes through pool with failover
)
```

---

## Advanced SDK Features

claw-forge exposes all 20 Claude Agent SDK APIs. See [`docs/sdk-api-guide.md`](docs/sdk-api-guide.md) for detailed examples. Highlights:

| Feature | API | Use case |
|---|---|---|
| File undo | `enable_file_checkpointing` + `rewind_files()` | Roll back bad refactors |
| Cost cap | `max_budget_usd` | Hard limit per session |
| Structured output | `output_format` schema | Typed review verdicts |
| Thinking depth | `ThinkingConfig` | Deep for planning, off for monitoring |
| Named sub-agents | `AgentDefinition` | Planner / Coder / Reviewer roles |
| OS sandbox | `SandboxSettings` | Filesystem + network isolation |
| Model fallback | `fallback_model` | Auto-retry on model error |

---

## Security

Three-layer defence:

1. **`CanUseTool` callback** — Python function runs before every tool; blocks dangerous commands, restricts writes to project directory, can mutate tool inputs
2. **Bash security hook** — hardcoded blocklist (`sudo`, `dd`, `shutdown`, ...) + per-project `allowed_commands.yaml`
3. **`SandboxSettings`** — OS-level bash isolation on macOS/Linux (optional)

Agent lock file (`.claw-forge.lock`) prevents two agents running on the same project simultaneously.

---

## Commands

### CLI Commands

| Command | Description | Key flags |
|---------|-------------|-----------|
| `claw-forge init` | Bootstrap project — scaffold `.claude/`, config, `app_spec.example.xml` | `--project`, `--config` |
| `claw-forge plan` | Parse spec → feature DAG in state DB (reconciles with existing session by default) | `spec` (positional), `--model`, `--concurrency`, `--fresh` |
| `claw-forge run` | Start agent pool, dispatch features in parallel | `--concurrency`, `--model`, `--yolo`, `--edit-mode`, `--loop-detect-threshold`, `--verify-on-exit` |
| `claw-forge add` | Add features to existing project (single or brownfield spec) | `--spec`, `--branch/--no-branch` |
| `claw-forge fix` | TDD bug-fix: write failing test → fix → regression suite | `--report`, `--branch/--no-branch` |
| `claw-forge status` | Project progress, phase bars, active agents, next action | `--config` |
| `claw-forge analyze` | Scan codebase → `brownfield_manifest.json` (stack, tests, conventions) | `--project` |
| `claw-forge ui` | Launch real-time Kanban board (React + WebSocket) | `--port`, `--session`, `--dev` |
| `claw-forge dev` | Start API (hot-reload) + UI (Vite HMR) for local development; add `--run` to also launch the agent orchestrator | `--state-port`, `--ui-port`, `--project`, `--run` |
| `claw-forge pool-status` | Provider health table (status, RPM, latency, cost) | `--config` |
| `claw-forge pause` | Drain mode — finish in-flight agents, start no new ones | — |
| `claw-forge resume` | Resume a paused project | — |
| `claw-forge input` | Answer human-input questions from blocked agents | — |
| `claw-forge state` | Start the state service REST API (port 8420) | `--port`, `--host`, `--reload` |

### Slash Commands (Claude Code)

| Command | When to use | What it produces |
|---------|-------------|-----------------|
| `/create-spec` | Starting a new project or adding features | `app_spec.txt` or `additions_spec.xml` |
| `/expand-project` | Adding features mid-sprint | New tasks in state DB |
| `/check-code` | Pre-PR quality gate | Ruff + mypy + pytest report |
| `/checkpoint` | Saving progress at a known-good state | Git commit + JSON snapshot + CHECKPOINT.md |
| `/review-pr` | Code review before merge | Structured verdict (APPROVE / REQUEST CHANGES) |
| `/pool-status` | Diagnosing slow agents or cost spikes | Provider health + recommendations |
| `/create-bug-report` | Structured bug reporting before fix | `bug_report.md` → auto-runs `claw-forge fix` |
| `/claw-forge-status` | Re-entry after leaving a session | Full project status card |

> 📚 Full details: [`docs/commands.md`](docs/commands.md) · End-to-end workflows: [`docs/workflows.md`](docs/workflows.md)

---

## Quick Workflow Cheatsheet

**New project:**
```
claw-forge init → /create-spec → claw-forge plan → claw-forge run
```

**Add features to existing app:**
```
claw-forge analyze → /create-spec → claw-forge add → claw-forge run
```

**Fix a bug:**
```
/create-bug-report → claw-forge fix
```

**Check health:**
```
claw-forge status → /pool-status → /check-code
```

**Save progress:**
```
/checkpoint → /review-pr → git push
```

---

## Workflow Features

| Feature | Command / Flag |
|---|---|
| YOLO mode | `claw-forge run my-app --yolo` |
| Fix a bug (one-liner) | `claw-forge fix "description"` |
| Fix a bug from report | `claw-forge fix --report report.md` |
| Pause (drain) | `claw-forge pause my-app` |
| Resume | `claw-forge resume my-app` |
| Human input | `claw-forge input my-app "Here's the API key"` |
| Project status | `claw-forge status` |
| Batch features | `--batch-size 3` |
| Specific features | `--batch-features 1,2,3` |
| Pool health | `claw-forge pool-status` |

---

## Kanban UI

Real-time board tracking feature progress across all agents. Cards flow across five columns as agents work — with live provider health, cost tracking, and regression status in the header.

![claw-forge Kanban board — light mode with 18 features across Pending, In Progress, Passing, Failed, and Blocked columns](website/assets/screenshots/kanban-overview.png)

### Dark mode

![claw-forge Kanban board — dark mode](website/assets/screenshots/kanban-dark.png)

```bash
claw-forge dev               # API (:8420, hot-reload) + UI (:5173, HMR) in one command
# or separately:
claw-forge state --reload &  # start REST + WebSocket server on :8420 with hot-reload
claw-forge ui --dev          # http://localhost:5173/?session=<uuid>
```

**Columns:** Pending · In Progress · Passing · Failed · Blocked

**Header:** provider health dots (green/yellow/red per provider) · progress bar (X/Y passing) · live agent count · cost sparkline · regression health bar

**Real-time:** WebSocket pushes feature status changes, agent streaming logs, provider health, and cost updates. Drag-and-drop cards to retry failed tasks.

---

## Claude Commands

Seven slash commands in `.claude/commands/` for use inside Claude Code. Automatically scaffolded by `claw-forge init`. See [`docs/commands.md`](docs/commands.md) for full reference with real-world examples, and [`docs/workflows.md`](docs/workflows.md) for end-to-end walkthroughs.

| Command | Purpose | Key flags | When to use |
|---|---|---|---|
| `/create-spec` | Interactive spec creation — auto-detects greenfield vs brownfield, outputs XML | `--brownfield`, `--output` | Starting a new project or adding features |
| `/expand-project` | Add features to an existing project | `--append` | Mid-run when you think of more features |
| `/check-code` | Run ruff + mypy + pytest and report | `--fix`, `--strict` | After agent completes a batch of features |
| `/checkpoint` | Commit + DB snapshot + session summary | `--message` | Before stepping away or at phase boundaries |
| `/review-pr` | Structured PR review with verdict | `--strict` | Before merging any agent-generated branch |
| `/pool-status` | Provider health and cost analysis | `--watch` | When you suspect rate limits or cost spikes |
| `/claw-forge-status` | Project progress, phase bars, agent state, next action | — | Quick health check at any time |
| `/create-bug-report` | Guided 6-phase bug report creation → runs fix | `--tdd` | When a bug is reported and you need a proper fix |

Four agent definitions in `.claude/agents/`:

| Agent | Model | Purpose |
|---|---|---|
| `coding` | sonnet | Implement features, TDD-first |
| `testing` | sonnet | Run regression tests, report failures |
| `reviewing` | opus | Code review with blocking/suggestion/approve verdict |
| `initializer` | sonnet | Parse spec, create feature DAG |

---

## Quick Workflow Cheatsheet

| Goal | Command chain |
|------|--------------|
| **New project** | `claw-forge init` → `/create-spec` → `claw-forge plan` → `claw-forge run` |
| **Add features to existing app** | `claw-forge analyze` → `/create-spec` → `claw-forge add` |
| **Fix a bug (TDD)** | `/create-bug-report` → `claw-forge fix` → `/review-pr` |
| **Quality check** | `/check-code` → `/review-pr` |
| **Save progress** | `/checkpoint` → `git push` |
| **Monitor providers** | `/pool-status` |
| **Resume after crash** | `claw-forge status` → `claw-forge run` |

📖 Full workflow guides: [docs/workflows.md](docs/workflows.md)
📖 Command reference: [docs/commands.md](docs/commands.md)

---

## Pre-installed Skills (18) + Templates

Skills are auto-injected into agent sessions via three layers:

1. **LSP by file extension** — `detect_lsp_plugins()` scans the project directory and injects the right language server based on file types found (`.py` → pyright, `.ts` → typescript-lsp, `.go` → gopls, etc.)
2. **Agent type** — `skills_for_agent()` injects role-appropriate skills (e.g. coding agents get `systematic-debug` + `verification-gate`, reviewers get `code-review` + `security-audit`)
3. **Task keywords** — same function scans the task description for keywords (`"database"` → database skill, `"docker"` → docker skill, `"security"` → security-audit, etc.)

All injection is controlled by `auto_inject_skills=True` on `run_agent()` / `auto_detect_lsp=True`.

**LSP servers (6):** pyright · gopls · rust-analyzer · typescript-lsp · clangd · solidity-lsp

**Process skills (6):** systematic-debug · verification-gate · parallel-dispatch · test-driven · code-review · web-research

**Integration skills (6):** git-workflow · api-client · docker · security-audit · performance · database

**Templates:** `skills/bug_report.template.md` — structured bug report template for use with `claw-forge fix --report`

---

## Brownfield Projects

claw-forge works on **existing codebases** — not just greenfield projects. The brownfield workflow analyzes your project, learns its conventions, and adds features or fixes bugs without breaking existing patterns.

```bash
# 1. Analyze your project (creates brownfield_manifest.json)
claw-forge analyze

# 2. Add a feature
claw-forge add "Add rate limiting to all API endpoints"

# 3. Fix a bug
claw-forge fix "Login fails when email contains uppercase letters"
```

The analyzer detects your stack, parses git history for hot files, establishes a test baseline, and writes `brownfield_manifest.json`. Subsequent `add`/`fix` runs load this manifest to match your existing conventions.

### Fixing bugs

**Quick fix** (one-liner):
```bash
claw-forge fix "users get 500 when uploading files > 5MB"
```

**Structured fix** (recommended for complex bugs):
```bash
# Generate a structured bug report interactively
/create-bug-report

# Or copy the template and fill it in
cp skills/bug_report.template.md bug_report.md
# edit bug_report.md...

# Run the fix
claw-forge fix --report bug_report.md
```

The bug-fix agent follows a strict **RED → GREEN** protocol:
1. Writes a failing regression test first (RED)
2. Locates root cause using systematic-debug skill
3. Makes surgical fix — touches only what's needed
4. Confirms regression test passes (GREEN)
5. Runs full test suite — must be 100% green
6. Commits with `fix: <title>\n\nRegression test: <test_name>`

> **Status:** `analyze`, `add`, and `fix` commands are planned — see [`docs/brownfield.md`](docs/brownfield.md) for the full design.

---

## Plugin System

Extend claw-forge with custom agent types via Python entry points — no fork required:

Built-in plugins (registered in `pyproject.toml`):

| Entry point | Plugin | Purpose |
|---|---|---|
| `initializer` | `InitializerPlugin` | Parse spec, create feature DAG |
| `coding` | `CodingPlugin` | TDD-first feature implementation |
| `testing` | `TestingPlugin` | Run regression tests, report failures |
| `reviewer` | `ReviewerPlugin` | Structured code review with verdict |
| `bugfix` | `BugFixPlugin` | Reproduce-first bug fix: RED→GREEN protocol |

Add your own:

```toml
# your-package/pyproject.toml
[project.entry-points."claw_forge.plugins"]
my_agent = "my_package.plugin:MyAgentPlugin"
```

```python
from claw_forge.plugins.base import AgentPlugin, PluginContext, PluginResult

class MyAgentPlugin(AgentPlugin):
    name = "my_agent"
    description = "Does something custom"
    version = "1.0.0"

    def get_system_prompt(self, context: PluginContext) -> str:
        return "You are a specialist in ..."

    async def execute(self, context: PluginContext) -> PluginResult:
        from claw_forge.agent import collect_result
        result = await collect_result(
            self.get_system_prompt(context),
            cwd=context.project_dir,
            agent_type="coding",
        )
        return PluginResult(success=True, output=result)
```

---

## Development

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Node.js 18+ (for the Kanban UI)

### Setup

```bash
git clone https://github.com/clawinfra/claw-forge.git
cd claw-forge
uv sync --extra dev          # install Python deps (including dev tools)
npm install --prefix ui      # install UI deps
```

### Local Dev (API + UI with hot-reload)

The fastest way to develop locally — one command starts both servers with automatic reload on file changes:

```bash
claw-forge dev
```

This starts:
- **State API** on `http://localhost:8420` — uvicorn with `--reload`, restarts on any Python file change under `claw_forge/`
- **Kanban UI** on `http://localhost:5173` — Vite dev server with HMR, instant updates on React/TypeScript changes

Options:

```bash
claw-forge dev --state-port 9000    # custom API port
claw-forge dev --ui-port 3000       # custom UI port
claw-forge dev --project /path/to/app  # point at a different project directory
claw-forge dev --no-open            # don't auto-open the browser
```

Press `Ctrl+C` to stop both servers.

### Running servers separately

If you prefer separate terminals (useful for cleaner log output):

```bash
# Terminal 1 — API with hot-reload
claw-forge state --reload

# Terminal 2 — UI with Vite HMR
claw-forge ui --dev
```

The `--reload` flag on `state` enables uvicorn file watching. The `--dev` flag on `ui` runs Vite instead of serving the pre-built static bundle.

### Running Vite directly (without the CLI)

If you want to run `npm run dev` from the `ui/` directory without going through `claw-forge ui --dev`, set the proxy target port via environment variables:

```bash
cd ui
VITE_API_PORT=8420 npm run dev
```

Or create `ui/.env.local`:

```env
VITE_API_PORT=8420
VITE_WS_PORT=8420
```

### Tests & linting

```bash
uv run pytest tests/ -q                                          # full test suite
uv run pytest tests/path/to/test.py::Class::test_name -v         # single test
uv run pytest tests/ -q --cov=claw_forge --cov-report=term-missing  # with coverage (must reach 90%)
uv run ruff check claw_forge/ tests/                             # lint
uv run ruff check claw_forge/ tests/ --fix                       # auto-fix
uv run mypy claw_forge/ --ignore-missing-imports                 # type check
```

---

## Documentation

| Document | Contents |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | System design, data flow, component details |
| [`docs/commands.md`](docs/commands.md) | Full CLI command reference with options and examples |
| [`docs/workflows.md`](docs/workflows.md) | End-to-end workflow walkthroughs |
| [`docs/sdk-api-guide.md`](docs/sdk-api-guide.md) | 20 Claude Agent SDK APIs with claw-forge examples |
| [`docs/bmad-integration.md`](docs/bmad-integration.md) | Using claw-forge with BMAD Method — convert epics/stories to spec |
| [`docs/brownfield.md`](docs/brownfield.md) | Brownfield mode — analyze existing codebases, add features, fix bugs |
| [`docs/agent-skill.md`](docs/agent-skill.md) | OpenClaw agent skill — install via `clawhub install claw-forge-cli` |
| [`docs/middleware/pre-completion-checklist.md`](docs/middleware/pre-completion-checklist.md) | Design doc: PreCompletionChecklistMiddleware (issue #4) |
| [`docs/middleware/loop-detection.md`](docs/middleware/loop-detection.md) | Design doc: LoopDetectionMiddleware (issue #5) |
| [`docs/benchmarks/terminal-bench.md`](docs/benchmarks/terminal-bench.md) | Terminal Bench 2.0 evaluation harness design (issue #6) |
| [`claw-forge.yaml`](claw-forge.yaml) | Annotated configuration reference |
| [`website/tutorial.html`](website/tutorial.html) | End-to-end getting started guide |
| [`website/features.html`](website/features.html) | Full feature list |

---

---

## Harness Design Patterns

claw-forge includes advanced harness patterns inspired by Anthropic's research on long-running AI applications. These patterns improve output quality, manage context limits, and enable strategic decision-making during multi-iteration agent workflows.

### Context Resets (`--reset-threshold`)

**Problem:** Long-running agent sessions eventually hit context limits or degrade due to accumulated conversation history ("context anxiety"). The agent may prematurely wrap up work to avoid losing context.

**Solution:** After N tool calls, the builder saves a structured `HANDOFF.md` artifact and spawns a fresh builder with it as context. The new builder gets a clean slate with just the essential state.

```python
from claw_forge.harness import ContextResetManager, HandoffArtifact

# Configure: trigger reset after 80 tool calls
reset_mgr = ContextResetManager(project_dir="/path/to/project", threshold=80)

# Track progress
for task in tasks:
    result = await agent.run(task)
    if reset_mgr.record_tool_call():  # Returns True when threshold reached
        # Save handoff and spawn fresh builder
        handoff = HandoffArtifact(
            completed=["feat: auth (abc123)", "feat: database (def456)"],
            state=["src/auth.py — 150 lines", "tests/ — 85% coverage"],
            next_steps=["Add rate limiting", "Write API docs"],
            decisions_made=["Using SQLite for local dev"],
            quality_bar="6.5/10 — needs error handling",
        )
        reset_mgr.save_handoff(handoff)
        # Spawn new builder with HANDOFF.md as context
        await spawn_fresh_builder(project_dir="/path/to/project")
```

**HANDOFF.md schema:**
- `## Completed` — Items done (with commit hashes for traceability)
- `## State` — Current codebase structure, test coverage, file counts
- `## Next Steps` — Ordered action items for the next builder
- `## Decisions Made` — Architectural decisions to avoid revisiting
- `## Quality Bar` — Current evaluator score, what needs improvement

### Adversarial Review (`--adversarial-review`)

**Problem:** Agents are overly optimistic about their own work. Self-evaluation scores are inflated (average 8.5/10 even for mediocre output), and vague praise ("looks good!") provides no actionable feedback.

**Solution:** Separate the generator from the evaluator. The evaluator uses a skeptical, evidence-based rubric with weighted grading dimensions:

| Dimension | Weight | Focus |
|-----------|--------|-------|
| Correctness | ×3 | Bugs, edge cases, error handling |
| Completeness | ×3 | Missing features, unimplemented specs |
| Quality | ×2 | Maintainability, duplication, architecture |
| Originality | ×1 | Novel approaches, design choices |

```python
from claw_forge.harness import AdversarialEvaluator, GradingDimension

evaluator = AdversarialEvaluator(
    approval_threshold=7.0,
    dimensions=[
        GradingDimension.CORRECTNESS,  # ×3
        GradingDimension.COMPLETENESS,  # ×3
        GradingDimension.QUALITY,  # ×2
        GradingDimension.ORIGINALITY,  # ×1
    ],
)

# Run adversarial review (via reviewer plugin with --adversarial flag)
# The evaluator returns:
# - Per-dimension scores (1-10) with specific evidence
# - Overall weighted score
# - Verdict: APPROVE or REQUEST_CHANGES
# - Actionable findings (blocking issues, suggestions)
```

**Adversarial prompt features:**
- "Assume the code has bugs until proven otherwise"
- Requires specific evidence (file names, line numbers, test names)
- Few-shot examples calibrated to distinguish good vs. bad reviews
- Generic praise ("well done!") is explicitly discouraged

### Strategic Pivot

**Problem:** Agents can get stuck in a local optimum, iterating endlessly on an approach that isn't converging. Declining scores over multiple iterations signal that the current direction is flawed.

**Solution:** Track evaluator scores across iterations and force a strategic decision after each review cycle:

- **Score ≥ threshold (7.0)** → `APPROVE` — work meets quality bar
- **Score trending up** → `REFINE` — continue with improvements
- **Score flat, below threshold** → `REFINE` — iterate with specific changes
- **Score declining for 2+ iterations** → `PIVOT` — abandon approach, try something different

```python
from claw_forge.harness import PivotTracker, PivotAction

tracker = PivotTracker(
    forced_pivot_streak=2,  # Force PIVOT after 2 consecutive declining scores
    approval_threshold=7.0,
)

# After each evaluator cycle:
decision = tracker.decide(score=6.2, iteration=3)
if decision.action == PivotAction.PIVOT:
    logger.warning("Scores declining: 7.5 → 6.8 → 6.2. Pivoting to new approach.")
    # Log to PLAN.md for traceability
    tracker.log_to_plan("PLAN.md")
    # Agent switches strategies entirely
elif decision.action == PivotAction.REFINE:
    logger.info("Score improving or flat. Continue with evaluator feedback.")
    # Agent iterates on current approach
elif decision.action == PivotAction.APPROVE:
    logger.info("Score meets threshold. Work approved.")
    # Agent finalizes and exits
```

**Pivot log in PLAN.md:**
```markdown
## Pivot Decision Log

### Iteration 3 — PIVOT
- **Score:** 6.2/10
- **Trend:** 7.5 → 6.8 → 6.2
- **Reasoning:** Score declining for 2+ consecutive iterations (7.5 → 6.8 → 6.2). Current approach is not converging — pivot to a different strategy.
- **Time:** 2026-03-28T12:34:56Z
```

### Usage

These patterns are integrated into the reviewer and coding plugins:

```bash
# Enable adversarial review in the reviewer plugin
claw-forge run --config reviewer.yaml  # with config: {adversarial: true}

# Coding plugin automatically loads HANDOFF.md when resuming
claw-forge run  # continues from previous handoff if HANDOFF.md exists
```

See the [`claw_forge.harness`](claw_forge/harness/) module for full API documentation and [`docs/harness-patterns.md`](docs/harness-patterns.md) for detailed usage patterns.

---

## Benchmark Results

Ablation study on [claw-forge-bench](https://github.com/clawinfra/claw-forge-bench) — 30 Python coding tasks (easy / medium / hard), model: `claude-opus-4-6`.

| Config | Middleware | Pass Rate | Δ vs Baseline |
|--------|-----------|----------:|---------------|
| A — baseline | none | 96.7% | — |
| B — hashline | hashline edit mode | 96.7% | +0.0pp |
| C — loop | loop detection | 96.7% | +0.0pp |
| D — verify | verify-on-exit | 96.7% | +0.0pp |
| **E — full stack** | **hashline + loop + verify** | **100%** | **+3.3pp** |

**Finding:** Individual middleware layers show no uplift in isolation. The combination of all three reaches **100%** — an interaction effect where each layer compensates for the others' blind spots.

**Recommended production stack:**
```bash
claw-forge run --edit-mode hashline --loop-detect-threshold 5 --verify-on-exit
```

→ [Full results + methodology](docs/benchmarks/results.md) · [Benchmark repo](https://github.com/clawinfra/claw-forge-bench)

---

## OpenClaw Agent Skill

claw-forge is available as an installable **OpenClaw agent skill** on [ClawHub](https://clawhub.com/skills/claw-forge-cli).
Any AI agent running on OpenClaw can use it to run the full claw-forge workflow autonomously.

```bash
clawhub install claw-forge-cli
```

See [`docs/agent-skill.md`](docs/agent-skill.md) for details on `--edit-mode hashline`,
the middleware stack, Terminal Bench ablation numbers, and how the skill integrates with OpenClaw.

---

## Harness Design Patterns

claw-forge implements key patterns from [Anthropic's engineering research](https://www.anthropic.com/engineering/harness-design-long-running-apps) on reliable long-running agents:

### Context Resets

After N tool calls (default: 80), the Builder saves a `HANDOFF.md` artifact and spawns a fresh context. This prevents *context anxiety* — agents wrapping up prematurely because they sense context pressure:

```bash
claw-forge run --task "..." --reset-threshold 60  # reset after 60 tool calls
```

The `HANDOFF.md` schema carries exactly what the next agent needs:

```markdown
## Completed      — what's done (with evidence e.g. commit hashes)
## State          — files touched, current coverage, blockers
## Next Steps     — ordered list of what to do next
## Decisions Made — don't revisit these
## Quality Bar    — current score, what needs improvement
```

### Adversarial Evaluator

The Reviewer phase can run in adversarial mode — a skeptical evaluator with explicit adversarial framing consistently outperforms standard self-evaluation:

```bash
claw-forge run --task "..." --adversarial-review
```

Scoring uses 4 weighted dimensions: **Correctness** (×3) + **Completeness** (×3) + **Quality** (×2) + **Originality** (×1). Score ≥ 7 = approve, < 7 = request changes with specific feedback.

### Strategic Pivot

After each eval cycle, claw-forge explicitly chooses **REFINE** (iterate current approach) or **PIVOT** (start fresh with a different approach). If score trends downward 2+ consecutive iterations, a pivot is forced automatically. Pivot decisions are logged to `PLAN.md` so future iterations don't repeat failed paths.

### Python API

```python
from claw_forge.harness import HandoffArtifact, ContextResetManager, AdversarialEvaluator, PivotTracker

# Context reset management
mgr = ContextResetManager(reset_threshold=80)
mgr.record_tool_call()
if mgr.should_reset():
    artifact = mgr.create_handoff(completed=[...], next_steps=[...])
    artifact.save("HANDOFF.md")

# Adversarial evaluation
evaluator = AdversarialEvaluator(model="claude-sonnet-4-5")
result = await evaluator.evaluate(task, output)
# result.score: 0-9, result.approved: bool, result.feedback: str

# Pivot tracking
tracker = PivotTracker()
tracker.record_score(result.score)
if tracker.should_pivot():
    # start fresh with different approach
    pass
```

See [`docs/harness-patterns.md`](docs/harness-patterns.md) for full usage guide.

---

## License

Apache-2.0 · Built by [ClawInfra](https://github.com/clawinfra)

