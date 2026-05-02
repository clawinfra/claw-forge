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
Bootstrap a new project — scaffold `.claude/`, `CLAUDE.md`, `claw-forge.yaml`,
`.env.example`, and `app_spec.example.xml`. Run this **once** before writing your spec.

#### When to use
- First command in any new project directory
- After cloning a repo that has no `.claude/` scaffold
- To get `app_spec.example.xml` as a format reference for your spec

#### Usage
```bash
# Bootstrap current directory
claw-forge init

# Bootstrap a specific directory
claw-forge init --project ~/projects/my-app
```

#### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--project`, `-p` | path | `.` | Root directory to bootstrap |
| `--config`, `-c` | path | `claw-forge.yaml` | Config file path (created if absent) |

#### What it does internally
1. Creates `claw-forge.yaml` with default providers if not present.
2. Creates `.env.example` documenting all environment variables.
3. Detects language/framework from `pyproject.toml`, `package.json`, `go.mod`, etc.
4. Generates `CLAUDE.md` tailored to the detected stack.
5. Creates `.claude/settings.json` (`enableAllProjectMcpServers: true`).
6. Copies 8 slash-command `.md` files into `.claude/commands/`.
7. Copies `app_spec.example.xml` — a full XML format reference for your spec.
8. Prints a next-step hint pointing to `/create-spec` or `claw-forge plan`.

#### Output example
```
✓ Created claw-forge.yaml  (edit providers as needed)
✓ Created .env.example     (copy to .env and fill keys)
⚠  No .env found — copy .env.example → .env and add your API keys
✓ Stack detected: python / fastapi
✓ Generated CLAUDE.md
✓ Created .claude/ with settings.json
✓ Created app_spec.example.xml  (reference format for your spec)
✓ Scaffolded 8 slash commands → .claude/commands/
  • /create-spec
  • /expand-project
  • /check-code
  ...

Next step: create your project spec.
  Option A — use the Claude slash command:
    Open Claude Code here and run /create-spec

  Option B — paste your PRD into Claude with this prompt:
    "Convert this PRD to claw-forge XML spec format.
     Use app_spec.example.xml in this directory as the template.
     Write the result to app_spec.txt."

  Then run: claw-forge plan app_spec.txt
```

#### Related commands
- **Next:** `/create-spec` (generate spec) → `claw-forge plan` (parse spec → DB)

---

### `claw-forge plan`

#### Purpose
Parse a spec file (`app_spec.txt` or `additions_spec.xml`) and generate the feature
dependency DAG in the state database. This is the planning step — run it after writing
your spec and before `claw-forge run`.

#### When to use
- After `/create-spec` produces `app_spec.txt`
- After converting a PRD to `app_spec.txt` using `app_spec.example.xml` as reference
- Re-running after editing the spec (only new features are added to the DB)
- Re-running on an active project to reconcile — completed tasks are preserved, only new features are added (use `--fresh` to start clean)

#### Usage
```bash
# Parse spec in current directory
claw-forge plan app_spec.txt

# Brownfield additions
claw-forge plan additions_spec.xml

# Use Sonnet instead of Opus (faster/cheaper, lower planning quality)
claw-forge plan app_spec.txt --model claude-sonnet-4-20250514

# Point at a different project
claw-forge plan app_spec.txt --project ~/projects/task-manager

# Reconcile with existing session (default — keeps completed tasks)
claw-forge plan app_spec.txt

# Force a fresh session (wipe and recreate all tasks)
claw-forge plan app_spec.txt --fresh
```

#### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `spec` | positional | **required** | Path to `app_spec.txt` or XML spec file |
| `--project`, `-p` | path | `.` | Root directory of the project |
| `--model`, `-m` | string | `claude-opus-4-5` | Model for parsing (Opus recommended) |
| `--concurrency`, `-n` | int | `5` | Used to estimate run time in summary |
| `--config`, `-c` | path | `claw-forge.yaml` | Path to YAML config |
| `--fresh` | flag | `False` | Force a fresh session — create all tasks from scratch. Without this flag, `plan` reconciles with the existing session: completed tasks are preserved, and only new/missing features are added. |

#### What it does internally
1. Validates the spec file exists and is valid XML.
2. Runs `InitializerPlugin` (Opus by default — planning errors cascade through every run).
3. Parses features from `<core_features>` — each bullet becomes one agent task.
4. Builds a dependency DAG from `<implementation_steps>` phase ordering.
5. Writes features to the state DB, printing a category table + wave count + ETA.

#### Output example
```
✅ Spec parsed: TaskFlow API

  Features by Category
  ┌──────────────────────┬───────┐
  │ Category             │ Count │
  ├──────────────────────┼───────┤
  │ Authentication       │    8  │
  │ Task Management      │   22  │
  │ API Layer            │    9  │
  │ Total                │   59  │
  └──────────────────────┴───────┘

  Dependency waves: 4
  Estimated run time: ~24 minutes (at concurrency=5)

  Next: claw-forge run --concurrency 5
```

#### Pro tips
- **Always use Opus** for planning. It produces better DAGs and catches ambiguous features.
  Use `--model sonnet` only if you're iterating quickly and cost matters more than quality.
- **Plan reconciliation** is the default behavior when re-running `plan` on an existing project. Completed tasks stay as-is, failed/pending tasks are retained, and only features missing from the DB are added as new pending tasks. Use `--fresh` to wipe and recreate all tasks from scratch.
- `app_spec.example.xml` (created by `claw-forge init`) shows the full XML schema.

#### Related commands
- **Before:** `claw-forge init` → `/create-spec`
- **After:** `claw-forge run`

---

### `claw-forge validate-spec`

#### Purpose
Validates a spec file across 3 layers before it seeds the task DAG. Catches bad bullets
early so agents never receive vague, untestable, or incomplete work orders — the most
common source of agent failure and rework.

#### When to use
- After `/create-spec` writes `app_spec.txt` and before `claw-forge plan`
- After manually editing a spec to verify you haven't broken any bullets
- In CI pipelines to gate `claw-forge plan` on spec quality

#### Usage
```bash
# Full validation — all 3 layers (requires ANTHROPIC_API_KEY for Layer 2)
claw-forge validate-spec app_spec.txt

# Structural + coverage only — zero LLM cost, no API key required
claw-forge validate-spec app_spec.txt --no-llm

# Stricter LLM threshold (default is 7.0)
claw-forge validate-spec app_spec.txt --threshold 8.0

# Use a different model for Layer 2 (default: Haiku)
claw-forge validate-spec app_spec.txt --model claude-sonnet-4-6
```

#### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `spec` | positional | **required** | Path to `app_spec.txt` or XML spec file |
| `--no-llm` | flag | `False` | Skip Layer 2 adversarial LLM evaluation |
| `--threshold`, `-t` | float | `7.0` | Layer 2 approval threshold (0–10) |
| `--model`, `-m` | string | `claude-haiku-4-5-20251001` | Model for Layer 2 evaluation |

#### The 3 layers

**Layer 1 — Structural (deterministic, zero cost)**
Every bullet is checked for:
- **Action-verb prefix** — must start with `User can`, `System returns`, `API validates`, `UI displays`, etc.
- **Measurable outcome** — must contain an observable result: HTTP status code, field name, UI element, redirect target, or event name
- **Atomicity** — no compound connectors (`and then`, `and receive`, `and redirect`) that hide multiple behaviors in one bullet
- **Non-vagueness** — minimum word count; no `etc`, `various`, `stuff`, `things`

Layer 1 violations are **errors** (compound bullets) or **warnings** (missing outcome, vague phrasing).

**Layer 2 — Adversarial LLM evaluation (per category, optional)**
A separate model call grades each category's bullet set on 4 spec-specific dimensions:

| Dimension | Weight | What it checks |
|-----------|--------|----------------|
| Testability | ×3 | Can you write a pass/fail test for every bullet? |
| Atomicity | ×3 | Is each bullet one implementable unit? |
| Specificity | ×2 | Does each bullet name concrete outcomes? |
| ErrorCoverage | ×2 | Does the category cover error and edge cases? |

Categories scoring below `--threshold` emit a WARNING with specific feedback.
Skips gracefully if `ANTHROPIC_API_KEY` is not set.

**Layer 3 — Coverage gap detection (deterministic, zero cost)**
Cross-references `<api_endpoints_summary>` and `<database_schema>` against feature bullets.
Every listed endpoint and table must appear in at least one bullet — otherwise agents will
never implement it.

#### What it does internally
1. Parses the spec with `ProjectSpec.from_file()`.
2. Runs Layer 1 structural rules on every bullet.
3. Runs Layer 2 adversarial LLM evaluation per category (if `--no-llm` is not set).
4. Runs Layer 3 coverage gap detection against endpoints and tables.
5. Prints a layered report and exits non-zero if any **errors** are found.

#### Output example
```
Validating: app_spec.txt
  Features:   59
  Categories: 6
  Endpoints:  24
  Tables:     5

Layer 1 (Structural)  PASS  0 errors, 3 warnings
  ⚠ [Task Management] Bullet has no measurable outcome.
    → Add a concrete result: HTTP status code, UI element name, field name.
    Bullet: "User can search tasks"
  ⚠ [API Layer] Bullet is too short (4 words). Minimum is 6.
  ⚠ [UI / UX] Bullet contains vague filler: ['etc'].

Layer 2 (LLM eval)    PASS
  ✓ Authentication & User Management: 8.9/10
  ✓ Task Management: 7.8/10
  ✓ API Layer: 8.2/10
  ✓ UI / UX: 7.1/10

Layer 3 (Coverage)    PASS  0 gaps

✅ Spec passed validation  (3 warnings)

  Next: claw-forge plan app_spec.txt
```

#### Failing example
```
Layer 1 (Structural)  FAIL  1 errors, 2 warnings
  ✗ [Authentication] Compound bullet detected ('and then'). Split into two bullets.
    → Each bullet must be one atomic behavior.
    Bullet: "User can register and then login and receive a JWT token"

✗ Spec has 1 error(s) — fix before running claw-forge plan

  To fix: open Claude Code and run /fix-spec
  Then re-run: claw-forge validate-spec app_spec.txt
```

Exit code 1, blocks `claw-forge plan`. Run `/fix-spec` in Claude Code to auto-repair the issues
iteratively, then re-run `validate-spec` until clean.

#### Pro tips
- Run `--no-llm` in tight loops when iterating on the spec — it's instant and free.
- Use `--threshold 8.0` for mission-critical apps where you want highly specific bullets.
- In CI, add `claw-forge validate-spec app_spec.txt --no-llm` as a gate before `claw-forge plan`.
- The Layer 3 gap report is the most actionable output — each gap is a feature the agents will silently never implement.

#### Related commands
- **Before:** `/create-spec`
- **If issues found:** `/fix-spec` — auto-repairs issues and re-validates in a loop
- **After:** `claw-forge plan`

---

### `claw-forge import`

#### Purpose
Convert a 3rd-party harness tool export (BMAD, Linear JSON, Jira XML/CSV, or generic markdown
folder) into a claw-forge spec file (`app_spec.txt` or `additions_spec.xml`).

#### When to use
- You have BMAD planning output (`prd.md`, `architecture.md`, `stories/`)
- You exported issues from Linear as JSON
- You exported tickets from Jira as XML or CSV
- You have a folder of markdown files describing features

#### Usage
```bash
# Auto-detect format and convert
claw-forge import ./bmad-output

# Skip confirmation prompt
claw-forge import ./bmad-output --yes

# Use a faster model
claw-forge import ./bmad-output --model claude-sonnet-4-6

# Write to a custom filename
claw-forge import ./bmad-output --out my-spec.xml

# Point at a different project directory
claw-forge import ./linear-export.json --project ~/projects/myapp
```

#### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `path` | positional | **required** | Path to harness output folder or file |
| `--project`, `-p` | path | `.` | Project directory (for brownfield detection + output) |
| `--model`, `-m` | string | `claude-opus-4-6` | Model for Claude conversion calls |
| `--yes`, `-y` | flag | `False` | Skip format confirmation prompt |
| `--config`, `-c` | path | `claw-forge.yaml` | Config file path |
| `--out`, `-o` | string | `""` | Output filename (default: auto — `app_spec.txt` or `additions_spec.xml`) |

#### What it does internally
1. Scans the path and detects format (BMAD / Linear / Jira / generic) with confidence score.
2. Shows the detected format and asks for confirmation (unless `--yes`).
3. Extracts epics, stories, tech stack, DB schema, and API endpoints using format-specific rules.
4. Calls Claude once per XML section (overview+tech, core features per epic, DB+API, steps+criteria).
5. Detects greenfield vs brownfield from presence of `brownfield_manifest.json`.
6. Writes `app_spec.txt` (greenfield) or `additions_spec.xml` (brownfield).
7. Shows output stats and next steps.

#### Output example
```
Scanning ./bmad-output...
✓ Detected: BMAD output — prd.md + architecture.md + 2 epics (5 stories)
  Confidence: high

Proceed with import? [Y/n]: Y

Extracting structure...  ✓  2 epics, 5 stories
Converting to spec via Claude...  ✓
Auto-detected: greenfield (no brownfield_manifest.json found)

✓ Written: app_spec.txt
  Features: 23 bullets across 2 categories
  Epics:    2 implementation phases

Next steps:
  1. Review app_spec.txt
  2. claw-forge validate-spec app_spec.txt
  3. claw-forge plan app_spec.txt
```

#### Pro tips
- Use `--yes` in scripts and CI pipelines to skip the confirmation prompt.
- For interactive section-by-section review, use `/import-spec` in Claude Code instead.
- Run `claw-forge analyze` first on brownfield projects to generate `brownfield_manifest.json`.
- The converter uses one Claude call per section to avoid context truncation on large specs.

#### Related commands
- **Before:** `claw-forge analyze` (brownfield), BMAD / Linear / Jira planning tools
- **Interactive version:** `/import-spec` slash command
- **After:** `claw-forge validate-spec`, `claw-forge plan`

---

### `claw-forge run`

#### Purpose
Starts the agent pool, dispatches features from the state DB to coding agents in parallel, and
drives the full implementation loop (code → test → review → merge).

#### When to use
- After `claw-forge plan` to begin building a new project
- After `claw-forge add` or `/expand-project` to build newly added features
- When resuming after an interruption — orphaned `running` tasks from the previous session are automatically reset to `pending` and retried
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

# Use hashline edit mode — dramatically improves weaker models
# (6.7% → 68.3% benchmark on Grok Code Fast, see docs/agent-skill.md)
claw-forge run --edit-mode hashline
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
| `--edit-mode` | string | `str_replace` | Edit tool format: `str_replace` (default) or `hashline` (content-addressed, better for weaker models) |
| `--loop-detect-threshold` | int | `5` | Max edits to a single file before the LoopDetectionMiddleware injects a "reconsider" prompt. Set to `0` to disable. When `--edit-mode hashline` is active, threshold auto-raises by 3 (e.g. 5 → 8). |
| `--verify-on-exit/--no-verify-on-exit` | flag | `True` | Inject a pre-completion verification checklist before the agent exits — forces re-reading the spec, running tests, and confirming correctness. Disable for fast iteration / debugging. |
| `--auto-push` | string | `None` (disabled) | Automatically `git push` to remote after agent completion. Value: path to git repo (uses `origin` by default), or `path:remote` for a custom remote. Skipped silently if the path is not a git repo or the remote doesn't exist. **Off by default — must be explicitly opted in.** |

#### What it does internally
1. Loads `claw-forge.yaml`, expands `${ENV_VAR}` placeholders.
2. Connects to the state service (starts one if not running).
3. Pulls the feature queue: tasks with status `pending`, `failed`, or `running` (orphaned from a previous interrupted run).
4. Resets any orphaned `running` tasks back to `pending` in the DB so the UI reflects the true state.
5. Spawns up to `--concurrency` Claude Code agent sessions via the provider pool.
6. Each agent runs the TDD loop: write tests → make them pass → commit.
7. On completion, updates feature status in the state DB (Passing / Failed / Blocked).
8. If a feature is Blocked, prompts for human input (unless `--yolo`).
9. Continues until the queue is empty or all remaining features are Blocked/Failed.

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

#### Failure modes — `resume_conflict`

When a previously-interrupted task is resumed, the dispatcher attempts a catch-up merge of the target branch into the feature branch *before* the agent runs (via `sync_worktree_with_target` in `claw_forge/git/merge.py`). This eliminates the prior failure pattern where the catch-up only happened at squash time, after the agent had already wasted a turn on stale state.

If the catch-up hits real content conflicts — both `target_branch` and the resumed feature branch modified the same lines of the same file since they diverged — the task is marked `failed` immediately with an `error_message` of the form:

```
resume_conflict: catch-up merge of main into branch failed on N file(s):
foo.py, bar.py. Resolve manually in <worktree-path> (run `git merge main`,
fix conflicts, commit) and requeue the task.
```

The worktree is preserved on disk so you can resolve manually:

```bash
cd .claw-forge/worktrees/<slug>
git merge <target>           # produces conflict markers
# resolve in your editor
git add -A && git commit --no-verify
```

Then requeue the task — click 'Reset All' on the Failed column in the Kanban UI, or POST to the state service: `curl -X POST http://localhost:8420/sessions/$SESSION_ID/tasks/requeue -d '{"statuses":["failed"]}' -H 'Content-Type: application/json'`. The next dispatch syncs cleanly because the resolution commit is now on the feature branch.

If the partial work is throwaway, use `claw-forge worktrees prune --discard` to drop the branch and worktree; the task's next retry will recreate them from current `target_branch`.

A second `resume_conflict` shape — `dirty_worktree: True` — appears when the worktree has uncommitted edits left over from an interrupted run. The dispatcher refuses to merge over uncommitted state to avoid silently overwriting the user's edits; commit or discard them inside the worktree, then requeue.

#### Related commands
- **Before:** `claw-forge plan`, `claw-forge state`
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
6. Shows the next command: `claw-forge run`.

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

  Next: claw-forge run --project .
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

## Kanban Board Overview

![Kanban board overview](../website/assets/screenshots/kanban-overview.png)
*The Kanban board shows all features across 5 columns: Pending, Running, Passing, Failed, Blocked*

### Dark Mode

![Dark mode](../website/assets/screenshots/kanban-dark.png)

### Command Palette (⌘K / Ctrl+K)

![Command palette](../website/assets/screenshots/command-palette.png)
*Press ⌘K (Mac) or Ctrl+K (Windows/Linux) to open the command palette*

#### Pro tips
- The Kanban board updates over WebSocket — no refreshing needed.
- The provider health dots (🟢/🟡/🔴) in the header tell you if a provider is circuit-broken.
- Use `--no-open` on a remote machine and tunnel via SSH: `ssh -L 5173:localhost:5173 yourserver`.

#### Related commands
- **Requires:** `claw-forge state` (state service must be running)
- **During:** `claw-forge run`, `claw-forge status`

---

### `claw-forge dev`

#### Purpose
Starts the FastAPI state service (with uvicorn `--reload`) and the Vite HMR dev server in a
single command. Both processes restart automatically on file changes. Optionally also launches
the agent orchestrator with `--run`.

#### When to use
- Developing claw-forge itself and you want hot-reload for both the API and the UI
- Running a project and you want all three processes (state service + UI + agents) from one terminal
- Pointing at a specific project directory to inspect its live state via the Kanban UI

> **Note:** Without `--run`, `claw-forge dev` only starts the servers — it does **not** execute
> agents. Tasks shown as "In Progress" in the UI are from a previous session. Run
> `claw-forge dev --run` (or a separate `claw-forge run`) to drive task execution.

#### Usage
```bash
# State service (hot-reload) + Vite UI only
claw-forge dev

# Also launch the agent orchestrator
claw-forge dev --project /path/to/project --run

# Custom ports
claw-forge dev --state-port 9000 --ui-port 3000

# Point at a different project
claw-forge dev --project ~/projects/my-app

# Don't auto-open browser
claw-forge dev --no-open
```

#### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--ui-port` | int | `5173` | Port for the Vite dev server |
| `--state-port` | int | `8420` | Port for the state service API |
| `--project`, `-p` | path | `.` | Project directory (sets DB path and passes to `run`) |
| `--open/--no-open` | flag | `True` | Auto-open browser after 3s |
| `--session`, `-s` | string | `""` | Session UUID to pre-select on the board |
| `--run/--no-run` | flag | `False` | Also launch `claw-forge run` to execute agents |

#### What it does internally
1. Validates that `ui/` source dir and Node.js are present (requires a source checkout).
2. Runs `npm install` if `ui/node_modules` is missing.
3. Launches `claw-forge state --reload` as a subprocess with `CLAW_FORGE_DB_URL` set.
4. Launches `npm run dev` in `ui/` with `VITE_API_PORT` and `VITE_WS_PORT` set.
5. If `--run` is passed, waits 2 seconds for the state service to start, then launches
   `claw-forge run --project <project>` as a third subprocess.
6. On Ctrl+C, terminates all child processes cleanly.

#### Output example
```
🔥 claw-forge dev (API + UI hot-reload)
   UI:        http://localhost:5173  (Vite HMR)
   State API: http://localhost:8420  (uvicorn --reload)
   Database:  /path/to/project/.claw-forge/state.db
   Session:   a1b2c3d4-...
   Agents:    enabled (--run)
   Press Ctrl+C to stop all servers
```

#### Pro tips
- Use `--run` for a one-command workflow: `claw-forge dev --project . --run` starts everything.
- Without `--run`, tasks stuck in "In Progress" are orphaned from a previous run — re-run
  `claw-forge run` (or use `--run`) to resume them. They will be automatically reset to pending.
- `--reload` means any change to `claw_forge/` Python files restarts the state service instantly.

#### Related commands
- **Requires source checkout:** `ui/` directory must exist
- **Alternative (production UI):** `claw-forge ui` (serves pre-built assets, no Node.js HMR)
- **Agents only:** `claw-forge run` (no UI server)

---

### `claw-forge state`

#### Purpose
Start the AgentStateService REST + WebSocket API. The state service powers the Kanban UI
and exposes REST endpoints for session, task, pool, regression, and command management.

#### When to use
- Running the state service standalone (instead of letting `claw-forge run` auto-start it)
- Connecting a PostgreSQL database instead of the default SQLite
- Development mode with hot-reload (`--reload`)
- Running the state service on a custom port or host

#### Usage
```bash
# Start on default port 8420
claw-forge state

# Start with hot-reload for development
claw-forge state --reload

# Start on a custom port, local-only
claw-forge state --port 9000 --host 127.0.0.1

# Start with PostgreSQL
claw-forge state --database-url postgresql+asyncpg://user:pass@host/db
```

#### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--port` | int | `8420` | Port to bind the state service on |
| `--host` | string | `0.0.0.0` | Host to bind (use `127.0.0.1` for local-only) |
| `--project`, `-p` | path | `.` | Project directory |
| `--config`, `-c` | path | `claw-forge.yaml` | Path to YAML config |
| `--reload` | flag | `False` | Enable hot-reload — restart on Python file changes (dev only) |
| `--database-url` | string | `None` | Database URL override (e.g. `postgresql+asyncpg://user:pass@host/db`). Default: SQLite in `.claw-forge/state.db` |

#### What it does internally
1. Loads `claw-forge.yaml` for project metadata and provider config.
2. Starts a uvicorn server with the FastAPI state service app.
3. Creates SQLite database at `.claw-forge/state.db` (or connects to the provided `--database-url`).
4. Exposes REST endpoints for sessions, tasks, pool status, and regression.
5. Opens WebSocket at `/ws` for real-time event broadcasting to the Kanban UI.
6. With `--reload`, watches Python source files and restarts on changes.

#### Related commands
- **Uses:** `claw-forge ui` (connects to the state service for the Kanban board)
- **Alternative:** `claw-forge dev` (starts state + UI + agents together)

---

### `claw-forge pause`

#### Purpose
Pause a running project in drain mode — in-flight agents complete their current task,
but no new tasks are dispatched.

#### When to use
- You want to review generated code before more features are built
- A provider is rate-limited and you want to wait before continuing
- You're about to make manual changes and don't want agents conflicting

#### Usage
```bash
# Pause by session ID
claw-forge pause abc-123-def

# Pause on a custom port
claw-forge pause abc-123-def --port 9000
```

#### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `project` | positional | **required** | Session ID or project name to pause |
| `--port` | int | `8420` | State service port |

#### What it does internally
1. Sends a pause request to the state service.
2. In-flight agents finish their current task (drain mode).
3. No new tasks are dispatched until `claw-forge resume` is called.
4. The Kanban UI reflects the paused state.

#### Related commands
- **Resume:** `claw-forge resume`
- **Status:** `claw-forge status` (check progress while paused)

---

### `claw-forge resume`

#### Purpose
Resume a paused project — the dispatcher starts accepting new tasks again.

#### When to use
- After `claw-forge pause` when you're ready to continue
- After reviewing Wave 1 output and approving the approach

#### Usage
```bash
# Resume by session ID
claw-forge resume abc-123-def

# Resume on a custom port
claw-forge resume abc-123-def --port 9000
```

#### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `project` | positional | **required** | Session ID or project name to resume |
| `--port` | int | `8420` | State service port |

#### What it does internally
1. Sends a resume request to the state service.
2. The dispatcher immediately begins picking up pending tasks.
3. Tasks queued during the pause are dispatched in dependency order.

#### Related commands
- **Pause:** `claw-forge pause`
- **Monitor:** `claw-forge status`, `claw-forge ui`

---

### `claw-forge input`

#### Purpose
List pending human-input questions and answer them interactively. Agents that get stuck
post a question to the state service; this command shows those questions and lets you
respond, unblocking the agent.

#### When to use
- A feature moved to "Blocked" in the Kanban UI
- An agent needs an API key name, design decision, or clarification
- You see `needs_human` status on a task

#### Usage
```bash
# Answer questions for a session
claw-forge input abc-123-def

# On a custom port
claw-forge input abc-123-def --port 9000
```

#### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `project` | positional | **required** | Session ID or project name |
| `--port` | int | `8420` | State service port |

#### What it does internally
1. Fetches all tasks with `needs_human` status from the state service.
2. Displays each question with the task name and context.
3. Prompts you for an answer interactively.
4. POSTs your answer to `/sessions/{id}/tasks/{id}/human-input`.
5. The task moves back to `pending` and the dispatcher retries it with your answer injected.

#### Output example
```
🙋 1 pending question for 'taskflow-api':

Task: Email reminders
Q: What is the SendGrid API key env var name?
Your answer: SENDGRID_API_KEY

✅ Answer submitted — task moved to pending
```

#### Related commands
- **YOLO mode:** `claw-forge run --yolo` skips human-input gates entirely
- **Monitor:** `claw-forge status` (shows blocked features)

---

### `claw-forge merge`

#### Purpose
Squash-merge a feature branch to the target branch. Used with `merge_strategy: manual`
in `claw-forge.yaml` to control when completed features land on main.

#### When to use
- You've set `merge_strategy: manual` and want to land a completed feature
- You want to review each feature branch before merging
- You need to merge into a branch other than `main` (e.g. `develop`)

#### Usage
```bash
# List feature branches ready to merge
claw-forge merge

# Squash-merge a specific branch to main
claw-forge merge feat/user-auth

# Merge into a custom target branch
claw-forge merge feat/user-auth --target develop

# Specify project directory
claw-forge merge feat/user-auth --project ~/projects/taskflow-api
```

#### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `branch` | positional | `None` | Branch to squash-merge. If omitted, lists available feature branches. |
| `--project`, `-p` | path | `.` | Project directory |
| `--target`, `-t` | string | `main` | Target branch to merge into |

#### What it does internally
1. If no branch is specified, lists branches matching the feature prefix (e.g. `feat/`).
2. Checks out the target branch.
3. Runs `git merge --squash <branch>` to squash all commits into one.
4. Creates a semantic commit message with completed steps, task ID, and session trailers.
5. Cleans up the feature branch and its git worktree (if one exists).

#### Pro tips
- With `merge_strategy: auto` (the default), features are squash-merged automatically on
  passing — you don't need this command.
- Use `merge_strategy: manual` when you want human review of each feature before landing.
- Run `claw-forge merge` (no args) to see which branches are ready.

#### Related commands
- **Before:** `claw-forge run` (features must be passing)
- **After:** `/check-code`, `git push`

---

### `claw-forge version`

#### Purpose
Print the installed claw-forge version.

#### Usage
```bash
claw-forge version
```

#### Output example
```
claw-forge 0.2.0b1
```

---

### `claw-forge export`

#### Purpose
Export session and task data from `state.db` to CSV (flat or per-table), SQL (sqlite-importable
dump), or JSON. Pure SQLite reads — no state service dependency, safe to run while a session is
active.

#### When to use
- Cost / progress reports for stakeholders
- Spreadsheet analysis of agent activity (per-task, per-category, per-provider)
- Backups of completed sessions before pruning the state DB
- Migrating session history to another machine via SQL round-trip

#### Usage
```bash
# Latest session, flat CSV (default)
claw-forge export

# All sessions as SQL dump (importable via `sqlite3 newdb.db < out.sql`)
claw-forge export --format sql --scope all --out backup.sql

# Specific session as JSON
claw-forge export --format json --session 8d304d81-... --out session.json

# CSV split (one file per table: sessions.csv, tasks.csv, events.csv)
claw-forge export --csv-mode split --out ./out/
```

#### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--format` | choice | `csv` | `csv` / `sql` / `json` |
| `--scope` | choice | `session` | `session` (latest) or `all` (every session in DB) |
| `--csv-mode` | choice | `flat` | `flat` (one denormalized row per task) or `split` (one CSV per table) |
| `--session` | str | latest | Specific session UUID; overrides `--scope=session`'s "latest" pick |
| `--out` | path | auto | Output path (auto-generated if omitted, e.g. `taskflow-2026-04-30.csv`) |
| `--project` | path | CWD | Project root containing `.claw-forge/state.db` |

#### What it does internally
1. Opens `.claw-forge/state.db` read-only via `sqlite3`.
2. Resolves the session(s) to export from `--scope` / `--session`.
3. For each format:
   - **csv flat**: denormalized join of `sessions × tasks` columns → one row per task.
   - **csv split**: three files — `sessions.csv`, `tasks.csv`, `events.csv` — mirroring the raw schema.
   - **sql**: standard SQLite dump (`CREATE TABLE IF NOT EXISTS` + `INSERT`); round-trippable via `sqlite3 newdb.db < out.sql`.
   - **json**: nested shape — `{exported_at, claw_forge_version, scope, sessions: [{..., tasks: [...]}]}`.
4. Writes to `--out` (or auto-generated filename) and prints the path.

#### Related commands
- **Inspect interactively:** `claw-forge status` for a Rich-table summary
- **Live state:** the Kanban UI (`claw-forge ui`) for real-time activity

---

### `claw-forge boundaries`

#### Purpose
Identify and refactor extension hotspots in target codebases — files where many concurrent
features are forced to edit the same lines (CLI dispatchers, parsers, route tables).
Converts those surfaces into plugin-extensible patterns so future tasks become "drop a new
file" instead of "edit the shared dispatcher."

This is a one-shot maintenance command, not part of every `claw-forge run`. Use when your
audit / log review reveals a recurring conflict choke point.

#### Subcommands
- **`audit`** — read-only; emit a ranked hotspot report
- **`apply`** — refactor hotspots one at a time, test-gated, squash-merge on green
- **`status`** — show the last audit's hotspot list

---

#### `claw-forge boundaries audit`

##### Usage
```bash
# Default: scan CWD, write boundaries_report.md
claw-forge boundaries audit

# Custom project + lower threshold
claw-forge boundaries audit --project /path/to/repo --min-score 3.0

# Custom output path
claw-forge boundaries audit --out reports/hotspots.md
```

##### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--project` | path | CWD | Project root to audit |
| `--min-score` | float | `5.0` | Minimum hotspot score to include in the report |
| `--out` | path | `<project>/boundaries_report.md` | Override the output path |

##### What it does internally
1. Walk source files via `git ls-files` (respects `.gitignore` + `boundaries.ignore_paths`).
2. Compute four signals per file:
   - **dispatch_score** — string-keyed `if/elif/match` branches (registry candidates)
   - **import_centrality** — distinct files importing this one (blast radius)
   - **recent_churn** — distinct branches that touched this file in the last 90 days
   - **function_centrality** — call-site fanout for each public top-level function
3. Composite weighted score (defaults: dispatch 0.4, churn 0.3, import 0.2, function 0.1).
4. Filter at or above `--min-score`, sort descending.
5. (Optional) classifier subagent labels each hotspot with one of four refactor patterns:
   `registry`, `split`, `extract_collaborators`, `route_table`.
6. Emit a markdown report with one section per hotspot.

##### Output example
```
Wrote /path/to/project/boundaries_report.md with 3 hotspot(s) (min score 5.0).
```

The generated `boundaries_report.md`:
```markdown
# Boundaries Audit — myapp

3 hotspot(s) identified.

## 1. cli/main.py  (score 8.7)
- signals: dispatch=10, import=6, churn=14, function=3
**Proposed pattern:** registry

## 2. parser.py  (score 6.2)
...
```

---

#### `claw-forge boundaries apply`

##### Usage
```bash
# Interactive — prompts before each hotspot
claw-forge boundaries apply

# Run only one named hotspot (recommended for first runs)
claw-forge boundaries apply --hotspot cli/main.py

# Fully autonomous — applies all hotspots in score order
claw-forge boundaries apply --auto

# Custom test command (default: `uv run pytest tests/ -q`)
claw-forge boundaries apply --test-command "npm test"
```

##### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--project` | path | CWD | Project root |
| `--test-command` | str | `uv run pytest tests/ -q` | Test command run inside each refactor's worktree |
| `--hotspot` | str | (all) | Apply only this one named hotspot path |
| `--auto` | flag | `false` | No prompts; apply all hotspots in score order |

##### What it does internally
For each hotspot in the report:

1. **`create_worktree`** → isolated branch + worktree under `.claw-forge/worktrees/`.
2. **Subagent dispatch** → claude-agent-sdk `query()` with a pattern-specific prompt (registry / split / extract / route_table). Subagent edits files inside the worktree only.
3. **Stage and commit** with `--no-verify` on the boundaries branch.
4. **Test gate** — runs `--test-command` inside the worktree so it sees the refactored code.
5. **Green** → `squash_merge` to `main` (reuses `claw-forge run`'s squash-merge plumbing); worktree + branch removed.
6. **Red** → cleanup, `main` untouched, refactor reverted.

##### Safety properties
- Reuses claw-forge's existing git plumbing (`create_worktree`, `squash_merge`, `remove_worktree`), so the v0.5.24 worktree-checkout fix and the v0.5.27 empty-squash detection apply automatically.
- Refactors run **serially** (refactor B may depend on refactor A's output); never in parallel.
- Subagents are sandboxed via the existing `make_can_use_tool` permission callback — file writes restricted to `project_dir`.
- Each hotspot's outcome is reported: `merged` / `reverted` / `skipped` (with reason).

##### First-run advice
For your first apply against a real codebase, use `--hotspot=<one_known_safe_file>` to validate the test command and the agent's behavior end-to-end before unleashing `--auto`.

---

#### `claw-forge boundaries status`

##### Usage
```bash
claw-forge boundaries status
claw-forge boundaries status --project /path/to/repo
```

Reads `boundaries_report.md` and prints the hotspot list with paths, scores, and proposed patterns. Exits 1 if no report is present (with instructions to run `audit`).

---

### Related commands
- **Diagnose merge conflicts:** if features keep conflicting, run `claw-forge boundaries audit` to see whether they're all editing the same hotspot file.
- **Spec-time prevention:** `/create-spec` Phase 3.5 lets you serialize known-overlapping features at spec creation, complementing the structural fix that `boundaries apply` provides.

---

### `claw-forge worktrees`

#### Purpose
Inspect and clean up the per-task feature-branch worktrees claw-forge creates under
`.claw-forge/worktrees/`. Worktrees from terminally-failed tasks (no further retry will
land) and from completed tasks whose squash-merge itself failed are **not** auto-salvaged
at startup — `claw-forge run`'s salvage hook only fires when a prior run was *interrupted*
(`orphans_reset > 0`). This subcommand fills that gap so you can act on the residue
without resorting to manual `git worktree remove` loops.

#### Subcommands
- **`list`** — show every worktree directory with branch + commit count
- **`prune`** — squash-merge branches with commits to *target*, then remove the dirs
- **`prune --discard`** — force-remove every directory + branch without salvage

---

#### `claw-forge worktrees list`

##### Usage
```bash
# From the project directory
claw-forge worktrees list

# Different project / target / prefix
claw-forge worktrees list --project /path/to/repo --target develop --prefix feature
```

##### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--project`, `-p` | path | CWD | Project root containing `.claw-forge/worktrees/` |
| `--target` | str | auto-detected via `git symbolic-ref refs/remotes/origin/HEAD` | Branch to count commits ahead of |
| `--prefix` | str | `feat` | Feature-branch prefix used by `create_worktree` |

##### Output
For each directory under `.claw-forge/worktrees/`:
- Bold branch name + commit count when the branch has commits ahead of target
- Up to 5 commit subjects (the rest summarised as `… N more`)
- Dim `empty` row when the branch is missing or has no commits

Trailing summary line: `<N> worktree(s) total — <K> salvageable, <N-K> empty.`

---

#### `claw-forge worktrees prune`

##### Usage
```bash
# Salvage anything with commits, then drop empty dirs
claw-forge worktrees prune

# Force-remove everything; discard committed agent work
claw-forge worktrees prune --discard

# Custom project / target
claw-forge worktrees prune --project /path/to/repo --target develop
```

##### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--project`, `-p` | path | CWD | Project root |
| `--target` | str | auto-detected | Squash-merge target branch |
| `--prefix` | str | `feat` | Feature-branch prefix |
| `--discard` | flag | off | Skip salvage; force-remove every dir + branch |

##### What it does internally

**Default (no flag):**
1. Call `merge_orphaned_worktrees(project, prefix=prefix, target=target)` — for each branch with commits ahead of target, run the same `squash_merge` flow `claw-forge run` uses (auto-rebase on conflict, no-op detection on empty squash, orphan-untracked-file sidelining).
2. Call `prune_worktrees(project)` — `git worktree remove --force` every remaining directory and run `git worktree prune` to clean git's bookkeeping.

**`--discard`:**
1. For each directory: `git worktree remove --force <dir>` → `shutil.rmtree` fallback if needed → `git branch -D feat/<slug>`.
2. `git worktree prune` to clean residual entries in `.git/worktrees/`.

##### When to use
- After upgrading past a merge-handler bug that left tasks stuck in `failed` with committed work on `feat/...` branches.
- Before re-running a session you don't intend to resume — strips stale worktrees so the next dispatch starts from a clean state.
- For triage when `claw-forge status` shows many `failed` tasks and you want to inspect (or drop) the work the agents had committed.

##### Safety notes
- Default mode (no `--discard`) is non-destructive of *work*: if a branch has commits, they land on `target` before the directory is removed. The branches themselves disappear only after a successful salvage merge; merge-failed branches are preserved for manual resolution.
- `--discard` deletes *both* the worktree and the branch. Committed work on a discarded branch is gone unless you've already merged or backed it up. Use this only when you're sure the agent's output is throwaway.

---

#### Smart-mode startup cleanup (`git.cleanup_orphan_worktrees: smart`)

The CLI command above is the *manual* cleanup surface. The same machinery is available as an *automatic* startup hook, opt-in via `claw-forge.yaml`:

```yaml
git:
  merge_strategy: auto                   # required for smart cleanup to act
  cleanup_orphan_worktrees: smart        # default: manual
  llm_conflict_proposals: false          # opt-in advisor (see below)
  llm_conflict_advisor_model: ""         # optional model override; blank = SDK default
```

In `manual` (default), `claw-forge run` startup only fires the salvage path when `orphans_reset > 0` — i.e. when the previous run was *interrupted* and tasks got reset. Worktrees from terminally-failed tasks and from `completed` tasks whose squash-merge itself failed accumulate forever.

In `smart`, startup walks every directory under `.claw-forge/worktrees/`, looks the corresponding task up by slug in the DB, and dispatches per the table:

| `task.status` | branch has commits | action | rationale |
|---|---|---|---|
| `pending` | yes | **preserve** | resume substrate for `git.prefer_resumable` |
| `pending` | no | **remove** | empty branch, nothing to keep |
| `running` | any | **preserve** | the legacy `orphans_reset` path will reset & own this |
| `failed` | yes | **salvage** | terminal — no auto-retry across runs in claw-forge |
| `failed` | no | **remove** | empty branch |
| `completed` | yes | **salvage** | the v0.5.35 bug class: squash failed previously |
| `completed` | no | **remove** | bookkeeping cleanup |
| no matching task | yes | **salvage** | orphan from prior session |
| no matching task | no | **remove** | no value, no owner |

Salvage uses the same `squash_merge` plumbing as a normal task completion (catch-up rebase on stale-target divergence, no-op detection, orphan-untracked-file sidelining). On real content conflict, the worktree + branch are preserved and reported to the user — smart mode never silently writes a half-resolved merge.

When `git.llm_conflict_proposals: true`, the advisor (see below) drafts a `CONFLICT_PROPOSAL.md` inside the preserved worktree on conflict.

##### When NOT to use `smart`

- You rely on per-branch state for retry-resume beyond what survives a squash-merge to `main` (custom checkpoint files outside the worktree, agent state caches, etc.). Salvage moves the work to `main` and removes the branch; the next attempt creates a fresh worktree from `main`.
- Your `merge_strategy` is `manual`. Smart mode is a no-op in that case (it never auto-merges) — set `cleanup_orphan_worktrees: manual` to keep the existing scan-and-report behaviour.

#### LLM conflict advisor (`git.llm_conflict_proposals: true`)

When smart-mode salvage hits a content conflict, the advisor:

1. Finds the files modified on both sides since the merge-base.
2. Reads the ancestor, target, and branch versions of each.
3. Sends them to `claude_agent_sdk` (one short conversation, no tools, no MCP) with the task description and a structured-output prompt.
4. Writes the agent's draft to `<worktree>/CONFLICT_PROPOSAL.md`.

The proposal contains a per-file resolution + reasoning + a `bash` block the user can adapt to apply it. Nothing the advisor produces lands on `main` automatically — the user reviews, edits, and applies. The asymmetric cost of a silently-wrong auto-merge (regression on `main` you find out about hours later) is why this is advisory rather than authoritative.

Off by default. Costs one agent call per conflicted worktree; budget accordingly on large multi-feature sessions.

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
(brownfield). The output becomes the input to `claw-forge plan` (greenfield) or `claw-forge add` (brownfield).

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
  2. Run: claw-forge plan app_spec.txt
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
- **After:** `claw-forge plan` (greenfield) or `claw-forge add` (brownfield)

---

### `/import-spec`

#### Purpose
Interactive section-by-section review of a 3rd-party harness export before writing — same
pipeline as `claw-forge import` but with approval gates at each XML section.

#### When to use
- You want to review and optionally edit each converted section before it's written
- You want to verify the extractor found the right epics and stories
- You prefer interactive control over a one-shot command

#### Usage
In Claude Code chat panel:
```
/import-spec ./bmad-output
/import-spec ./linear-export.json --model claude-sonnet-4-6
```

#### What it does internally
Steps through 5 stages — detect, extract, convert section by section (with approve/edit/skip
at each), write, suggest next steps. Each XML section is shown for review before being
committed to the output file.

#### Related commands
- **Non-interactive version:** `claw-forge import`
- **After:** `claw-forge validate-spec`, `claw-forge plan`

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

---

## Middleware Reference

claw-forge ships three composable hook-based middleware layers, all activated via `claw-forge run` flags.

**Key insight:** `loop_detect_threshold=5` and `verify_on_exit=True` are **on by default**. The only explicit opt-in is `--edit-mode hashline`. Running `claw-forge run --edit-mode hashline` gives you the full Config E stack.

---

### Hashline Edit Mode (`--edit-mode hashline`)

**What it does:** Replaces exact-text `str_replace` editing with content-addressed line references. Every file the agent reads gets annotated with 3-char SHA256 hashes; the agent references lines by hash rather than reproducing their exact text.

**The problem it solves:** `str_replace` requires the agent to reproduce an exact substring — whitespace, indentation and all. This fails constantly on indented code (Python, YAML, Rust), long sessions where the model's recall degrades, and weaker/faster models that hallucinate whitespace.

**Benchmark impact:** 6.7% → 68.3% on Grok Code Fast. On Opus 4.6, it's what enables Config E to reach 100% (vs 96.7% without it).

**When to use:**
- Weaker or faster models (Sonnet, Haiku, local models) — removes exact-match failure mode entirely
- Python/YAML/Rust heavy codebases — where indentation errors are common
- Long unattended runs (CI, overnight, `--auto-push`) — no edit-rejection loops at 3 AM
- Any production/evaluation run — it's strictly more reliable

**When to skip:**
- Debugging agent edit behaviour (hash annotations add log noise)
- Reviewing diffs as plain patches (hashline blocks aren't unified diff format)
- Auto-generated or minified files (annotations are noise on long lines)

**Full use-case guide:** [`docs/middleware/hashline.md`](middleware/hashline.md)

```bash
# Recommended — full Config E (loop-detect + verify-on-exit are on by default)
claw-forge run --edit-mode hashline

# Stay on str_replace (middleware still runs)
claw-forge run

# Debug mode — all middleware off
claw-forge run --no-verify-on-exit --loop-detect-threshold 0
```

---

### LoopDetectionMiddleware (`--loop-detect-threshold`)

**What it does:** Tracks how many times each file has been edited in the current agent session. When a single file exceeds the threshold, the middleware injects a structured "reconsider" prompt via the `PostToolUse` hook — breaking the agent out of doom loops before they waste tokens.

**When it fires:**
- After any `Edit` or `MultiEdit` tool use
- When `edit_count[file] >= loop_detect_threshold`

**Threshold auto-boost:** When `--edit-mode hashline` is active, the effective threshold is raised by 3 (e.g. default 5 → 8), because hashline legitimately produces more edits per file (individual line replacements).

**Disabling:** `--loop-detect-threshold 0` turns it off entirely.

**Design doc:** [`docs/middleware/loop-detection.md`](middleware/loop-detection.md)

```bash
# Use with a tighter threshold (high-risk project, big files)
claw-forge run --loop-detect-threshold 3

# Disable loop detection entirely (fast iteration mode)
claw-forge run --loop-detect-threshold 0
```

---

### PreCompletionChecklistMiddleware (`--verify-on-exit / --no-verify-on-exit`)

**What it does:** Intercepts the `Stop` event before the agent exits and injects a structured verification checklist. The agent must re-read the task spec, confirm all acceptance criteria are met, run tests, and explicitly state it has verified — before the session closes.

**Effect:** Dramatically reduces "ships passing but incomplete" — agents that claim done without actually checking.

**Disabling:** `--no-verify-on-exit` skips the checklist entirely (useful during debugging).

**Design doc:** [`docs/middleware/pre-completion-checklist.md`](middleware/pre-completion-checklist.md)

```bash
# Default — checklist runs on every exit
claw-forge run

# Disable for fast iterative runs where you'll verify manually
claw-forge run --no-verify-on-exit
```

---

### AutoPush (`--auto-push`)

**What it does:** After the agent session completes, runs `git push` to push the agent's commits to a remote.

**Default: disabled.** Must be explicitly opted in — never pushes without `--auto-push` being set.

**Guards (all must pass before pushing):**
1. Path must be a git repository (has `.git/`)
2. Specified remote must exist (`git remote` check)
3. Push failure is caught and logged — never crashes the session

```bash
# Push to origin (default remote)
claw-forge run --auto-push /path/to/repo

# Push to a custom remote
claw-forge run --auto-push /path/to/repo:upstream

# Via claw-forge.yaml config (also off by default)
# [agent]
# auto_push = "/path/to/repo"
```

**Design doc:** [`docs/middleware/pre-completion-checklist.md`](middleware/pre-completion-checklist.md)

---

### Combining middleware — defaults are already Config E

`loop_detect_threshold=5` and `verify_on_exit=True` are **on by default**. You get the full middleware stack without any flags:

```bash
# This is already Config E — loop detection + verify-on-exit are on by default
claw-forge run --edit-mode hashline
```

The only flag you need to opt into is `--edit-mode hashline` (changes the edit tool format).
To disable middleware for fast debugging:

```bash
claw-forge run --no-verify-on-exit --loop-detect-threshold 0
```

With auto-push for fully autonomous workflows (explicit opt-in — network write):

```bash
claw-forge run --edit-mode hashline --auto-push /path/to/repo
```

**Config E** (`hashline` + `loop-detect=5` + `verify-on-exit`) achieves **100%** on claw-forge-bench (30 tasks, `claude-opus-4-6`) — and it's the default minus one flag.

See [`docs/benchmarks/results.md`](benchmarks/results.md) for full ablation results across configs A–E.

---

## See Also

- [docs/workflows.md](workflows.md) — End-to-end workflow walkthroughs
- [docs/brownfield.md](brownfield.md) — Brownfield mode deep dive
- [docs/middleware/loop-detection.md](middleware/loop-detection.md) — LoopDetectionMiddleware design
- [docs/middleware/pre-completion-checklist.md](middleware/pre-completion-checklist.md) — PreCompletionChecklistMiddleware design
- [docs/benchmarks/terminal-bench.md](benchmarks/terminal-bench.md) — Terminal Bench 2.0 eval harness
- [README.md](../README.md) — Project overview and quick start
