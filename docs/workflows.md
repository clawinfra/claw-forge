# claw-forge Workflows

End-to-end walkthroughs for common development scenarios. Each workflow shows the exact
commands, what happens at each step, and what the agents do autonomously.

For individual command details, see [docs/commands.md](commands.md).

---

## Workflow 1: Greenfield — Build a New App from Scratch

**Pipeline:** `claw-forge init` → `/create-spec` → `claw-forge plan` → `claw-forge run` → `/check-code` →
`/checkpoint` → `/review-pr`

**Scenario:** You're building "TaskFlow API" — a FastAPI + SQLite REST API for personal
task management with JWT auth, project grouping, and email reminders.

---

### Step 1: Scaffold the project

```bash
mkdir taskflow-api && cd taskflow-api
git init
claw-forge init
```

**What happens:** claw-forge scaffolds `.claude/commands/` with 8 slash commands,
creates `claw-forge.yaml`, `.env.example`, and `app_spec.example.xml` (XML format reference).

**You see:**
```
✓ Created claw-forge.yaml  (edit providers as needed)
✓ Created .env.example     (copy to .env and fill keys)
⚠  No .env found — copy .env.example → .env and add your API keys
✓ Stack detected: unknown / unknown
✓ Generated CLAUDE.md (tailored to your stack)
✓ Created .claude/ with settings.json
✓ Created app_spec.example.xml  (reference format for your spec)
✓ Scaffolded 8 slash commands → .claude/commands/
  • /create-spec
  • /expand-project
  • /check-code
  • /checkpoint
  • /review-pr
  • /pool-status
  • /create-bug-report
  • /claw-forge-status

Next step: create your project spec.
  Option A — run /create-spec in Claude Code
  Option B — convert your PRD using app_spec.example.xml as the template
  Then run: claw-forge plan app_spec.txt
```

### Step 2: Create the spec interactively

Open Claude Code and type:
```
/create-spec
```

Claude walks you through:
1. **Project identity:** "TaskFlow API — REST API for personal task management"
2. **Audience:** "Individual devs and small teams (up to 10 people)"
3. **Quick vs Detailed:** You choose "Detailed"
4. **Features by category:** Claude asks about each area and generates bullets:

```
Authentication (8 bullets)
- User can register with email and password (returns 201 with user_id)
- System sends verification email on registration
- User can verify email via link (sets email_verified=true)
- User can login and receive JWT access_token + refresh_token
- System rejects login for unverified emails with 403
- User can refresh access token using refresh_token
- User can logout (invalidates refresh token)
- System rate-limits login attempts (5/minute per IP)

Task Management (22 bullets)
- User can create a task with title, description, due_date, priority
- User can list all tasks (paginated, 20 per page)
- User can filter tasks by status (pending/in_progress/done)
- User can filter tasks by priority (low/medium/high)
- User can filter tasks by due date range
- User can search tasks by title (case-insensitive substring)
- ...
```

5. **Tech stack:** FastAPI, SQLite (dev) / PostgreSQL (prod), JWT, pytest
6. **DB schema:** Users, Tasks, Projects, TaskAssignments, Notifications tables

**Output files written:**
- `app_spec.txt` — 59 features across 6 categories, 4 phases, full DB schema
- `claw-forge.yaml` — provider config with `claude-oauth` enabled

### Step 3: Initialize with spec

```bash
claw-forge plan app_spec.txt --concurrency 5
```

**What happens:** The `InitializerPlugin` parses all 59 features from the XML spec, builds
a 4-wave dependency DAG, and registers them in the state DB.

**You see:**
```
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

  Next: claw-forge run --spec app_spec.txt --concurrency 5
```

> **Re-running `claw-forge plan`:** By default, plan reconciles with the existing session —
> completed tasks are preserved, and only new/missing features are added. Use `--fresh` to
> start a clean session from scratch.

### Step 4: Run the agents

```bash
# Option A — one command (state service + UI + agents together)
claw-forge dev --project . --run

# Option B — three separate terminals (more control)
# Terminal 1: start the state service
claw-forge state &

# Terminal 2: start agents
claw-forge run --concurrency 5

# Terminal 3 (optional): watch progress
claw-forge ui
```

**What the agents do autonomously:**
- Wave 1 starts: 5 agents pick up auth features in parallel.
- Each agent follows TDD: writes a failing test → implements → makes it pass → commits.
- When a feature reaches "Passing," the next pending feature from the queue is dispatched.
- Wave 2 begins when Wave 1 dependencies are satisfied.
- If an agent gets stuck (e.g. needs an API key), it posts a human-input question and the
  feature moves to "Blocked."

**You see in the Kanban UI:**
```
┌──────────────┬──────────────┬──────────────┬────────────────┐
│   PENDING    │ IN PROGRESS  │   PASSING    │    BLOCKED     │
│     54       │      5       │     0        │       0        │
├──────────────┼──────────────┼──────────────┼────────────────┤
│ Create task  │ Register     │              │                │
│ List tasks   │ Login        │              │                │
│ Filter tasks │ Email verify │              │                │
│ …            │ Password hash│              │                │
│              │ Rate limit   │              │                │
└──────────────┴──────────────┴──────────────┴────────────────┘
```

After ~24 minutes:
```
Progress: 59/59 passing · 0 in-flight · $3.12 spent
✅ All features complete!
```

### Step 5: Verify code quality

In Claude Code:
```
/check-code
```

**Output:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Code Quality Report — TaskFlow API
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ✅ Ruff lint     — 0 errors, 0 warnings
  ✅ Ruff format   — All files formatted
  ✅ MyPy          — 0 type errors
  ✅ Pytest        — 59 passed, 0 failed

Overall: ALL CLEAR ✅
```

### Step 6: Checkpoint and review

```
/checkpoint
```

```
✅ Checkpoint saved!
  Commit:   4a7f2e1
  Snapshot: .claw-forge/snapshots/snapshot-20250514T143022.json
```

```
/review-pr
```

```
  VERDICT: ✅ APPROVE
  Files changed: 24 · Lines: +3,412 / -0
  🟡 SUGGESTIONS: 2 (docstring improvements)
  ✅ Tests, types, security: all clear
```

Push:
```bash
git push origin main
```

**Total time:** ~30 minutes. **Total cost:** ~$3.12. **Lines of code:** ~3,400.

---

## Workflow 2: Brownfield — Add Features to Existing Codebase

**Pipeline:** `claw-forge analyze` → `/create-spec` (brownfield) → `claw-forge add` →
`/check-code`

**Scenario:** TaskFlow API is live with 59 passing tests. Product wants Stripe payments
so users can subscribe to a Pro plan with higher task limits.

---

### Step 1: Analyze the existing codebase

```bash
cd ~/projects/taskflow-api
claw-forge analyze
```

**What happens:** claw-forge scans git history, runs the test suite, and detects your
conventions. Writes `brownfield_manifest.json`.

**You see:**
```
Analyzing ~/projects/taskflow-api…

  Stack detected:
    Language:   Python 3.12
    Framework:  FastAPI 0.111
    Database:   SQLite (aiosqlite)
    Testing:    pytest + pytest-asyncio

  Test baseline:
    Tests:      59 passing, 0 failing
    Coverage:   91%

  Conventions detected:
    Naming:     snake_case functions, PascalCase models
    Async:      async/await throughout
    Docstrings: Google style

✅ Wrote brownfield_manifest.json
```

**File content (`brownfield_manifest.json`):**
```json
{
  "stack": {
    "language": "python",
    "version": "3.12",
    "framework": "fastapi",
    "database": "sqlite",
    "test_runner": "pytest"
  },
  "test_baseline": {
    "total": 59,
    "passing": 59,
    "failing": 0,
    "coverage": 91.2
  },
  "conventions": {
    "naming": "snake_case",
    "models": "PascalCase",
    "async": true,
    "docstyle": "google",
    "imports": "absolute"
  },
  "hot_files": [
    "routers/tasks.py",
    "services/task_service.py",
    "models/task.py"
  ]
}
```

### Step 2: Create brownfield spec

In Claude Code:
```
/create-spec
```

Claude auto-detects `brownfield_manifest.json` and enters brownfield mode:

```
Claude: I found brownfield_manifest.json — entering brownfield mode.
  Stack: Python 3.12 / FastAPI / SQLite
  Tests: 59 passing, 91% coverage

  What are you adding? Give it a name and one-sentence summary.

You: Stripe Payments — let users subscribe to Pro plan via Stripe Checkout.

Claude: Which parts of the existing code does this touch?

You: Extends User model with stripe_customer_id. Adds /payments router.
     New StripeService class in services/. Webhook endpoint for Stripe events.

Claude: What must NOT change?

You: Auth flow must stay intact. All 59 existing tests must pass.
     No changes to task/project CRUD logic.

Claude: List the features to add:

You:
  - User can add a payment method via Stripe Elements
  - System creates Stripe customer on first payment attempt
  - User can subscribe to Pro plan via Stripe Checkout
  - Webhook processes subscription.created events
  - Webhook processes subscription.deleted events
  - User can access billing portal to manage subscription
  - System enforces task limit (10 for free, unlimited for Pro)
  - User can view current plan and billing history
  - System sends email on successful subscription
  - System sends email on subscription cancellation
  - Admin can view all subscriptions
  - Stripe webhook signature verification on all events
```

**Output — writes `additions_spec.xml`:**
```
✅ Brownfield spec created: additions_spec.xml

📊 Summary:
  Features to add: 12
  Phases: 3 (Stripe integration → Subscription flow → Admin)
  Integration points: 4
  Constraints: 3

Next: claw-forge add --spec additions_spec.xml
```

### Step 3: Add the features

```bash
claw-forge add --spec additions_spec.xml
```

**You see:**
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

  Suggested git branch: feature/stripe-payments

  Next: claw-forge run --spec additions_spec.xml --project .
```

### Step 4: Run and verify

```bash
claw-forge run --concurrency 3
```

After ~8 minutes, all 12 new features pass. The original 59 tests still pass too.

```
/check-code
```

```
  ✅ Ruff lint     — 0 errors
  ✅ Ruff format   — All formatted
  ✅ MyPy          — 0 type errors
  ✅ Pytest        — 71 passed, 0 failed (59 original + 12 new)

Overall: ALL CLEAR ✅
```

**Total time:** ~15 minutes. **Cost:** ~$0.84. **New lines:** ~680.

---

## Workflow 3: Bug Fix — TDD Regression Fix

**Pipeline:** `/create-bug-report` → `claw-forge fix` → `/check-code` → `/review-pr`

**Scenario:** A user reports: "I can't reset my password when my email address has uppercase
letters (e.g. John@example.com). No error is shown, but the reset email never arrives."

---

### Step 1: Create structured bug report

In Claude Code:
```
/create-bug-report user can't reset password with uppercase email
```

Claude walks you through 6 phases:

```
Claude: Phase 1 — What's broken?
You: Password reset silently fails for mixed-case emails.

Claude: Error messages? Frequency?
You: No error shown. Happens 100% of the time for any uppercase email.

Claude: Phase 2 — Exact reproduction steps?
You:
  1. Register with John@example.com
  2. Go to /forgot-password
  3. Enter John@example.com
  4. No reset email arrives
  5. DB shows no password_reset_token created

Claude: Phase 3 — Expected behaviour?
You: Email lookups should be case-insensitive. Reset should always work.

Claude: Phase 4 — Suspected files?
You: auth/service.py — the email lookup in the reset flow.

Claude: Constraints?
You: Don't break existing lowercase email flows. All 71 tests must pass.
```

**Output — writes `bug_report.md`:**
```markdown
# Bug Report: Password reset fails for uppercase emails

## Symptoms
Password reset silently fails when email contains uppercase letters.
No error shown to user. Reset email never sent.
Frequency: 100% reproducible.

## Reproduction Steps
1. Register with email John@example.com
2. Navigate to /forgot-password
3. Enter John@example.com and submit
4. Check inbox — no reset email arrives
5. Query DB: no password_reset_token row for user

## Expected Behaviour
Email lookups are case-insensitive. Reset email sent regardless of case.

## Actual Behaviour
Reset silently fails. No token created, no email sent.

## Affected Files
- auth/service.py (email lookup in password_reset_request)

## Constraints
- Must not break existing lowercase email reset flow
- All 71 existing tests must remain green
```

```
Claude: Ready to fix? (yes/no)
You: yes
```

### Step 2: Run the fix

```bash
claw-forge fix --report bug_report.md
```

**What the agent does (RED → GREEN → REFACTOR):**

**Phase 1 — RED:** Agent writes a failing test:
```python
# tests/test_auth.py
async def test_password_reset_uppercase_email(client, db):
    """Regression: password reset must work for mixed-case emails."""
    # Register with mixed-case email
    await client.post("/auth/register", json={
        "email": "John@Example.com",
        "password": "SecurePass123!"
    })
    # Request reset — should succeed
    resp = await client.post("/auth/forgot-password", json={
        "email": "John@Example.com"
    })
    assert resp.status_code == 200
    # Token should exist in DB
    token = await db.fetchone(
        "SELECT * FROM password_reset_tokens WHERE user_id = ?",
        (user_id,)
    )
    assert token is not None, "Reset token was not created"
```

Runs it: `FAILED` ✅ (proves the bug exists)

**Phase 2 — GREEN:** Agent identifies root cause and fixes it:
```python
# auth/service.py, line 142
# BEFORE:
user = await db.fetchone(
    "SELECT * FROM users WHERE email = ?", (email,)
)

# AFTER:
user = await db.fetchone(
    "SELECT * FROM users WHERE LOWER(email) = LOWER(?)", (email,)
)
```

Runs the new test: `PASSED` ✅

**Phase 3 — REFACTOR:** Runs full suite:
```
72 passed, 0 failed ✅
```

**You see:**
```
🐛 Bug: Password reset fails for uppercase emails
Created branch: fix/password-reset-fails-for-uppercase-emails

Running bug-fix agent…
✅ Bug fix complete
   Files modified: auth/service.py, tests/test_auth.py
   New test: test_password_reset_uppercase_email
```

### Step 3: Verify and review

```
/check-code
```
```
  ✅ All 4 checks passing. 72 tests, 0 failures.
```

```
/review-pr
```
```
  VERDICT: ✅ APPROVE
  Files changed: 2 · Lines: +18 / -1
  ✅ Regression test covers exact bug. Fix is minimal and correct.
```

Push:
```bash
git push origin fix/password-reset-fails-for-uppercase-emails
gh pr create --fill
```

**Total time:** ~5 minutes. **Cost:** ~$0.12.

#### Bugfix dispatch sweep

After the main wave dispatch completes, the dispatcher runs an automatic bugfix sweep to
pick up any pending bugfix tasks that were created during the run. This happens when:
- A regression test fails after a feature lands
- The reviewer flags an issue that needs a fix
- A test-only failure triggers an automatic bugfix task

The sweep ensures bugfix tasks are not left behind when the main feature queue empties.

---

## Workflow 4: Parallel Development — Multi-Agent Feature Sprint

**Pipeline:** `claw-forge run --concurrency 5` → `claw-forge status` → `/pool-status` →
`/checkpoint`

**Scenario:** You're building a large SaaS app with 50 features across 6 phases. You want
to run 5 agents in parallel to finish the whole thing in one sitting.

---

### Step 1: Start the sprint

You've already run `claw-forge plan saas_spec.txt`. The spec has 50 features in 6
waves. Time to go:

```bash
# Terminal 1: state service
claw-forge state &

# Terminal 2: agents
claw-forge run --concurrency 5

# Terminal 3: Kanban board
claw-forge ui
```

**What you see on the board at T+0:**
```
┌──────────────┬──────────────┬──────────────┬────────────────┐
│   PENDING    │ IN PROGRESS  │   PASSING    │    BLOCKED     │
│     45       │      5       │     0        │       0        │
└──────────────┴──────────────┴──────────────┴────────────────┘
Progress: ░░░░░░░░░░░░░░░░  0/50  ·  5 agents  ·  $0.00
```

### Step 2: Monitor mid-sprint

At T+15 minutes, check status:

```bash
claw-forge status
```

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SaaS Platform  ·  claude-sonnet  ·  $4.21 spent
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Phase 1: Auth           ████████████████ 10/10 ✅ complete
  Phase 2: Core CRUD      ████████████░░░░ 9/12  🔄 in progress
  Phase 3: Payments       ░░░░░░░░░░░░░░░░ 0/8   ⏳ pending
  Phase 4: Admin          ░░░░░░░░░░░░░░░░ 0/8   ⏳ pending
  Phase 5: Integrations   ░░░░░░░░░░░░░░░░ 0/7   ⏳ pending
  Phase 6: Polish         ░░░░░░░░░░░░░░░░ 0/5   ⏳ pending

  19/50 features passing · 5 in-flight · $4.21
```

Check provider health:

In Claude Code:
```
/pool-status
```

```
  claude-oauth       🟢 OK     12/∞     100%     1.2s     $0.00
  anthropic-direct   🟢 OK     45/60    99%      0.8s     $4.21

  Total: $4.21 · All providers healthy ✅
```

### Step 3: Mid-sprint checkpoint

At T+30 minutes (30/50 features done), save progress:

```
/checkpoint
```

```
✅ Checkpoint saved!
  Commit:   b3e8f91
  Snapshot: .claw-forge/snapshots/snapshot-20250514T153000.json
  Tests: 30 passing
```

### Step 4: Handle a blocked feature

At T+35 minutes, one feature gets blocked — it needs a Stripe API key the agent doesn't have:

```bash
claw-forge input saas-platform
```

```
🙋 1 pending question(s):

Task: "System creates Stripe customer on payment"
Q: I need the Stripe secret key (sk_test_...) to configure the client.
   Where should I read it from?

Your answer: Read from STRIPE_SECRET_KEY environment variable.
             For tests, use sk_test_mock_12345.

✅ Answer submitted — task moved to pending
```

The agent picks it up immediately and continues.

### Step 5: Sprint complete

At T+45 minutes:
```
Progress: 50/50 passing · 0 in-flight · $7.83 spent
✅ All features complete!
```

Final checkpoint:
```
/checkpoint
/review-pr
```

**Summary:** 50 features, 5 concurrent agents, 45 minutes, $7.83.

---

## Workflow 5: Recovery — Resuming After Interruption

**Pipeline:** `claw-forge status` → `claw-forge run` (resumes) → `/expand-project`

**Scenario:** Your laptop shuts down in the middle of a 50-feature sprint. 28 features were
passing, 5 were in-progress (mid-implementation), and 17 were pending. You reboot and want
to pick up where you left off.

---

### Step 1: Check what happened

```bash
cd ~/projects/saas-platform
claw-forge status
```

**What happens:** claw-forge connects to the state service (which persists to disk). It finds
the interrupted session and shows the exact state at shutdown:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SaaS Platform  ·  INTERRUPTED  ·  $5.10 spent
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Phase 1: Auth           ████████████████ 10/10 ✅
  Phase 2: Core CRUD      ████████████████ 12/12 ✅
  Phase 3: Payments       ████████░░░░░░░░ 4/8   ⚠ interrupted
  Phase 4: Admin          ██░░░░░░░░░░░░░░ 2/8   ⚠ interrupted
  Phase 5: Integrations   ░░░░░░░░░░░░░░░░ 0/7   ⏳ pending
  Phase 6: Polish         ░░░░░░░░░░░░░░░░ 0/5   ⏳ pending

  28/50 passing · 0 in-flight · 5 interrupted

  Interrupted features (will be retried on resume):
    ⚠ "Webhook processes invoice.paid events"  — had partial code
    ⚠ "Admin can view all users"               — test was written
    ⚠ "Admin can disable user accounts"        — not started
    ⚠ "Stripe subscription cancellation"       — code complete, untested
    ⚠ "User can update payment method"         — not started

  Next: claw-forge run (will resume from interrupted state)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Step 2: Resume the run

```bash
# claw-forge run auto-starts the state service if not running, then resumes
claw-forge run --concurrency 5
```

**What happens:**
- `claw-forge run` queries tasks with status `pending`, `failed`, **and `running`** — so orphaned
  tasks from the interrupted session are always picked up.
- The orphaned `running` tasks are reset to `pending` in the DB (and `started_at` cleared)
  so the Kanban UI shows the correct state before agents re-execute them.
- Features that had partial work are retried from scratch (agents are stateless).
- The 28 passing features are NOT re-run.
- **Orphan task adoption:** If the session row was lost (e.g. DB corruption recovery) but task
  rows survived, the state service automatically re-parents orphaned tasks to the new session
  on startup.
- **Regression wait:** Before marking the session complete, the CLI waits up to 60 seconds for
  any in-flight regression tests to finish (`has_pending_work` property on the reviewer). This
  prevents premature "all done" signals when the final bugfix sweep is still running.
- The remaining 17 pending features are queued as normal.

**You see:**
```
Resuming session: saas-platform (28/50 passing, 22 remaining)
  Resetting 5 orphaned task(s) from previous interrupted run

Dispatching wave 3/6 (4 remaining features)…
  [1/5] Agent x1y2z3 → "Webhook processes invoice.paid events"
  [2/5] Agent a4b5c6 → "Stripe subscription cancellation"
  [3/5] Agent d7e8f9 → "User can update payment method"
  [4/5] Agent g0h1i2 → "Admin can view all users"
  [5/5] Agent j3k4l5 → "Admin can disable user accounts"
```

### Step 3: Add more features mid-run (optional)

While the run is active, you realize you need a new feature. In Claude Code:

```
/expand-project
```

```
Claude: Current: SaaS Platform (35/50 passing, 5 in-flight, 10 pending)

  What would you like to add?

You: Add a feature: "Admin can export user list as CSV with columns:
     email, plan, signup_date, last_login, task_count"

Claude: ✅ Created task: exp-001 (priority 5)
  The dispatcher will pick this up after current pending tasks.
```

The new feature appears in the Pending column of the Kanban board immediately.

### Step 4: Complete and verify

After ~20 minutes:
```
Progress: 51/51 passing · 0 in-flight · $9.22 spent
✅ All features complete (including 1 added mid-run)
```

Run the full verification:
```
/check-code → /checkpoint → /review-pr → git push
```

**Key takeaway:** claw-forge's state is persistent. Interruptions — power loss, laptop sleep,
network drops, accidental Ctrl+C — are handled automatically. Just `claw-forge run` again.

---

## Decision Tree: Which Command Do I Use?

```
Start here
  │
  ├── Building something new?
  │     └── claw-forge init → /create-spec → claw-forge plan → claw-forge run
  │
  ├── Adding features to existing code?
  │     └── claw-forge analyze → /create-spec → claw-forge add → claw-forge run
  │
  ├── Fixing a bug?
  │     └── /create-bug-report → claw-forge fix
  │
  ├── Checking project health?
  │     ├── Code quality → /check-code
  │     ├── Feature progress → claw-forge status
  │     └── Provider health → /pool-status
  │
  ├── Saving progress?
  │     └── /checkpoint → /review-pr → git push
  │
  ├── Resuming after break?
  │     └── claw-forge status → claw-forge run
  │
  ├── Pausing / resuming agents?
  │     └── claw-forge pause <session> → claw-forge resume <session>
  │
  ├── Agent asking a question?
  │     └── claw-forge input <session>
  │
  ├── Merging feature branches manually?
  │     └── claw-forge merge feat/branch-name
  │
  └── Adding features mid-run?
        └── /expand-project (or: claw-forge add "feature description")
```

---

## See Also

- [docs/commands.md](commands.md) — Full reference for every command and flag
- [docs/brownfield.md](brownfield.md) — Deep dive on brownfield mode
- [README.md](../README.md) — Project overview and quick start
