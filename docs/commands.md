# claw-forge Commands Reference

Complete reference for all CLI commands and Claude slash commands. For end-to-end workflow
walkthroughs, see [docs/workflows.md](workflows.md). For the project README, see
[README.md](../README.md).

---

## CLI Workflow Commands

Run these in your terminal. All CLI commands accept `--config` to point at a non-default
`claw-forge.yaml`.

---

### `claw-forge init`

#### Purpose
Parses your project spec, generates a feature dependency graph (DAG), and scaffolds the
`.claude/` directory with slash commands, agent definitions, and a tailored `CLAUDE.md`.

#### When to use
- Starting a new project after writing `app_spec.txt` or running `/create-spec`
- After pulling a repo that has a spec but no `.claude/` scaffold
- Re-running after adding phases to an existing spec (only new features are created)
- When you want claw-forge to analyse your stack and auto-detect LSP plugins

#### Usage
```bash
# Basic — analyze current directory
claw-forge init

# With a spec file (parses features, builds DAG)
claw-forge init --spec app_spec.txt

# Point at a different project directory
claw-forge init --project ~/projects/task-manager --spec app_spec.txt

# Control concurrency estimate in post-parse summary
claw-forge init --spec app_spec.txt --concurrency 8
```

#### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--spec`, `-s` | path | `None` | Path to `app_spec.txt` or XML spec file |
| `--project`, `-p` | path | `.` | Root directory of the project |
| `--concurrency`, `-n` | int | `5` | Used to estimate run time in the summary |
| `--config`, `-c` | path | `claw-forge.yaml` | Path to YAML config |

#### What it does internally
1. Detects language/framework by scanning the project directory for `pyproject.toml`,
   `package.json`, `go.mod`, `Cargo.toml`, etc.
2. If `--spec` is given, runs `InitializerPlugin` which parses the XML spec into a feature list.
3. Builds a dependency DAG from `<phase>` ordering in the spec.
4. Writes `.claude/commands/` with the 7 slash-command markdown files.
5. Writes `.claude/agents/` with `coding`, `testing`, `reviewing`, and `initializer` agents.
6. Generates `CLAUDE.md` tailored to the detected stack (LSP hints, skill list, conventions).
7. Prints a feature-by-category table, wave count, and estimated run time.

#### Real-world example
You've written `app_spec.txt` for "TaskFlow API" — a FastAPI + SQLite task manager. You run:

```bash
cd ~/projects/taskflow-api
claw-forge init --spec app_spec.txt --concurrency 5
```

#### Output example
```
claw-forge v0.2.0b1
✅ Spec parsed: TaskFlow API

  Features by Category
  ┌────────────────────────┬───────┐
  │ Category               │ Count │
  ├────────────────────────┼───────┤
  │ Authentication         │    8  │
  │ Task Management        │   22  │
  │ Project Management     │   14  │
  │ Notifications          │    6  │
  │ API Layer              │    9  │
  │ Total                  │   59  │
  └────────────────────────┴───────┘

  Dependency waves: 4
  Estimated run time: ~24 minutes (at concurrency=5)

  Implementation phases (4):
    1. Core models + auth
    2. Task CRUD + project structure
    3. Notifications + integrations
    4. Polish + performance

✓ Generated CLAUDE.md (tailored to your stack)
✓ Scaffolded 7 slash commands → .claude/commands/
  • /create-spec
  • /expand-project
  • /check-code
  • /checkpoint
  • /review-pr
  • /pool-status
  • /create-bug-report
✓ Stack detected: python / fastapi

  Next: claw-forge run --spec app_spec.txt --concurrency 5
```

#### Pro tips
- Run `claw-forge init` without `--spec` on an existing codebase first — it detects your stack
  and scaffolds commands even before you write a spec.
- The estimated run time assumes ~2 min per feature. Add more providers to halve that.
- Re-running `init` on an existing project is safe — it won't duplicate features already in the
  state DB.

#### Related commands
- **Before:** `/create-spec` (generate the spec interactively)
- **After:** `claw-forge run` (start the agents)

---

### `claw-forge run`

#### Purpose
Starts the agent pool, dispatches features from the state DB to coding agents in parallel, and
drives the full implementation loop (code → test → review → merge).

#### When to use
- After `claw-forge init` to begin building a new project
- After `claw-forge add` or `/expand-project` to build newly added features
- When resuming after an interruption (detects in-progress features automatically)
- For controlled feature sprints with `--concurrency` tuned to your provider tier

#### Usage
```bash
# Standard run (5 concurrent agents, Sonnet, reads claw-forge.yaml)
claw-forge run

# Override project directory
claw-forge run --project ~/projects/taskflow-api

# More concurrency for a large feature set
claw-forge run --concurrency 10

# YOLO mode: skip human-input prompts, max CPU concurrency, aggressive retry
claw-forge run --yolo

# Use a specific model for all coding agents
claw-forge run --model claude-opus-4-20250514

# Use a different config (e.g. high-priority providers)
claw-forge run --config claw-forge.premium.yaml
```

#### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--config`, `-c` | path | `claw-forge.yaml` | Provider and orchestrator config |
| `--project`, `-p` | path | `.` | Project root directory |
| `--task`, `-t` | string | `coding` | Agent plugin to run (`coding`, `testing`, `reviewing`) |
| `--model`, `-m` | string | `claude-sonnet-4-20250514` | Model identifier for coding agents |
| `--concurrency`, `-n` | int | `5` | Max agents running simultaneously |
| `--yolo` | flag | `False` | Skip human approval gates, max concurrency, aggressive retry |

#### What it does internally
1. Loads `claw-forge.yaml`, expands `${ENV_VAR}` placeholders.
2. Connects to the state service (starts one if not running).
3. Pulls the feature queue ordered by dependency wave and priority.
4. Spawns up to `--concurrency` Claude Code agent sessions via the provider pool.
5. Each agent runs the TDD loop: write tests → make them pass → commit.
6. On completion, updates feature status in the state DB (Passing / Failed / Blocked).
7. If a feature is Blocked, prompts for human input (unless `--yolo`).
8. Continues until the queue is empty or all remaining features are Blocked/Failed.

#### Real-world example
TaskFlow API has 59 features across 4 waves. You run:

```bash
claw-forge run --concurrency 5 --model claude-sonnet-4-20250514
```

Wave 1 (8 auth features) starts immediately, 5 agents fire in parallel. Wave 2 begins as Wave 1
features reach "Passing" status.

#### Output example
```
claw-forge v0.2.0b1
Project: ~/projects/taskflow-api
Task:    coding
Model:   claude-sonnet-4-20250514
Providers: 3

Dispatching wave 1/4 (8 features, concurrency=5)…
  [1/5] Agent abc123 → "User can register with email and password"
  [2/5] Agent def456 → "User can login and receive JWT tokens"
  [3/5] Agent ghi789 → "System validates email format on registration"
  [4/5] Agent jkl012 → "System hashes passwords with bcrypt"
  [5/5] Agent mno345 → "User can request password reset email"

✅ "User can register" — PASSING (1m 42s, $0.04)
✅ "User can login"    — PASSING (2m 08s, $0.05)
⏳ "Rate limiting"    — waiting on: auth-core (blocked)

Progress: 12/59 passing · 3 in-flight · $0.61 spent
```

#### Pro tips
- Start with `--concurrency 3` on a new project to verify your spec parses cleanly before
  committing to a full parallel run.
- Use `--yolo` only when you trust your spec is precise. Human-input gates exist for a reason.
- Open `claw-forge ui` in a separate terminal while `run` is active to watch the Kanban board.

#### Related commands
- **Before:** `claw-forge init`, `claw-forge state`
- **During:** `claw-forge status`, `claw-forge ui`, `claw-forge pause`
- **After:** `/check-code`, `/checkpoint`, `/review-pr`

---

### `claw-forge add`

#### Purpose
Adds one or more features to an existing project — either a single feature description or a full
brownfield spec — without touching features that are already passing.

#### When to use
- You want to add a single feature mid-sprint without writing a full spec
- You've generated `additions_spec.xml` via `/create-spec` (brownfield mode)
- A stakeholder requests a new endpoint after the first run finished
- You're iterating on an existing app and want agents to match its existing conventions

#### Usage
```bash
# Single feature, quick add
claw-forge add "User can export tasks as CSV"

# From a brownfield XML spec
claw-forge add --spec additions_spec.xml

# Suppress automatic branch creation
claw-forge add "Add rate limiting" --no-branch

# Target a non-current directory
claw-forge add --spec additions_spec.xml --project ~/projects/myapp
```

#### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `feature` | positional | — | Feature description or `@spec-file` path |
| `--spec`, `-s` | path | `None` | Path to brownfield `additions_spec.xml` |
| `--project`, `-p` | path | `.` | Project root directory |
| `--branch/--no-branch` | flag | `True` | Auto-create a git branch for the addition |

#### What it does internally
1. If `--spec` is provided, reads `additions_spec.xml` and loads `brownfield_manifest.json` from
   the project root (if present) to provide existing context.
2. Merges `stack`, `test_baseline`, and `conventions` from the manifest into the agent context.
3. Runs `InitializerPlugin` to parse the new features and append them to the state DB.
4. Prints integration points and constraints from the spec.
5. Suggests a git branch name based on the spec's `<project_name>`.
6. Shows the next command: `claw-forge run --spec additions_spec.xml`.

#### Real-world example
Your TaskFlow API is live. Product wants Stripe payments. You've run `/create-spec` (brownfield)
to produce `additions_spec.xml`. Now:

```bash
claw-forge add --spec additions_spec.xml
```

#### Output example
```
✅ Brownfield spec: TaskFlow API — Stripe Payments
   Mode: brownfield
   Features to add: 12
   Constraints: 3
   Integration points: 4

Agent context:
  Existing stack: Python / FastAPI / SQLite
  Test baseline: 59 tests passing, 91% coverage
  Conventions: snake_case, async handlers, pydantic v2

  ⚠ Constraints (will be enforced by all agents):
    1. Must not modify existing auth flow
    2. All 59 existing tests must stay green
    3. Follow existing async handler pattern in routers/

  Suggested git branch: feature/stripe-payments

  Next: claw-forge run --spec additions_spec.xml --project .
```

#### Pro tips
- Always run `claw-forge analyze` first when adding to an existing codebase — it generates
  `brownfield_manifest.json` which gives agents full context about your conventions.
- For a single quick feature, the positional form (`claw-forge add "..."`) is faster than a
  full spec.
- Commit your current state before `claw-forge add` — the auto-branch makes it easy to diff.

#### Related commands
- **Before:** `claw-forge analyze`, `/create-spec` (brownfield mode)
- **After:** `claw-forge run`

---

### `claw-forge fix`

#### Purpose
Runs a reproduce-first bug-fix protocol: the agent writes a failing test that proves the bug,
then makes it pass, then runs the full regression suite to ensure nothing else broke.

#### When to use
- A user reports a bug and you have a clear reproduction path
- CI is failing on a specific test and you want an agent to diagnose and fix it
- You've created a `bug_report.md` via `/create-bug-report` and want to hand it to an agent
- Quick one-liner fix for obvious issues without writing a formal report

#### Usage
```bash
# One-liner description
claw-forge fix "User gets 500 error when resetting password with uppercase email"

# From a structured bug report (recommended for complex bugs)
claw-forge fix --report bug_report.md

# Target a different project
claw-forge fix --report bug_report.md --project ~/projects/taskflow-api

# Don't create a git branch (fix directly on current branch)
claw-forge fix "Missing null check in task serializer" --no-branch
```

#### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `description` | positional | `None` | One-line bug description |
| `--report`, `-r` | path | `None` | Path to `bug_report.md` |
| `--project`, `-p` | path | `.` | Project root directory |
| `--branch/--no-branch` | flag | `True` | Create `fix/<slug>` git branch |

#### What it does internally
1. Parses the bug report or description into a `BugReport` object.
2. Creates a `fix/<slug>` git branch (e.g. `fix/uppercase-email-password-reset`).
3. Runs `BugFixPlugin` which spawns a coding agent with the bug context.
4. Agent phase 1 (RED): writes a failing regression test that proves the bug exists.
5. Agent phase 2 (GREEN): modifies source code until the test passes.
6. Agent phase 3 (REFACTOR): runs full test suite; fails if any existing tests break.
7. Reports files modified and the test that was added.

#### Real-world example
A user reports: "I can't reset my password if my email address has any uppercase letters."
You use `/create-bug-report` to generate `bug_report.md`, then:

```bash
claw-forge fix --report bug_report.md
```

#### Output example
```
🐛 Bug: Password reset fails for emails with uppercase letters
[dim]Created branch: fix/password-reset-fails-for-emails-with-uppercase-lett[/dim]

Running bug-fix agent…

  Phase 1 — RED: Writing failing test…
    ✅ test_password_reset_uppercase_email FAILED (as expected)

  Phase 2 — GREEN: Finding root cause…
    Root cause: auth/service.py:142 — email not lowercased before DB lookup
    Fix: add .lower() before query

  Phase 3 — REFACTOR: Running full test suite…
    ✅ 59 tests passed, 0 failed

✅ Bug fix complete
   Files modified: auth/service.py, tests/test_auth.py
   New test: test_password_reset_uppercase_email
```

#### Pro tips
- Use `--report bug_report.md` for anything non-trivial — the structured report gives the agent
  reproduction steps, expected vs actual behaviour, and scope constraints.
- The mandatory regression test is the real value here: the bug can never silently re-appear.
- If the fix attempt fails, the agent explains why — use that output as context for your own fix.

#### Related commands
- **Before:** `/create-bug-report` (generate the structured report)
- **After:** `/check-code`, `/review-pr`

---

### `claw-forge status`

#### Purpose
Shows a zero-friction project status card: progress by phase, active agent state, cost so far,
and the one recommended next action — perfect for re-entry after leaving a session.

#### When to use
- Coming back to a project after a break and want to see where things are
- Something looks stuck and you want to know which feature is Blocked
- You want a quick cost check before letting more agents run
- Before running `/checkpoint` to know the current state of play

#### Usage
```bash
# Default (reads claw-forge.yaml in cwd)
claw-forge status

# Explicit config
claw-forge status --config claw-forge.yaml
```

#### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--config`, `-c` | path | `claw-forge.yaml` | Path to YAML config |

#### What it does internally
1. Loads config and connects to the state service (port 8420 by default).
2. Fetches session list and active feature states.
3. Groups features by phase and status (Pending / In Progress / Passing / Failed / Blocked).
4. Calculates per-phase progress bars and overall completion percentage.
5. Shows cost, active agent count, and the recommended next action.

#### Real-world example
You paused a TaskFlow run an hour ago and are back at your desk:

```bash
claw-forge status
```

#### Output example
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  TaskFlow API  ·  claude-sonnet-4-20250514  ·  $2.41 spent
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Phase 1: Core models + auth    ████████████████ 8/8   ✅ complete
  Phase 2: Task CRUD             ████████████░░░░ 12/16  🔄 in progress
  Phase 3: Notifications         ░░░░░░░░░░░░░░░░ 0/6    ⏳ pending
  Phase 4: Polish                ░░░░░░░░░░░░░░░░ 0/9    ⏳ pending

  Active agents (3):
    Agent a1b2c3 → "User can filter tasks by due date"    (1m 12s)
    Agent d4e5f6 → "System paginates task list responses" (0m 48s)
    Agent g7h8i9 → "User can assign tasks to team members" (2m 03s)

  Blocked (1):
    ⚠ "Webhook notification on task complete" — waiting for human input
    → Run: claw-forge input taskflow-api

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  20/39 features passing  ·  3 in-flight  ·  1 blocked
  Next: answer the blocked feature's question, then continue
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

#### Pro tips
- Run `claw-forge status` before re-running `claw-forge run` — if features are Blocked, answer
  them first with `claw-forge input`.
- The "Next action" line is the most important thing on screen: follow it.
- Alias this to `cf-st` in your shell for speed.

#### Related commands
- **Next:** `claw-forge input`, `claw-forge run`, `/checkpoint`

---

### `claw-forge analyze`

#### Purpose
Scans an existing codebase to understand its stack, test baseline, conventions, and hot files —
then writes `brownfield_manifest.json`, which enables subsequent `add` and `fix` commands to
match your existing patterns.

#### When to use
- Before adding features to a codebase claw-forge has never seen
- When your team has coding conventions you want agents to respect
- After cloning an inherited repository you want to extend
- Before running `/create-spec` in brownfield mode

#### Usage
```bash
# Analyze current directory
claw-forge analyze

# Analyze a specific project
claw-forge analyze --project ~/projects/myapp

# With explicit config
claw-forge analyze --config claw-forge.yaml --project .
```

#### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--project`, `-p` | path | `.` | Project root to analyze |
| `--config`, `-c` | path | `claw-forge.yaml` | Path to YAML config |

#### What it does internally
1. Scans file extensions to detect language/framework/database.
2. Parses `pyproject.toml` / `package.json` / `go.mod` for dependencies.
3. Runs `git log --stat` to identify hot files (most frequently changed).
4. Runs the test suite to establish the baseline (N tests, X% coverage).
5. Inspects source files for naming conventions, docstring style, import patterns.
6. Writes `brownfield_manifest.json` to the project root.

#### Real-world example
You're adding Stripe payments to a live FastAPI app:

```bash
cd ~/projects/myapp
claw-forge analyze
```

#### Output example
```
Analyzing ~/projects/myapp…

  Stack detected:
    Language:   Python 3.12
    Framework:  FastAPI 0.111
    Database:   PostgreSQL (asyncpg)
    Testing:    pytest + pytest-asyncio

  Test baseline:
    Tests:      47 passing, 0 failing
    Coverage:   87%
    Last run:   2025-05-14 09:12

  Hot files (git history):
    routers/auth.py        — 34 commits
    services/user.py       — 28 commits
    models/user.py         — 19 commits

  Conventions detected:
    Naming:     snake_case functions, PascalCase models
    Imports:    absolute (from app.routers import ...)
    Docstrings: Google style
    Async:      async/await throughout (no sync handlers)

✅ Wrote brownfield_manifest.json
   Next: /create-spec (brownfield) → claw-forge add --spec additions_spec.xml
```

#### Pro tips
- Commit or stash local changes before `analyze` so the test baseline is clean.
- The hot files list tells you which parts of the codebase are most active — review those areas
  carefully after agents make changes.
- `brownfield_manifest.json` is committed to the repo so all team members get the same context.

#### Related commands
- **After:** `/create-spec` (brownfield mode), `claw-forge add`

---

### `claw-forge ui`

#### Purpose
Launches the real-time Kanban board — a React app that shows every feature's status (Pending,
In Progress, Passing, Failed, Blocked) with live WebSocket updates as agents work.

#### When to use
- Running a large parallel sprint and you want a visual overview
- Sharing progress with a team or stakeholder on a second monitor
- Debugging why certain features are stuck (see the Blocked column in real time)
- Checking cost and provider health at a glance during a run

#### Usage
```bash
# Default: port 5173, connects to state service on :8888
claw-forge ui

# Custom ports
claw-forge ui --port 3000 --state-port 8420

# Don't auto-open browser (useful for headless servers)
claw-forge ui --no-open

# Jump straight to a specific session
claw-forge ui --session a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

#### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--port`, `-p` | int | `5173` | Port for the Vite dev server |
| `--state-port` | int | `8888` | Port the state service is running on |
| `--open/--no-open` | flag | `True` | Auto-open browser after 2s |
| `--session`, `-s` | string | `""` | Session UUID to pre-select on the board |

#### What it does internally
1. Checks that Node.js is installed.
2. If `ui/node_modules` doesn't exist, runs `npm install` automatically.
3. Sets `VITE_API_PORT` and `VITE_WS_PORT` env vars from `--state-port`.
4. Starts `npm run dev` in the `ui/` directory.
5. After a 2-second delay, opens `http://localhost:<port>/?session=<session>` in the default
   browser.

#### Real-world example
You start a 50-feature parallel run and want to watch it on your second monitor:

```bash
# Terminal 1: start state service
claw-forge state &

# Terminal 2: start agents
claw-forge run --concurrency 5

# Terminal 3: launch board
claw-forge ui --session $(cat .claw-forge/session-id)
```

#### Output example
```
🔥 Starting claw-forge Kanban UI
   UI:           http://localhost:5173/?session=a1b2c3d4
   State API:    http://localhost:8888
   Press Ctrl+C to stop

  VITE v5.2.0  ready in 312 ms
  ➜  Local:   http://localhost:5173/
  ➜  Network: http://10.0.1.42:5173/
```

Browser shows:
```
┌─────────────────────────────────────────────────────────────┐
│ TaskFlow API · 🟢 claude-oauth  🟢 anthropic-direct         │
│ Progress: ████████████░░░░  20/59 passing · $2.41 · 3 agents│
├──────────────┬──────────────┬──────────────┬────────────────┤
│   PENDING    │ IN PROGRESS  │   PASSING    │    BLOCKED     │
│     39       │      3       │     20       │       1        │
│ ─────────    │ ─────────    │ ─────────    │ ─────────      │
│ Filter tasks │ Assign tasks │ User login   │ Webhook notif. │
│ Export CSV   │ Pagination   │ User register│ (awaiting API  │
│ …            │ Due dates    │ …            │  key input)    │
└──────────────┴──────────────┴──────────────┴────────────────┘
```

#### Pro tips
- The Kanban board updates over WebSocket — no refreshing needed.
- The provider health dots (🟢/🟡/🔴) in the header tell you if a provider is circuit-broken.
- Use `--no-open` on a remote machine and tunnel via SSH: `ssh -L 5173:localhost:5173 yourserver`.

#### Related commands
- **Requires:** `claw-forge state` (state service must be running)
- **During:** `claw-forge run`, `claw-forge status`

---

## Claude Slash Commands

These commands live in `.claude/commands/` and are used **inside Claude Code** (the editor),
not in the terminal. Type `/command-name` in the Claude Code chat panel to invoke them.

They are automatically scaffolded by `claw-forge init` into your project directory.

---

### `/create-spec`

#### Purpose
Guides you through an interactive conversation to generate a precise, claw-forge-compatible XML
project spec — either for a new app (greenfield) or for adding features to an existing one
(brownfield). The output becomes the input to `claw-forge init` or `claw-forge add`.

#### When to use
- Starting a brand-new project and you want to think through features systematically
- Adding a significant feature set to an existing app (Stripe, auth, notifications, etc.)
- You have a rough idea but need help turning it into 100-300 granular agent tasks
- After running `claw-forge analyze` on an existing codebase

#### Usage
In Claude Code chat panel:
```
/create-spec
```
Or with a hint:
```
/create-spec Task Manager API with FastAPI and SQLite
```

#### What it does internally
1. Checks if `brownfield_manifest.json` exists → chooses Greenfield or Brownfield flow.
2. **Greenfield:** Asks about project identity, features by category, tech stack, DB schema,
   API structure, and UI layout. Derives 100-300 granular feature bullets.
3. **Brownfield:** Loads the manifest, asks what you're adding, constraints, integration points.
4. Generates and writes `app_spec.txt` (greenfield) or `additions_spec.xml` (brownfield).
5. Also writes `claw-forge.yaml` (greenfield only).
6. Shows a summary and next steps.

#### Real-world example
You want to build a Task Manager API. In Claude Code:

```
You: /create-spec

Claude: What are you building? Give me a name and 2-3 sentence description.

You: TaskFlow API — a REST API for managing personal tasks and projects.
     Users can create projects, add tasks with due dates, assign priorities,
     and get reminded via email when deadlines approach.

Claude: Who is it for?

You: Individual developers and small teams, up to ~10 people per workspace.

Claude: Quick or Detailed spec?

You: Detailed

Claude: Let's map out the features. What happens when a user first opens the app?

You: Registration with email/password, email verification, then login.

Claude: From that, I'm generating:
  Authentication (8 bullets)
  - User can register with email and password (returns 201 with user_id)
  - System sends verification email on registration
  - User can verify email via link (sets email_verified=true)
  - User can login and receive JWT access_token + refresh_token
  - System rejects login for unverified emails with 403
  - User can refresh access token using refresh_token
  - User can logout (invalidates refresh token)
  - System rate-limits login attempts (5/minute per IP)

  Does this capture it? Anything to add?
```

#### Output example
After the conversation, Claude writes:

```
✅ Project spec created!

📊 Summary:
  Features: 59 across 6 categories
  Phases: 4 implementation steps
  Tables: 5 database tables
  Endpoints: 24 API endpoints

Files written:
  app_spec.txt     (59 feature bullets, 4 phases, full DB schema)
  claw-forge.yaml  (provider config, concurrency=5)

Next steps:
  1. Review app_spec.txt — add/remove features as needed
  2. Run: claw-forge init --spec app_spec.txt
  3. Run: claw-forge run --concurrency 5

💡 Tip: Each feature bullet = one agent task. More specific = better output.
```

#### Pro tips
- Be specific in each answer. "User can manage tasks" → vague. "User can create a task with
  title, description, due_date, and priority (low/medium/high)" → perfect.
- Don't worry about getting the feature list perfect — you can add more later with
  `/expand-project`.
- For brownfield, run `claw-forge analyze` first to generate `brownfield_manifest.json` —
  `/create-spec` will auto-load it and pre-fill your tech stack details.

#### Related commands
- **Before:** `claw-forge analyze` (brownfield)
- **After:** `claw-forge init` (greenfield) or `claw-forge add` (brownfield)

---

### `/expand-project`

#### Purpose
Adds new features to a running or paused claw-forge project by POSTing them atomically to the
state service — no re-running `init`, no duplicating existing features.

#### When to use
- Mid-sprint, a stakeholder requests additional functionality
- You finished Wave 1 and want to add Wave 2 features on the fly
- You realized you missed an important use case during spec creation
- You want to interactively build up features without editing XML

#### Usage
In Claude Code:
```
/expand-project
```

Claude will ask what you want to add, then handle the state service API calls automatically.

#### What it does internally
1. Queries `http://localhost:8420/sessions` to list current features and their status.
2. Shows you what exists so you don't duplicate.
3. Asks what new features to add (title, description, dependencies, priority).
4. POSTs each new feature to `/sessions/<id>/tasks` atomically.
5. On failure, rolls back successfully-created features.
6. Appends new features to `.claw-forge/app_spec.txt` to keep the spec in sync.
7. Reminds you to resume if the project is paused.

#### Real-world example
TaskFlow is 40/59 features done. Your client wants CSV export:

```
You: /expand-project

Claude: Current project: TaskFlow API (40/59 passing, 3 in-flight)

  Existing features (summary):
    Phase 1: Authentication — 8/8 ✅
    Phase 2: Task CRUD — 20/22 ✅
    Phase 3: Projects — 12/16 🔄
    Phase 4: Polish — 0/13 ⏳

  What would you like to add?

You: CSV export for tasks. User should be able to download all their tasks
     as a CSV file with columns: title, description, due_date, priority,
     status, project_name.

Claude: Creating feature:
  Title: User can export tasks as CSV
  Description: GET /tasks/export returns a CSV file with title, description,
    due_date, priority, status, project_name columns. Filters by workspace.
  Dependencies: [task-list-endpoint, project-read-endpoint]
  Priority: 6

  ✅ Created task: exp-001
  ✅ Updated .claw-forge/app_spec.txt

  The dispatcher will pick this up on the next run.
```

#### Pro tips
- Use this instead of re-running `init` — it's faster and doesn't touch existing features.
- Set `priority: 8+` for urgent additions so they jump the queue.
- After expanding, open the Kanban board (`claw-forge ui`) to see the new card appear.

#### Related commands
- **Requires:** State service running (`claw-forge state`)
- **After:** `claw-forge run` (resumes automatically if already running)

---

### `/check-code`

#### Purpose
Runs ruff (lint + format), mypy (type checking), and pytest (tests) in sequence and produces a
structured quality report — identifying exactly what's failing and why, with fix suggestions.

#### When to use
- Before creating a PR to ensure code is clean
- After a batch of agents finish to verify their output
- When CI is red and you want a fast local diagnosis
- Before running `/checkpoint` to capture only a clean state

#### Usage
In Claude Code:
```
/check-code
```

Claude runs the checks and formats the results.

#### What it does internally
1. Runs `uv run ruff check . --output-format=concise` (lint).
2. Runs `uv run ruff format --check .` (formatting).
3. Runs `uv run mypy . --ignore-missing-imports --no-error-summary` (types).
4. Runs `uv run pytest tests/ -v --tb=short --no-header` (tests).
5. Formats results into a structured report with ✅/❌ per check.
6. For failures: explains root cause and provides the exact fix command.
7. Optionally applies ruff auto-fixes if you say yes.

#### Real-world example
You've just run `claw-forge run` and 59 features are passing. You want to verify before pushing:

```
You: /check-code

Claude: Running code quality checks…
```

#### Output example
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Code Quality Report — TaskFlow API
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ✅ Ruff lint     — 0 errors, 0 warnings
  ✅ Ruff format   — All files formatted
  ❌ MyPy          — 2 type errors
  ✅ Pytest        — 59 passed, 0 failed

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MyPy Issues:
  routers/tasks.py:87: error: Argument "due_date" has incompatible type
    "str | None"; expected "date | None"
    Fix: change annotation to Optional[date] and parse with date.fromisoformat()

  services/notifications.py:34: error: Item "None" has no attribute "email"
    Fix: add null guard → if user is None: raise HTTPException(404)

Overall: NEEDS ATTENTION (1/4 checks failing)

Quick fix:
  uv run ruff check . --fix && uv run ruff format .
  (mypy errors require manual fixes — see above)
```

#### Pro tips
- Make `/check-code` part of your pre-PR ritual: code → `/check-code` → `/checkpoint` →
  `/review-pr` → push.
- If mypy is noisy on a large codebase, run it on just the changed files:
  ask Claude to check specific modules.
- Ruff auto-fixes are safe — always accept them.

#### Related commands
- **After:** `claw-forge run`, `claw-forge fix`
- **Next:** `/checkpoint`, `/review-pr`

---

### `/checkpoint`

#### Purpose
Creates a timestamped save point: commits all changes, exports the feature state DB to a JSON
snapshot, and writes a human-readable `CHECKPOINT.md` — so you can always rewind to a known
good state.

#### When to use
- Before a risky operation (provider change, schema migration, major refactor)
- After a wave of features reaches "Passing" status
- End of day — save your progress before shutting down
- Before `/review-pr` — ensures the reviewer sees a clean, committed state

#### Usage
In Claude Code:
```
/checkpoint
```

Claude handles everything automatically.

#### What it does internally
1. Runs `uv run pytest tests/ -q` and notes pass/fail counts.
2. Creates `.claw-forge/snapshots/` if it doesn't exist.
3. Queries `http://localhost:8420/sessions` and saves the full state to
   `snapshot-YYYYMMDDTHHMMSS.json`.
4. Writes `.claw-forge/CHECKPOINT.md` with status summary, in-progress features, and known issues.
5. Runs `git add -A` and commits with a structured message including test counts and feature
   progress.
6. Reports the commit hash and snapshot file path.

#### Real-world example
Wave 2 of TaskFlow just finished — 22 more features passing. You want to save before starting
Wave 3:

```
You: /checkpoint
```

#### Output example
```
Running pytest… 59 passed, 0 failed.

Exporting state snapshot…
  ✅ Snapshot: .claw-forge/snapshots/snapshot-20250514T143022.json

Writing CHECKPOINT.md…
  ✅ .claw-forge/CHECKPOINT.md

Committing…
  [main 4a7f2e1] checkpoint: 2025-05-14 14:30:22
  Status:
  - Tests: 59 passing
  - Features: 39/59

✅ Checkpoint saved!

  Commit:   4a7f2e1
  Snapshot: .claw-forge/snapshots/snapshot-20250514T143022.json
  Summary:  .claw-forge/CHECKPOINT.md

To restore to this state:
  git checkout 4a7f2e1
```

#### Pro tips
- Run `/checkpoint` before every `claw-forge run --yolo` — if something goes wrong, you can
  revert instantly.
- The JSON snapshot captures the full task graph — use it to understand what each agent built.
- Pair with `git tag v0.1.0-checkpoint-1` for named restore points on important milestones.

#### Related commands
- **Before:** `/check-code` (verify first)
- **After:** `/review-pr`

---

### `/review-pr`

#### Purpose
Reviews the current git diff (or a specific PR) for tests, type annotations, security issues,
performance problems, and style — producing a structured APPROVE / REQUEST CHANGES / COMMENT
verdict with actionable feedback.

#### When to use
- Before merging any agent-generated code into `main`
- After `claw-forge fix` to verify the bug fix is correct
- When reviewing a teammate's PR without leaving Claude Code
- As the final step before pushing a feature branch

#### Usage
In Claude Code:
```
/review-pr
```
Or to review a specific PR number (requires `gh` CLI):
```
/review-pr 42
```

#### What it does internally
1. Gets the diff: `git diff HEAD` (uncommitted) or `gh pr diff <N>` (specific PR).
2. For each changed file, checks: tests, type annotations, docstrings, security, performance,
   style.
3. Produces a structured report with BLOCKING / SUGGESTION / LOOKS GOOD sections.
4. Optionally posts a review event to the state service.
5. Returns a clear APPROVE / REQUEST CHANGES / COMMENT verdict.

#### Real-world example
You've fixed the password-reset bug and want to verify before pushing:

```
You: /review-pr
```

#### Output example
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PR Review — fix/password-reset-uppercase-email
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Files changed: 2
  Lines added: +23 | Lines removed: -1

  VERDICT: ✅ APPROVE

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  🔴 BLOCKING ISSUES: none

  🟡 SUGGESTIONS:
    1. auth/service.py:142 — consider adding a comment explaining why
       .lower() is applied (non-obvious security implication)

  ✅ LOOKS GOOD:
    - Tests: new regression test covers the exact bug path
    - Types: all annotations correct
    - Security: no hardcoded secrets, parameterized queries
    - No N+1 issues introduced

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

#### Pro tips
- The security check specifically looks for shell injection, hardcoded keys, and SQL injection.
  Trust it but also scan manually for domain-specific issues the agent might miss.
- "COMMENT" verdict means the code is mergeable but has observations. Use it for stylistic
  feedback that doesn't block shipping.
- For large PRs (>500 lines), ask Claude to review file by file to get more thorough analysis.

#### Related commands
- **Before:** `/check-code`, `/checkpoint`
- **After:** `git push`, `gh pr create`

---

### `/pool-status`

#### Purpose
Shows the health of every configured provider — RPM usage, success rate, average latency, cost
today — with alerts and recommendations, so you can catch problems before they slow down your
agent run.

#### When to use
- Before starting a large `claw-forge run` to verify providers are healthy
- When agents are running slower than expected (check latency / circuit breakers)
- When you want to understand cost distribution across providers
- After adding a new provider to verify it's routing correctly

#### Usage
In Claude Code:
```
/pool-status
```

Or via CLI (raw data, no analysis):
```bash
claw-forge pool-status
```

#### What it does internally
1. Queries `http://localhost:8420/pool/status` for live health data.
2. Falls back to `claw-forge pool-status` CLI if the state service isn't running.
3. Formats provider health into a table with status indicators (🟢/🟡/🔴).
4. Shows last 5 requests with provider routing, latency, and cost.
5. Highlights circuit breaker events and approaching RPM limits.
6. Adds actionable recommendations.

#### Real-world example
Your run is slower than usual. You suspect a provider issue:

```
You: /pool-status
```

#### Output example
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Provider Pool Status — 2025-05-14 14:23:45
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Provider           Status    RPM      Success  Latency  Cost Today
  ─────────────────────────────────────────────────────────────────
  claude-oauth       🟢 OK     12/∞     100%     1.2s     $0.00
  anthropic-direct   🟡 BUSY   58/60    99.5%    0.8s     $1.23
  groq-backup        🔴 OPEN   0/30     72%      —        $0.00

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ⚠ anthropic-direct is at 97% RPM capacity — slowdowns likely
  🔴 groq-backup circuit breaker is OPEN (5 consecutive failures)
     Auto-resets in: ~2 minutes

  Recommendations:
    - Add another provider — only 1 of 3 is fully healthy
    - groq-backup circuit breaker will auto-reset; monitor recovery
    - Consider lowering anthropic-direct priority to let claude-oauth handle more

  Total cost today: $1.23 · Active sessions: 3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

#### Pro tips
- A 🔴 circuit breaker that auto-resets in 2 minutes is fine to wait out. A persistent one
  means your API key or endpoint is broken — fix it.
- If `anthropic-direct` is near RPM limit, add `claude-oauth` (free tier) as a load-overflow
  provider.
- Use the CLI version (`claw-forge pool-status`) for a quick table without the analysis overlay.

#### Related commands
- **Before:** `claw-forge run`
- **CLI equivalent:** `claw-forge pool-status`

---

### `/create-bug-report`

#### Purpose
Guides you through a 6-phase conversation to create a precise, structured `bug_report.md` file —
then hands it directly to `claw-forge fix` to run the TDD repair loop.

#### When to use
- A user reports a bug and you want the agent to have full context before attempting a fix
- You're tracking down a non-obvious issue and want to think through it systematically
- You want to create a reusable bug report for your issue tracker
- Before running `claw-forge fix --report` on a complex bug

#### Usage
In Claude Code:
```
/create-bug-report
```
Or with an initial hint:
```
/create-bug-report user can't reset password with uppercase email
```

#### What it does internally
1. **Phase 1** — Title & symptoms: asks what's broken, any error messages, frequency.
2. **Phase 2** — Reproduction: exact steps, every-time vs intermittent.
3. **Phase 3** — Expected vs actual behaviour.
4. **Phase 4** — Scope: runs `ls src/ lib/ app/` to suggest affected files, asks what must not
   change.
5. **Phase 5** — Writes `bug_report.md` to the project root.
6. **Phase 6** — Asks "Ready to fix?" → if yes, runs `claw-forge fix --report bug_report.md`.

#### Real-world example
A user reports they can't reset their password. In Claude Code:

```
You: /create-bug-report

Claude: Phase 1 — What's broken? Describe the symptom in one sentence.

You: Users can't reset their password if their email address has any uppercase letters.

Claude: Any other symptoms? (error messages, affected users, frequency)

You: The reset email is never sent. No error message shown to user.
     Happens to anyone with uppercase in their email (e.g. John@example.com).
     Every time, 100% reproducible.

Claude: Phase 2 — Exact reproduction steps?

You: 1. Register with email John@example.com
     2. Go to /forgot-password
     3. Enter John@example.com
     4. Check inbox — no email arrives
     5. Check DB: no password_reset_token was created

Claude: Does it happen every time?

You: Yes, every time. john@example.com (lowercase) works fine.

Claude: Phase 3 — What should happen instead?

You: The system should be case-insensitive for email lookups.
     A reset email should always be sent regardless of case.
```

#### Output example
After all 6 phases, Claude writes `bug_report.md`:

```markdown
# Bug Report: Password reset fails for emails with uppercase letters

## Symptoms
Users cannot reset their password when their email contains uppercase letters.
The reset email is never sent, no error shown to the user.
Affects: all users with uppercase in email. Frequency: 100% reproducible.

## Reproduction Steps
1. Register with email John@example.com
2. Go to /forgot-password and enter John@example.com
3. Check inbox — no reset email arrives
4. Verify in DB: no password_reset_token row created for the user

## Expected Behaviour
System is case-insensitive for email lookups. Reset email always sent.

## Actual Behaviour
Password reset silently fails for mixed-case emails.

## Affected Files (suspected)
- auth/service.py (email lookup logic)
- routers/auth.py (forgot-password endpoint)

## Constraints
- Must not break existing auth flow for lowercase emails
- All 59 existing tests must remain green
```

Then:
```
✅ bug_report.md written.

Ready to fix? (yes/no)

You: yes

Running: claw-forge fix --report bug_report.md
```

#### Pro tips
- Be specific in Phase 4 about what must NOT change — agents treat constraints as hard rules.
- If the bug is intermittent, describe the conditions that trigger it (load, timing, data state).
- You can use the generated `bug_report.md` directly in GitHub Issues for team documentation.

#### Related commands
- **After:** `claw-forge fix --report bug_report.md`
- **Then:** `/check-code`, `/review-pr`

---

## See Also

- [docs/workflows.md](workflows.md) — End-to-end workflow walkthroughs
- [docs/brownfield.md](brownfield.md) — Brownfield mode deep dive
- [README.md](../README.md) — Project overview and quick start
