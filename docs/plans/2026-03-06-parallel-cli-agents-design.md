# Parallel CLI Agent Execution — Design

**Date:** 2026-03-06
**Status:** Approved
**Scope:** `claw_forge/cli.py`, `tests/test_e2e_gaps.py`, `tests/test_cli_commands.py`

## Problem

The `_cli_semaphore = asyncio.Semaphore(1)` in `cli.py:533` serializes all Claude CLI agent execution, limiting throughput to one agent at a time despite the dispatcher supporting `--concurrency 5`.

Two root causes motivated the semaphore:

1. **CLAUDECODE env var race** — Each task pops `CLAUDECODE` from `os.environ` before spawning a subprocess and restores it after. Concurrent coroutines race on this global mutable state.
2. **returncode 255** — Observed when multiple claude CLI subprocesses exit concurrently, attributed to asyncio SIGCHLD race conditions.

## Reference Implementation

The `autonomous-coding` project (`/Users/bowenli/projects/autonomous-coding`) successfully runs multiple Claude CLI agents in parallel using a proven pattern:

- **`threading.Lock()`** serializes only env var mutation + client creation (synchronous, brief)
- **Agent connect + execution** runs fully parallel outside the lock
- **No returncode 255 issues** observed with concurrent subprocesses

Key code: `src/agents/parallel_session.py:21-23, 239-261, 284-294`

## Design

### Change 1 — Pop CLAUDECODE once at the top of `run()`

Move the `os.environ.pop("CLAUDECODE")` from per-task (inside `task_handler`) to the outer scope of the `run()` command. Restore in a `finally` block. This eliminates the per-task race entirely since CLAUDECODE is never needed during the orchestration phase.

```python
# Before dispatch loop (inside main() within run())
_saved_claudecode = os.environ.pop("CLAUDECODE", None)
try:
    # ... entire dispatch loop + task handlers ...
finally:
    if _saved_claudecode is not None:
        os.environ["CLAUDECODE"] = _saved_claudecode
```

### Change 2 — Replace `_cli_semaphore` with narrow `_env_lock`

Replace the `Semaphore(1)` (which serializes the entire agent lifecycle) with an `asyncio.Lock()` that serializes only the env-sensitive setup phase — matching the `_env_client_lock` pattern from autonomous-coding.

```python
# Before:
_cli_semaphore = asyncio.Semaphore(1)

# After:
_env_lock = asyncio.Lock()
```

The lock covers:
- Reading `os.environ` for API key resolution
- Constructing `sdk_env` dict
- Creating `ClaudeAgentOptions` with the captured env snapshot

The lock does NOT cover:
- `AgentSession.__aenter__()` (subprocess spawn / connect)
- `agent_session.run(prompt)` (agent execution / streaming)

### Change 3 — Restructure task_handler

```python
async def task_handler(task_node):
    # UNDER LOCK: env reads + options construction (synchronous, brief)
    async with _env_lock:
        sdk_env: dict[str, str] = {}
        _api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not _api_key and pool is not None:
            _provs = pool.providers
            if _provs and hasattr(_provs[0], "config"):
                _api_key = _provs[0].config.api_key or ""
        if _api_key:
            sdk_env["ANTHROPIC_API_KEY"] = _api_key
        # ... oauth fallback ...

        options = ClaudeAgentOptions(
            model=model,
            cwd=str(project_path),
            env=sdk_env,
            permission_mode="bypassPermissions",
        )

    # OUTSIDE LOCK: connect + run (parallel with other agents)
    full_output: list[str] = []
    try:
        async with AgentSession(options) as agent_session:
            async for msg in agent_session.run(prompt):
                # ... process messages (same as current) ...
    except Exception as sdk_exc:
        # ... error handling (same as current) ...
```

### Change 4 — Remove per-task CLAUDECODE pop/restore

Delete the per-task `os.environ.pop("CLAUDECODE")` and its corresponding `finally` restore block. No longer needed since CLAUDECODE is popped once globally.

### Change 5 — Update tests

- **Remove** `test_semaphore_serialises_sessions` (validates old Semaphore(1) behavior)
- **Add** `test_env_lock_allows_parallel_sessions` — verify multiple agents can run concurrently
- **Add** `test_env_lock_serialises_options_construction` — verify the lock protects env reads
- **Update** `test_claudecode_popped_and_restored_on_success` — verify pop-once at run() level
- **Update** `test_claudecode_restored_after_sdk_exception` — verify restore in outer finally

## Non-Changes

- **Dispatcher semaphore** (`dispatcher.py:116`) — Unchanged. Still gates overall concurrency via `Semaphore(max_concurrency)`.
- **Pool/API path** (`cli.py:779+`) — Unchanged. Already runs fully concurrently.
- **Retry logic** (`dispatcher.py:256+`) — Unchanged. Still retries failed tasks with exponential backoff. If returncode 255 ever occurs, the retry handles it.

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| returncode 255 recurrence | Dispatcher retry (exponential backoff, 3 attempts default). autonomous-coding proves concurrent spawns work. |
| Env var race in future per-agent key rotation | `_env_lock` protects the critical section, matching autonomous-coding's pattern |
| SDK reads os.environ during connect() outside lock | `options.env` (sdk_env) overrides os.environ during subprocess spawn: `{**os.environ, **options.env}` |

## Why `asyncio.Lock()` not `threading.Lock()`

autonomous-coding uses `threading.Lock()` because their `create_client()` is synchronous. In claw-forge, the critical section is also synchronous (no await under the lock), but we use `asyncio.Lock()` because:
- Pure async context (no thread-based agent execution)
- Safer with asyncio coroutines (no deadlock risk from accidental yield)
- Future-proof if the section ever needs an await
