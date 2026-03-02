# Brownfield Project Support

claw-forge can work on **existing codebases** — not just greenfield projects. Brownfield mode analyzes your project's stack, conventions, and test baseline, then adds features or fixes bugs while respecting existing patterns.

---

## How It Works

```
┌─────────────────────────────────────────────────────────┐
│                   Your Existing Project                  │
│  src/ tests/ package.json pyproject.toml .git/          │
└─────────────────────────┬───────────────────────────────┘
                          │
                  claw-forge analyze
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│              BrownfieldAnalyzer                          │
│                                                         │
│  1. Detect stack (language, framework, pkg manager)     │
│  2. Parse git log → find hot files                      │
│  3. Read code → detect conventions                      │
│  4. Run test suite → establish baseline                 │
│  5. Identify entry points and architecture layers       │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│              brownfield_manifest.json                    │
│                                                         │
│  { stack, conventions, test_baseline, hot_files,        │
│    entry_points, architecture }                         │
└─────────────────────────┬───────────────────────────────┘
                          │
            ┌─────────────┴─────────────┐
            │                           │
    claw-forge add <feature>    claw-forge fix <bug>
            │                           │
            ▼                           ▼
   ┌────────────────┐         ┌──────────────────┐
   │ Feature Flow   │         │ Bug Fix Flow     │
   │                │         │                  │
   │ 1. Branch      │         │ 1. Branch        │
   │ 2. Baseline    │         │ 2. Baseline      │
   │    tests       │         │    tests         │
   │ 3. Implement   │         │ 3. Write failing │
   │    (match      │         │    test (RED)    │
   │    conventions)│         │ 4. Surgical fix  │
   │ 4. Run tests   │         │ 5. Test passes   │
   │ 5. Commit      │         │    (GREEN)       │
   └────────────────┘         │ 6. Full suite    │
                              │ 7. Commit        │
                              └──────────────────┘
```

---

## Commands

### `claw-forge analyze`

Scans an existing project and produces `brownfield_manifest.json`.

```bash
# Analyze current directory
claw-forge analyze

# Analyze a specific project
claw-forge analyze --project /path/to/myapp

# Analyze with custom config
claw-forge analyze --config claw-forge.yaml --project ./myapp
```

**Output:**
```
✅ Project analyzed: myapp
   Stack:     Python 3.12 / FastAPI / uv / pytest
   Tests:     142 passing (87% coverage)
   Hot files: src/auth.py (47 changes), src/models.py (39 changes)
   Manifest:  brownfield_manifest.json written
```

### `claw-forge add <feature>`

Add a single feature to an existing codebase.

```bash
# Add a feature
claw-forge add "Add rate limiting to all API endpoints"

# With options
claw-forge add "WebSocket notification system" \
  --project ./myapp \
  --model claude-sonnet-4-5 \
  --config claw-forge.yaml
```

**What happens:**
1. Auto-runs `analyze` if no `brownfield_manifest.json` exists
2. Creates git branch `feat/add-rate-limiting-to-all-api-endpoints`
3. Runs existing test suite → establishes baseline (must pass)
4. Agent reads manifest, matches conventions, implements feature
5. Runs full test suite → must still pass + new tests added
6. Commits on feature branch

### `claw-forge fix <description>`

Fix a bug using a strict reproduce-first protocol (RED → GREEN). Two modes are supported: a quick one-liner, or a structured bug report for complex issues.

---

#### Quick fix (one-liner)

```bash
claw-forge fix "users get 500 when uploading files > 5MB"
```

Describe the bug in plain English. The agent reproduces it, writes a failing test, fixes it, and commits.

#### Structured fix (recommended for complex bugs)

For bugs that are hard to describe in one line, use a structured bug report:

```bash
# Option A — Generate interactively with the /create-bug-report slash command
# (opens guided 6-phase flow in Claude Code)
/create-bug-report

# Option B — Fill in the template manually
cp skills/bug_report.template.md bug_report.md
# edit bug_report.md...

# Run the fix
claw-forge fix --report bug_report.md
```

**Example filled-in `bug_report.md`:**

```markdown
# Bug Report

## Title
Users get HTTP 500 when uploading files larger than 5 MB

## Symptoms
- POST /api/upload returns 500 Internal Server Error
- Only reproducible for files ≥ 5 MB; smaller files work fine
- Error only appears in production (not local dev)
- No useful error message in the response body

## Steps to Reproduce
1. Authenticate as any user
2. POST /api/upload with a multipart file ≥ 5 MB
3. Observe 500 response

## Expected Behaviour
File is uploaded successfully, returns 201 with `{"file_id": "..."}`.

## Actual Behaviour
500 Internal Server Error. Server logs show:
`RequestEntityTooLargeError: request body exceeded 4194304 bytes`

## Affected Scope
- `src/api/upload.py` — upload endpoint
- `src/config.py` — possibly where the limit is set

## Constraints
- Must not break existing file upload tests
- Fix must work for files up to 100 MB (product requirement)
- Do not change the request Content-Type handling

## Regression Test Required
Yes — add a test that POSTs a 6 MB file and asserts 201.
```

---

#### What happens during `claw-forge fix`

1. Auto-runs `analyze` if no `brownfield_manifest.json` exists
2. Creates git branch `fix/<slug-of-description>`
3. Runs existing test suite → establishes baseline (must all pass)
4. Loads `BugReport` from description or `--report` file
5. Agent writes a **failing regression test** that reproduces the bug (**RED**)
6. Agent uses `systematic-debug` skill to isolate root cause
7. Agent applies **surgical fix** — minimum code change, matched to project conventions
8. Confirms the regression test now passes (**GREEN**)
9. Runs full test suite → all must be green (no regressions)
10. Commits with message: `fix: <title>\n\nRegression test: <test_name>`

---

#### RED → GREEN protocol detail

```
  Bug description / bug_report.md
         │
         ▼
  BugReport.from_file() / from_description()
         │  Parses: symptoms, repro steps, expected/actual,
         │  affected scope, constraints, regression_test_required
         ▼
  BugFixPlugin.execute()
         │  Injects: to_agent_prompt() → structured context
         │  Skills: systematic-debug (auto), verification-gate (auto)
         │  Thinking: ADAPTIVE_THINKING
         ▼
  Agent runs RED→GREEN loop:
    1. Write failing regression test (RED) ← committed first
    2. Isolate root cause (systematic-debug)
    3. Surgical fix — touches only what's needed
    4. Regression test passes (GREEN)
    5. Full suite green — 0 regressions allowed
    6. Atomic commit: fix: <title>\n\nRegression test: <test_name>
```

The failing test is committed **before** the fix. This proves the bug was real and the fix is targeted.

---

#### With options

```bash
claw-forge fix "Memory leak in WebSocket handler" \
  --project ./myapp \
  --model claude-sonnet-4-5

claw-forge fix --report bug_report.md \
  --project ./myapp \
  --config claw-forge.yaml
```

---

## brownfield_manifest.json

The manifest is the bridge between your project and the agent. It tells the agent what your project looks like so it can match your patterns.

### Example

```json
{
  "version": "1.0",
  "generated_at": "2026-03-02T10:30:00Z",
  "project_root": "/home/user/myapp",
  "stack": {
    "language": "python",
    "language_version": "3.12",
    "framework": "fastapi",
    "package_manager": "uv",
    "test_runner": "pytest"
  },
  "conventions": {
    "naming": "snake_case",
    "error_handling": "raise specific exceptions with HTTPException",
    "logging": "structlog with bound loggers",
    "imports": "from __future__ import annotations, absolute imports"
  },
  "test_baseline": {
    "framework": "pytest",
    "total_tests": 142,
    "passing": 142,
    "failing": 0,
    "coverage_pct": 87.3,
    "test_command": "uv run pytest tests/ -v"
  },
  "hot_files": [
    {"path": "src/auth.py", "change_count": 47, "role": "authentication module"},
    {"path": "src/models.py", "change_count": 39, "role": "SQLAlchemy models"},
    {"path": "src/api/tasks.py", "change_count": 31, "role": "task CRUD endpoints"}
  ],
  "entry_points": [
    {"type": "cli", "path": "src/main.py", "description": "FastAPI app entry point"},
    {"type": "config", "path": "pyproject.toml", "description": "Project configuration"}
  ],
  "architecture": {
    "layers": ["api", "service", "model", "schema"],
    "patterns": ["repository pattern", "dependency injection"],
    "key_modules": [
      {"path": "src/api/", "role": "HTTP endpoints"},
      {"path": "src/services/", "role": "business logic"},
      {"path": "src/models/", "role": "database models"}
    ]
  }
}
```

---

## Workflow Examples

### Example 1: Add a feature to an existing FastAPI app

```bash
cd ~/myapp

# Step 1: Analyze (optional — add will auto-analyze)
claw-forge analyze

# Step 2: Add the feature
claw-forge add "Add pagination to GET /users endpoint with page and per_page query params"

# Step 3: Review the branch
git log --oneline feat/add-pagination-to-get-users-endpoint
git diff main..feat/add-pagination-to-get-users-endpoint
```

### Example 2: Fix a bug with reproduce-first protocol

```bash
cd ~/myapp

# Fix the bug
claw-forge fix "GET /tasks returns 500 when user has no tasks (empty list case)"

# Check the fix branch
git log --oneline fix/get-tasks-returns-500-when-user-has-no-tasks
# Should see: test commit (RED) then fix commit (GREEN)
```

### Example 3: Multiple features in sequence

```bash
cd ~/myapp

claw-forge add "Add email validation on user registration"
claw-forge add "Add rate limiting middleware (100 req/min per IP)"
claw-forge add "Add health check endpoint at GET /health"
```

Each creates its own branch. Merge them into main as you review.

---

## Tips

- **Run `analyze` explicitly** if you want to inspect the manifest before adding features
- **The manifest is a cache** — delete `brownfield_manifest.json` and re-analyze if your project changed significantly
- **Branch-first always** — brownfield commands never commit to main
- **Tests are sacred** — if existing tests break, the agent must fix them before completing
- **Conventions are enforced** — the agent reads the manifest and matches your naming, error handling, and import style
