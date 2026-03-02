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

Fix a bug using reproduce-first protocol (Red-Green).

```bash
# Fix a bug
claw-forge fix "Login returns 500 when email contains plus sign"

# With options
claw-forge fix "Memory leak in WebSocket handler" \
  --project ./myapp \
  --model claude-sonnet-4-5
```

**What happens:**
1. Auto-runs `analyze` if no `brownfield_manifest.json` exists
2. Creates git branch `fix/login-returns-500-when-email-contains-plus-sign`
3. Runs existing test suite → establishes baseline (must pass)
4. Agent writes a **failing test** that reproduces the bug (RED)
5. Agent finds root cause with systematic debugging
6. Agent applies **surgical fix** — minimum code change
7. Confirms the failing test now passes (GREEN)
8. Runs full test suite → all green
9. Generates fix report, commits on branch

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
