# Computation Awareness: Auto-Offloading + Sub-Agent Parallelism

**Date**: 2026-03-21
**Status**: Approved

## Problem

claw-forge's event loop is single-threaded. While 99%+ of wall-clock time is LLM API latency today, several code paths perform CPU-bound or disk-heavy work that could block the event loop as project scale grows. Additionally, individual agents process large tasks sequentially even when sub-tasks are independent and could be parallelized via sub-agents.

## Goals

1. **A-lite**: Provide a simple opt-in mechanism to offload CPU-bound functions to a process pool — no auto-detection, no runtime profiling
2. **B-lite**: Guide agents to use sub-agents for parallelizable work, with a configurable soft-limit to prevent runaway spawning
3. **Observability**: Show active sub-agent count on UI task cards in real-time

## Non-Goals

- Runtime CPU profiling or auto-detection of slow functions
- Hard-blocking sub-agent creation (breaks model reasoning)
- Changes to the dispatcher's task-level parallelism (already handled by TaskGroup + worktrees)
- Changes to the provider pool (sub-agent API calls already route through it)

---

## Design

### Part A: `@offload_heavy` Decorator + Shared Process Pool

#### New file: `claw_forge/compute.py`

A module providing:

- **`get_pool() -> ProcessPoolExecutor`**: Lazy-initializes a module-level singleton process pool sized to `min(os.cpu_count(), 4)`. Returns the existing pool on subsequent calls. Capped at 4 workers because the offloaded workload is small — a full cpu_count pool wastes memory.

- **`offload_heavy(fn)`**: Decorator that wraps a synchronous, CPU-bound function so it runs in the process pool via `asyncio.get_running_loop().run_in_executor()`. The decorated function becomes a coroutine. Requirements on the wrapped function:
  - Must be a **pure function** (no shared mutable state, no closures over unpicklable objects)
  - Arguments and return values must be **picklable** (Path, str, list, dict, dataclasses — all fine)
  - Must be a **module-level function** (not a lambda, nested def, or bound method) for pickle compatibility

- **`shutdown_pool()`**: Calls `pool.shutdown(wait=False)`. Registered via `atexit` on first pool creation. Idempotent.

#### Offloaded functions

**CPU-bound (use `@offload_heavy` → ProcessPoolExecutor):**

| Function | File | Why | Notes |
|----------|------|-----|-------|
| `_assign_dependencies()` | `claw_forge/spec/parser.py` | O(n^2) topological wave computation | **Requires refactoring**: currently mutates `features` in-place (returns `None`). Must be changed to return a `list[list[int]]` mapping each feature index to its `depends_on_indices`, with the caller applying the results. This makes it a pure function suitable for cross-process execution. |

**I/O-bound (use `asyncio.to_thread()` → ThreadPoolExecutor):**

| Function | File | Why | Notes |
|----------|------|-----|-------|
| `detect_lsp_plugins()` | `claw_forge/lsp.py` | `Path.rglob("*")` blocking disk scan | I/O-bound, not CPU-bound — `to_thread()` is correct here, not ProcessPoolExecutor. GIL is released during syscalls. |

**Deferred (not in initial implementation):**

| Function | File | Why deferred |
|----------|------|--------------|
| `annotate()` | `claw_forge/hashline.py` | For typical source files (hundreds of lines), SHA256 computation completes in microseconds. The IPC overhead of pickling content to a child process would exceed the computation time. Revisit if hashline is used on files with 10,000+ lines. |

#### Call site changes

Functions that call the offloaded functions must `await` them. Affected call sites:

- `spec/parser.py`: `_assign_dependencies()` is called from `ProjectSpec.from_file()` (classmethod at `parser.py:93`), which is called synchronously from `InitializerPlugin._execute_with_spec()`. Since the initializer plugin's `execute()` method is async, the `from_file()` call must be wrapped in `asyncio.to_thread()` to bridge into async context, where the refactored `_assign_dependencies()` can then be offloaded via the process pool.
- `lsp.py`: `detect_lsp_plugins()` is called from `runner.py:run_agent()` which is already async — wrapping with `await asyncio.to_thread()` is straightforward

#### Pool lifecycle

```
First @offload_heavy call
        │
        ▼
  get_pool() creates ProcessPoolExecutor(max_workers=min(cpu_count(), 4))
  atexit.register(shutdown_pool)
        │
        ▼
  Pool lives for process lifetime
        │
        ▼
  On exit: atexit fires shutdown_pool()
           pool.shutdown(wait=False)
```

---

### Part B: Sub-Agent Guidance + Resource Guard

#### B1: System prompt guidance

Add to `get_system_prompt()` in `coding.py` and `bugfix.py` plugins:

```
## Parallel Sub-Agents

When your task involves 5+ independent file modifications or independent subtasks,
use the Agent tool to parallelize:
- Spawn one sub-agent per independent file or module
- Each sub-agent gets a focused, self-contained instruction
- Do NOT spawn sub-agents for sequential work (where step N depends on step N-1)

Limit: spawn at most {max_subagents} sub-agents per task.
```

Not added to `testing` or `reviewer` plugins — their work is inherently sequential (run tests, parse results).

#### B2: Soft-limit in SubagentStart hook

Modify `subagent_start_hook()` in `claw_forge/agent/hooks.py`:

- **Counter**: Track `active_subagents` (incremented on `SubagentStart`, decremented on `SubagentStop`) and `total_subagents_spawned` (only incremented) per task
- **Per-task state**: Convert `subagent_start_hook` and `subagent_stop_hook` from plain module-level functions to a **factory pattern** — `make_subagent_hooks(max_subagents, state_url)` returns closures that capture a mutable `dict[str, SubagentState]` keyed by task ID. This follows the existing pattern used by `make_stop_hook` and `make_notification_hook` in the same file.
- **Soft-limit check**: When `total_subagents_spawned >= max_subagents_per_task`, inject `additionalContext` warning: "You have reached the sub-agent limit for this task. Complete remaining work sequentially."
- **No hard-block**: The hook still returns normally — the model receives guidance, not a wall

#### Configuration

```yaml
# claw-forge.yaml
agent:
  max_subagents_per_task: 5    # default; 0 = unlimited
```

Read in `cli.py` and passed to `make_subagent_hooks()` when constructing hooks.

---

### Part C: Sub-Agent Count on UI Task Cards

#### Data flow

```
SubagentStart hook ──► counter++ ──► PATCH state service ──► WebSocket broadcast ──► UI badge
SubagentStop hook  ──► counter-- ──► PATCH state service ──► WebSocket broadcast ──► UI badge hide
```

#### State service changes

**`state/models.py`**: Add column to Task model:
```python
active_subagents: Mapped[int] = mapped_column(default=0)
```

**`state/service.py`**: Accept `active_subagents` in the PATCH `/sessions/{sid}/tasks/{tid}` endpoint. Include it in WebSocket broadcast payloads.

#### Hook → State service communication

The `SubagentStart` and `SubagentStop` hooks make an `httpx.AsyncClient.patch()` call to the state service to update the `active_subagents` count. The state service URL is passed into `HookContext` at hook construction time (the CLI task handler already knows this URL).

Error handling: the PATCH is dispatched via `asyncio.create_task()` (fire-and-forget) with a 2-second `httpx` timeout. If the state service is slow or unreachable, the task logs a warning — sub-agent count display is best-effort, not critical path. This follows the existing pattern in `make_notification_hook` which already uses `asyncio.create_task()`.

#### Existing database compatibility

Per CLAUDE.md, the project uses `CREATE TABLE IF NOT EXISTS` with no migrations. The new `active_subagents` column will only appear on fresh databases. This is acceptable because:
- State databases are ephemeral — created per session and not carried across upgrades
- The column defaults to 0, so even if an `ALTER TABLE ADD COLUMN` fallback were added, it would be a no-op for running tasks

#### UI changes

**`ui/src/types.ts`**: Add `active_subagents: number` to the Task type.

**`ui/src/components/TaskCard.tsx`**: When `active_subagents > 0`, show a badge on the task card displaying the count. Badge disappears when count returns to 0. Updates arrive via the existing WebSocket connection — no polling needed.

---

## File Change Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `claw_forge/compute.py` | **New** | `get_pool()`, `@offload_heavy`, `shutdown_pool()` |
| `claw_forge/spec/parser.py` | Modify | Refactor `_assign_dependencies()` to return data (not mutate), decorate with `@offload_heavy`, wrap `from_file()` call in `asyncio.to_thread()` |
| `claw_forge/lsp.py` | Modify | Wrap `detect_lsp_plugins()` with `asyncio.to_thread()` |
| `claw_forge/plugins/coding.py` | Modify | Add sub-agent guidance to system prompt |
| `claw_forge/plugins/bugfix.py` | Modify | Add sub-agent guidance to system prompt |
| `claw_forge/agent/hooks.py` | Modify | Convert subagent hooks to factory pattern (`make_subagent_hooks`), add counter, soft-limit, and fire-and-forget state service PATCH |
| `claw_forge/state/models.py` | Modify | Add `active_subagents` column |
| `claw_forge/state/service.py` | Modify | Accept and broadcast `active_subagents` |
| `claw_forge/cli.py` | Modify | Read `agent.max_subagents_per_task` from config, pass to hooks |
| `ui/src/types.ts` | Modify | Add `active_subagents` to Task type |
| `ui/src/components/TaskCard.tsx` | Modify | Show sub-agent count badge |
| `tests/test_compute.py` | **New** | Decorator behavior, pool lifecycle, picklability |
| `tests/test_hooks_subagent_limit.py` | **New** | Counter, soft-limit, PATCH calls |

## Testing Strategy

### `tests/test_compute.py`
- Decorated sync function becomes awaitable
- Function executes in a separate process (verify via `os.getpid()`)
- Pool is lazy-initialized (not created at import time)
- `shutdown_pool()` is idempotent
- Non-picklable arguments raise clear error

### `tests/test_hooks_subagent_limit.py`
- Counter increments on SubagentStart, decrements on SubagentStop
- Warning injected in `additionalContext` when limit reached
- Counter tracks per-task (not global)
- Configurable limit from `claw-forge.yaml`
- State service PATCH called on each start/stop
- PATCH failure logged but does not block hook

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Opt-in decorator, not auto-detect | Runtime profiling adds overhead everywhere to benefit almost nowhere; target functions are known |
| `ProcessPoolExecutor` for CPU, `to_thread()` for I/O | CPU-bound work (wave computation) needs GIL escape; I/O-bound work (rglob) releases GIL during syscalls — threads are sufficient and cheaper |
| Lazy pool initialization | No pool overhead if offloaded functions are never called |
| Pool capped at 4 workers | Only 1 CPU-bound function offloaded today; full cpu_count pool wastes memory |
| `annotate()` deferred | IPC pickling overhead exceeds computation time for typical file sizes |
| `_assign_dependencies` refactored to return data | Original mutates in-place — mutations in a child process don't propagate back to the caller |
| Soft-limit, not hard-block | Hard-blocking a sub-agent mid-spawn breaks the model's reasoning plan; soft warning lets it adapt |
| Factory pattern for subagent hooks | Per-task counter state requires closures; follows existing `make_stop_hook` / `make_notification_hook` pattern |
| Fire-and-forget PATCH with 2s timeout | Follows existing `make_notification_hook` pattern; avoids blocking hook return on slow state service |
| `active_subagents` on Task model | Leverages existing PATCH + WebSocket infrastructure; no new endpoints needed |
| Guidance in coding/bugfix only | Testing and reviewer plugins do sequential work; sub-agent fan-out doesn't help |
