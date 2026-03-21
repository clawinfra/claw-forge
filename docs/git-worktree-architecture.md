# Git Worktree Architecture for Concurrent Agent Isolation

## Context

claw-forge orchestrates multiple AI agents in parallel, each implementing a separate feature. Without isolation, concurrent agents writing to the same working directory create file conflicts, corrupt each other's state, and produce unpredictable git histories. Git worktrees solve this by giving each agent its own checked-out copy of the repository while sharing a single object store — no full clones required.

This document describes the worktree lifecycle, locking strategy, failure recovery model, and how worktrees integrate with the broader orchestration pipeline.

## Why Worktrees, Not Clones or Branches-in-Place

| Approach | Disk Cost | Concurrent Safety | Git History |
|----------|-----------|-------------------|-------------|
| Shared working directory | 1× | Unsafe — file conflicts | Interleaved commits |
| Full clone per agent | N× repo | Safe | Separate repos, hard to merge |
| **Git worktrees** | **1× repo + N× files** | **Safe — independent HEAD/index** | **Shared refs, easy squash-merge** |

A worktree creates a new working directory linked back to the original `.git` store. All git objects (commits, blobs, trees, pack files) are shared. Only the checked-out files, `HEAD`, and index are per-worktree. If the repo has 100 MB of history and 20 MB of tracked files, each additional worktree costs ~20 MB — not ~120 MB.

## Directory Layout

```
project/
├── .git/                          # Shared object store (one copy)
├── .claw-forge/
│   ├── worktrees/                 # All agent worktrees (gitignored)
│   │   ├── auth-jwt-tokens/       # Worktree for auth feature
│   │   │   ├── .git               # File (not dir) — points to main .git
│   │   │   ├── src/               # Independent checkout
│   │   │   └── ...
│   │   └── api-rate-limiting/     # Worktree for API feature
│   │       ├── .git
│   │       └── ...
│   ├── state.db                   # SQLite state (gitignored)
│   └── state.log                  # Runtime log (gitignored)
├── src/                           # Main working directory (stays on main)
└── .gitignore                     # Includes .claw-forge/worktrees/
```

Each worktree's `.git` is a **file** (not a directory) containing a single line pointing to the real `.git/worktrees/<name>` metadata.

## Lifecycle

### Phase 1: Creation

When the dispatcher assigns a task to an agent, the CLI handler creates an isolated worktree:

```
project_dir / ".claw-forge" / "worktrees" / {slug}
```

**Implementation** (`claw_forge/git/branching.py:create_worktree`):

```python
def create_worktree(project_dir, task_id, slug, *, prefix="feat"):
    branch_name = f"{prefix}/{slug}"
    worktree_path = project_dir / ".claw-forge" / "worktrees" / slug

    # Stale cleanup from prior crashed run
    if worktree_path.exists():
        shutil.rmtree(worktree_path)
        _run_git(["worktree", "prune"], project_dir)

    # Create worktree — reuse or create branch
    if branch_exists(project_dir, branch_name):
        _run_git(["worktree", "add", str(worktree_path), branch_name], ...)
    else:
        _run_git(["worktree", "add", "-b", branch_name, str(worktree_path)], ...)

    return (branch_name, worktree_path)
```

The branch name is derived from the task description via `make_slug()`, which strips leading action verbs so branches read as noun phrases (e.g., `feat/auth-jwt-tokens` instead of `feat/implement-auth-jwt-tokens`).

### Phase 2: Agent Execution

The agent runs with `cwd=worktree_path`, giving it full read-write access to an independent checkout:

```python
# cli.py — task handler
_agent_cwd = _worktree_path or project_path  # Fallback if git disabled

await run_agent(
    cwd=_agent_cwd,
    project_dir=project_path,  # Used for sandbox boundary
    ...
)
```

The agent's filesystem sandbox is bound to `project_dir` (the original repo root), but execution happens inside the worktree. Git commands are excluded from sandboxing (`excludedCommands=["git"]`) because they need host-level access for commits and pushes.

### Phase 3: Checkpoint Commits

On plugin boundaries (e.g., coding → testing), the handler commits progress within the worktree:

```python
await git_ops.checkpoint(
    message=task_description,
    task_id=task_id,
    plugin="coding",
    phase="coding",
    session_id=session_id,
    cwd=worktree_path,       # Commit inside the worktree, not main
)
```

Each checkpoint commit includes structured trailers for audit:

```
feat: implement JWT authentication

Task-ID: abc123
Plugin: coding
Phase: coding
Session: sess_456
```

### Phase 4: Squash Merge (Success)

After a task completes successfully, the feature branch is squash-merged into `main`:

```python
# merge.py:squash_merge
switch_branch(project_dir, target)               # Switch main repo to target
_run_git(["merge", "--squash", branch], ...)      # Stage all changes
_run_git(["commit", "-m", commit_msg], ...)       # Single atomic commit
remove_worktree(project_dir, worktree_path)       # Clean up worktree
delete_branch(project_dir, branch, force=True)    # Remove feature branch
```

The squash merge collapses all worktree commits into a single semantic commit on `main`, including:
- Feature title
- Completed steps checklist
- Commit subjects from the feature branch (as "Completed Phases")
- Task-ID and Session trailers

### Phase 5: Cleanup (Failure)

If a task fails after exhausting retries, the worktree is removed but the branch is preserved:

```python
# cli.py — failure path
if not success and _worktree_path:
    await git_ops.remove_worktree(_worktree_path)
    # Branch remains — can be inspected or retried
```

This allows debugging the branch state while freeing the worktree's disk space.

### Phase 6: Crash Recovery

On startup, `GitOps.init()` calls `prune_worktrees()` to clean up orphans from unclean shutdowns:

```python
def prune_worktrees(project_dir):
    worktrees_dir = project_dir / ".claw-forge" / "worktrees"
    for child in worktrees_dir.iterdir():
        # Tier 1: git worktree remove --force
        _run_git(["worktree", "remove", "--force", str(child)], ...)
        # Tier 2: fallback shutil.rmtree if git fails
        if child.exists():
            shutil.rmtree(child, ignore_errors=True)
    # Tier 3: prune git bookkeeping
    _run_git(["worktree", "prune"], project_dir)
```

## Locking Strategy

The `GitOps` async wrapper uses a single `asyncio.Lock` to protect shared state:

| Operation | Lock Required | Reason |
|-----------|--------------|--------|
| `create_worktree()` | No | Each worktree has independent HEAD/index |
| `checkpoint()` | No | Commits target the worktree's own branch |
| `remove_worktree()` | No | Removes only the worktree's directory |
| `merge()` | **Yes** | Mutates `main` branch — must be serialized |
| `create_feature_branch()` | Yes | Legacy shared-directory path |

This means N agents can write files, stage, and commit concurrently without contention. Only the final merge step is serialized, and it runs after agent work is complete — so it never blocks agent execution.

## Concurrency Flow

```
                ┌─────────────────────────────────────────┐
                │           Dispatcher (TaskGroup)         │
                │         Semaphore: max_parallel=5        │
                └──────┬──────────┬──────────┬────────────┘
                       │          │          │
               ┌───────▼──┐ ┌────▼─────┐ ┌──▼────────┐
               │ Agent A   │ │ Agent B  │ │ Agent C   │
               │ wt/auth   │ │ wt/api   │ │ wt/ui     │
               │ (no lock) │ │ (no lock)│ │ (no lock) │
               └───────┬───┘ └────┬─────┘ └──┬────────┘
                       │          │           │
                       ▼          ▼           ▼
               ┌──────────────────────────────────────┐
               │   Merge Queue (asyncio.Lock)          │
               │   Serialized squash-merge to main     │
               └──────────────────────────────────────┘
                                  │
                                  ▼
                          main branch
                    (clean linear history)
```

## Configuration

Worktree behavior is controlled via `claw-forge.yaml`:

```yaml
git:
  enabled: true                      # Master switch for all git operations
  merge_strategy: auto               # auto | manual
  branch_prefix: feat                # Branch prefix (feat/, fix/, etc.)
  commit_on_plugin_boundary: true    # Checkpoint commits between plugins
```

When `git.enabled: false`, the system falls back to running all agents in the shared project directory — useful for debugging but unsafe for parallel execution.

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Worktrees under `.claw-forge/worktrees/` | Co-located with other runtime state; single `.gitignore` entry covers everything |
| Always squash merge | One atomic commit per feature gives a clean, linear `main` history |
| Remove worktree on success, preserve branch on failure | Success: full cleanup. Failure: branch preserved for debugging |
| Two-tier crash cleanup (git remove → shutil.rmtree) | `git worktree remove` respects bookkeeping but can fail on corrupted state; `shutil.rmtree` is the nuclear fallback |
| Pre-create stale guard | Idempotent creation — crashed prior runs don't block new ones |
| Lock-free agent execution | The performance-critical phase (agent file I/O) runs without contention |
| Git excluded from agent sandbox | Git needs host-level access for commits, refs, and pack operations |
| Semantic branch names via `make_slug()` | Human-readable names in `git branch` output; verb-stripping avoids redundant prefixes like `feat/implement-...` |

## File Reference

| File | Role |
|------|------|
| `claw_forge/git/branching.py` | `create_worktree()`, `remove_worktree()`, `prune_worktrees()` |
| `claw_forge/git/merge.py` | `squash_merge()` with optional worktree cleanup |
| `claw_forge/git/commits.py` | `commit_checkpoint()` with semantic trailers |
| `claw_forge/git/slug.py` | `make_slug()`, `make_branch_name()` — verb-stripped naming |
| `claw_forge/git/repo.py` | `init_or_detect()`, `ensure_gitignore()` — ensures `.claw-forge/worktrees/` is gitignored |
| `claw_forge/git/__init__.py` | `GitOps` async wrapper — lock strategy, `asyncio.to_thread()` bridge |
| `claw_forge/cli.py` | Worktree creation/merge/cleanup in the `run` command task handler |
| `claw_forge/agent/runner.py` | `cwd=worktree_path` parameter, sandbox configuration |
| `tests/git/test_worktree.py` | Unit tests: creation, removal, pruning, parallel isolation |
| `tests/git/test_dispatcher_git.py` | Integration tests: async GitOps, full lifecycle |
