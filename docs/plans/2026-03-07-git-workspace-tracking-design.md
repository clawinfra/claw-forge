# Git Workspace Tracking Design

**Date:** 2026-03-07
**Status:** Approved

## Problem

claw-forge has no git integration. Agent work is tracked only in SQLite state. There is no version-controlled history of what agents did, no way to bisect regressions, and no structured memory for agents to understand prior work.

## Design Decisions

- **Hybrid branch model**: Agents commit freely on feature branches; squash-merge to main on completion. Detailed trace on branches, clean history on main.
- **Commit triggers**: Plugin-boundary auto-commits + agent milestone commits + explicit `checkpoint` MCP tool.
- **Merge strategy**: Configurable (`auto` | `manual`) in `claw-forge.yaml`, default `auto`.
- **Init behavior**: Auto-detect `.git/` — init if missing, commit scaffolding if existing.
- **Commit format**: Conventional Commits with structured trailers (`Task-ID`, `Plugin`, `Phase`, `Session`).
- **Parallel safety**: `asyncio.Lock` serializes git operations (stash/switch/commit/switch-back). No worktrees for now.
- **Architecture**: Centralized `claw_forge/git/` module + MCP tools for agent access.

## Architecture

### New Module: `claw_forge/git/`

```
claw_forge/git/
  __init__.py          # public API re-exports
  repo.py              # init_or_detect, .gitignore management
  branching.py         # create/switch/delete feature branches
  commits.py           # checkpoint commits with conventional + trailers
  merge.py             # squash-merge feature branches to main
```

### Key Functions

| Function | Module | Purpose |
|----------|--------|---------|
| `init_or_detect(project_dir)` | repo.py | If `.git/` exists, return repo info; otherwise `git init` + `.gitignore` + initial commit |
| `create_feature_branch(task_id, slug)` | branching.py | Create `feat/<slug>` from main, switch to it |
| `commit_checkpoint(message, task_id, plugin, phase, session_id)` | commits.py | Conventional commit with structured trailers |
| `squash_merge(branch, target="main")` | merge.py | Squash-merge branch to target, delete branch |
| `task_history(task_id, limit)` | commits.py | Parse `git log` into structured commit data |
| `current_branch()`, `branch_exists(name)` | branching.py | Query helpers |

All functions use `subprocess.run(["git", ...])`, consistent with existing `claw-forge fix`.

### Integration Points

**`claw-forge init`:**
1. `init_or_detect(project_dir)` — set up repo if needed
2. Commit scaffolded files: `chore(claw-forge): initialize project tracking`

**`claw-forge run` dispatcher lifecycle:**

| Event | Git Operation |
|-------|--------------|
| Task starts | `create_feature_branch(task_id, slug)` |
| Coding plugin completes | `commit_checkpoint(...)` with `Phase: coding` |
| Testing plugin completes | `commit_checkpoint(...)` with `Phase: testing` |
| Reviewer approves | `commit_checkpoint(...)` with `Phase: review` |
| All plugins pass (auto mode) | `squash_merge(branch)` |
| All plugins pass (manual mode) | Mark branch as ready-to-merge |
| Task fails | Branch preserved for debugging |

**Parallel safety:** An `asyncio.Lock` serializes git operations. During a commit: stash current work -> switch to feature branch -> stage + commit -> switch back -> pop stash. The lock only guards the brief git operations, not agent execution.

### MCP Tools (added to `mcp/sdk_server.py`)

**`checkpoint`** — Write tool for agents:
```
Parameters:
  message (str, required): What was accomplished
  phase (str, optional): "milestone" | "save" | "risky" (default: "milestone")
Returns:
  commit_hash (str): Short SHA
  branch (str): Current feature branch name
```

**`task_history`** — Read tool for agents:
```
Parameters:
  task_id (str, optional): Filter by task. Omit for recent project history.
  limit (int, optional): Max commits (default: 20)
Returns:
  commits: [{hash, message, timestamp, trailers: {task_id, plugin, phase, session_id}}]
```

### Commit Format

```
feat(auth): add password hashing

Implemented bcrypt-based password hashing with configurable rounds.

Task-ID: 3a8f1c2d
Plugin: coding
Phase: milestone
Session: 9c2b4e7a
```

### Configuration (`claw-forge.yaml`)

```yaml
git:
  enabled: true                    # false = all git ops become no-ops
  merge_strategy: auto             # auto | manual
  branch_prefix: feat              # customizable prefix
  commit_on_plugin_boundary: true  # auto-commit at plugin phase transitions
```

### New CLI Command

`claw-forge merge [feature-slug]` — Manually trigger squash-merge for a ready branch. Lists ready branches if no slug provided. Only relevant when `merge_strategy: manual`.
