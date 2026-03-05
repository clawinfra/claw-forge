# Parallel CLI Agent Execution — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable true parallel Claude CLI agent execution by replacing the `Semaphore(1)` with a narrow `asyncio.Lock()` around env setup, matching the proven pattern from `autonomous-coding`.

**Architecture:** Pop `CLAUDECODE` once at the top of `run()`. Replace the wide `_cli_semaphore` with a narrow `_env_lock` that serializes only env reads + options construction. Agent connect + execution runs fully parallel, gated only by the dispatcher's `Semaphore(max_concurrency)`.

**Tech Stack:** Python asyncio, claude-agent-sdk, pytest

**Design doc:** `docs/plans/2026-03-06-parallel-cli-agents-design.md`

---

### Task 1: Update e2e concurrency tests (Red)

Replace the serialization test with a parallel-execution test.

**Files:**
- Modify: `tests/test_e2e_gaps.py:133-179`

**Step 1: Write the failing tests**

Replace the `TestCliSubprocessConcurrency` class with:

```python
# ── Parallel CLI agent execution (env lock pattern) ──────────────────────────

class TestCliParallelExecution:
    """Verify the _env_lock allows parallel agent sessions."""

    @pytest.mark.asyncio
    async def test_env_lock_allows_parallel_sessions(self) -> None:
        """Multiple AgentSessions run concurrently after options are built."""
        env_lock = asyncio.Lock()
        timeline: list[tuple[str, float]] = []

        async def fake_session(name: str) -> None:
            async with env_lock:
                # Options construction (brief, serialized)
                pass
            # Agent execution (parallel)
            timeline.append((f"start:{name}", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.05)
            timeline.append((f"end:{name}", asyncio.get_event_loop().time()))

        await asyncio.gather(
            fake_session("A"),
            fake_session("B"),
            fake_session("C"),
        )
        # All three should START before any END (parallel execution)
        starts = [t for tag, t in timeline if tag.startswith("start:")]
        ends = [t for tag, t in timeline if tag.startswith("end:")]
        # The last start should happen before the first end
        assert max(starts) < min(ends), (
            f"Sessions did not run in parallel: {timeline}"
        )

    @pytest.mark.asyncio
    async def test_env_lock_serialises_options_construction(self) -> None:
        """The env lock prevents concurrent env reads."""
        env_lock = asyncio.Lock()
        in_critical: list[bool] = []
        overlap_detected = False

        async def fake_session(name: str) -> None:
            nonlocal overlap_detected
            async with env_lock:
                if any(in_critical):
                    overlap_detected = True
                in_critical.append(True)
                await asyncio.sleep(0.01)  # simulate options construction
                in_critical.pop()

        await asyncio.gather(
            fake_session("A"),
            fake_session("B"),
            fake_session("C"),
        )
        assert not overlap_detected, "Lock failed to prevent concurrent access"

    @pytest.mark.asyncio
    async def test_env_lock_on_exception_releases(self) -> None:
        """Lock is released even when options construction raises."""
        env_lock = asyncio.Lock()

        async def failing_setup() -> None:
            async with env_lock:
                raise RuntimeError("bad env")

        with pytest.raises(RuntimeError):
            await failing_setup()

        # Lock must be acquirable again
        assert not env_lock.locked()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_e2e_gaps.py::TestCliParallelExecution -v`
Expected: FAIL — `TestCliSubprocessConcurrency` still exists (class not yet renamed). New tests should fail or not exist yet.

---

### Task 2: Update CLAUDECODE pop/restore tests (Red)

Update tests to validate the pop-once-at-run-level pattern.

**Files:**
- Modify: `tests/test_cli_commands.py:865-1009`

**Step 1: Update the test class to verify pop-once behavior**

The existing `TestSdkAgentExecution` tests check that CLAUDECODE is popped per-task. Update them to verify it's popped at the `run()` level (before `task_handler` is entered).

In `test_claudecode_popped_and_restored_on_success`, the `FakeAgentSession.__aenter__` currently checks `os.environ.get("CLAUDECODE")` expecting `None`. This will still pass with pop-once — CLAUDECODE is absent during the entire run. No change needed to the assertion, but the `FakeAgentSession` should NOT see the per-task pop/restore (because it won't exist). The test should verify that CLAUDECODE is absent during `__aenter__` and restored after `run()` completes.

The existing tests are actually compatible with the pop-once change — they just verify CLAUDECODE is absent during session spawn and present after run(). Keep them as-is for now; they'll validate the new behavior.

**Step 2: Run existing CLAUDECODE tests to confirm they pass on current code**

Run: `uv run pytest tests/test_cli_commands.py::TestSdkAgentExecution -v`
Expected: PASS (baseline)

---

### Task 3: Pop CLAUDECODE once at the top of `main()` (Green)

**Files:**
- Modify: `claw_forge/cli.py:419` (inside `async def main()`)

**Step 1: Add pop-once at the top of `main()`**

At `cli.py:419`, wrap the body of `main()` in a CLAUDECODE pop/restore:

```python
    async def main() -> None:
        # Pop CLAUDECODE once for the entire run — prevents the claude CLI
        # from refusing to start (it detects nesting via this env var).
        # Restored in finally so the parent session is unaffected.
        _saved_claudecode = os.environ.pop("CLAUDECODE", None)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            # ... rest of main() unchanged ...
        finally:
            if _saved_claudecode is not None:
                os.environ["CLAUDECODE"] = _saved_claudecode
```

The existing body of `main()` (from `async with engine.begin()` through the dispatcher summary) moves inside the `try` block. The indentation of the entire body increases by one level.

**Step 2: Run CLAUDECODE tests**

Run: `uv run pytest tests/test_cli_commands.py::TestSdkAgentExecution -v`
Expected: PASS

---

### Task 4: Replace `_cli_semaphore` with `_env_lock` (Green)

**Files:**
- Modify: `claw_forge/cli.py:527-533` (semaphore declaration)
- Modify: `claw_forge/cli.py:652-767` (task_handler SDK path)

**Step 1: Replace the semaphore with an asyncio.Lock**

At `cli.py:527-533`, replace:

```python
            # Semaphore to serialise claude CLI subprocess spawning.
            # Python's asyncio SIGCHLD handler races when multiple subprocesses
            # exit concurrently — one process reaps another's PID, causing
            # "Unknown child process pid N, will report returncode 255".
            # Limiting to 1 concurrent CLI invocation eliminates the race.
            # API-only mode (pool) is unaffected and runs fully concurrently.
            _cli_semaphore = asyncio.Semaphore(1)
```

With:

```python
            # Lock to serialise env-sensitive options construction.
            # Matches the _env_client_lock pattern from autonomous-coding:
            # env reads + ClaudeAgentOptions creation happen under lock;
            # AgentSession connect + agent execution run fully in parallel.
            # The dispatcher's Semaphore(max_concurrency) gates overall
            # concurrency; this lock only prevents env-read races.
            _env_lock = asyncio.Lock()
```

**Step 2: Restructure the SDK execution path**

At `cli.py:652-767`, restructure the `if sdk_available:` block. Replace:

```python
                        if sdk_available:
                            from claude_agent_sdk import ClaudeAgentOptions

                            from claw_forge.agent.session import AgentSession
                            # Resolve auth: ...
                            sdk_env: dict[str, str] = {}
                            _api_key = os.environ.get("ANTHROPIC_API_KEY", "")
                            # ... key resolution ...
                            if _api_key:
                                sdk_env["ANTHROPIC_API_KEY"] = _api_key
                            elif not _api_key:
                                # ... oauth fallback ...

                            options = ClaudeAgentOptions(
                                model=model,
                                cwd=str(project_path),
                                env=sdk_env,
                                permission_mode="bypassPermissions",
                            )
                            full_output: list[str] = []
                            try:
                                _saved_claudecode = os.environ.pop("CLAUDECODE", None)
                                try:
                                    async with (
                                        _cli_semaphore,
                                        AgentSession(options) as agent_session,
                                    ):
                                        async for msg in agent_session.run(prompt):
                                            # ... message processing ...
                                finally:
                                    if _saved_claudecode is not None:
                                        os.environ["CLAUDECODE"] = _saved_claudecode
                                # ... output verification ...
                            except Exception as sdk_exc:
                                # ... error handling ...
```

With:

```python
                        if sdk_available:
                            from claude_agent_sdk import ClaudeAgentOptions

                            from claw_forge.agent.session import AgentSession

                            # UNDER LOCK: env reads + options construction
                            # (matches autonomous-coding _env_client_lock pattern)
                            async with _env_lock:
                                sdk_env: dict[str, str] = {}
                                _api_key = os.environ.get("ANTHROPIC_API_KEY", "")
                                if not _api_key and pool is not None:
                                    _provs = pool.providers
                                    if _provs and hasattr(_provs[0], "config"):
                                        _api_key = _provs[0].config.api_key or ""
                                if _api_key:
                                    sdk_env["ANTHROPIC_API_KEY"] = _api_key
                                elif not _api_key:
                                    _oauth_tok = os.environ.get("ANTHROPIC_SETUP_TOKEN", "")
                                    if not _oauth_tok and pool is not None:
                                        _provs = pool.providers
                                        if _provs and hasattr(_provs[0], "config"):
                                            _cfg = _provs[0].config
                                            _oauth_tok = getattr(_cfg, "oauth_token", "") or ""
                                    if _oauth_tok:
                                        sdk_env["ANTHROPIC_SETUP_TOKEN"] = _oauth_tok

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
                                        _cls = type(msg).__name__
                                        if _cls == "ResultMessage":
                                            if getattr(msg, "result", None):
                                                full_output.append(msg.result)
                                                await _log_agent(
                                                    http, task_node.id, task_name,
                                                    "result", msg.result[:500],
                                                )
                                            continue
                                        if _cls != "AssistantMessage":
                                            continue
                                        content = getattr(msg, "content", None)
                                        if not isinstance(content, list):
                                            continue
                                        for block in content:
                                            _bcls = type(block).__name__
                                            if _bcls == "TextBlock":
                                                full_output.append(block.text)
                                                await _log_agent(
                                                    http, task_node.id, task_name,
                                                    "assistant", block.text[:500],
                                                )
                                            elif _bcls == "ToolUseBlock":
                                                _tn = getattr(block, "name", "?")
                                                _raw = getattr(block, "input", {})
                                                _ti = _fmt_tool(_tn, _raw)
                                                await _log_agent(
                                                    http, task_node.id, task_name,
                                                    "tool_use", f"{_tn} → {_ti}",
                                                )
                                            elif _bcls == "ToolResultBlock":
                                                _is_err = getattr(block, "is_error", False)
                                                _tc = str(getattr(block, "content", ""))[:300]
                                                await _log_agent(
                                                    http, task_node.id, task_name,
                                                    "tool_result", _tc,
                                                    level="error" if _is_err else "info",
                                                )
                                        if getattr(msg, "error", None):
                                            raise RuntimeError(
                                                f"Agent error: {msg.error} — "
                                                "check `claude login` or verify API key in .env"
                                            )
                                output = "\n".join(full_output)
                                if not output.strip():
                                    raise RuntimeError(
                                        "Agent produced no output — "
                                        "check `claude login` or verify API key in .env"
                                    )
                                success = True
                            except Exception as sdk_exc:
                                output = str(sdk_exc)
                                success = False
                                await _log_agent(
                                    http, task_node.id, task_name,
                                    "error", str(sdk_exc)[:500],
                                    level="error",
                                )
```

Key structural changes:
- `_cli_semaphore` → `_env_lock` (narrow lock)
- Lock covers only env reads + `ClaudeAgentOptions()` construction
- `AgentSession` context manager + `run()` streaming happen OUTSIDE the lock
- Per-task CLAUDECODE pop/restore removed entirely (handled by Task 3)

**Step 3: Run all tests**

Run: `uv run pytest tests/test_cli_commands.py::TestSdkAgentExecution tests/test_e2e_gaps.py::TestCliParallelExecution -v`
Expected: PASS

---

### Task 5: Update e2e tests (Green)

**Files:**
- Modify: `tests/test_e2e_gaps.py:133-179`

**Step 1: Replace the old test class with the new one from Task 1**

Remove `TestCliSubprocessConcurrency` and add `TestCliParallelExecution` (the tests written in Task 1).

**Step 2: Run the new tests**

Run: `uv run pytest tests/test_e2e_gaps.py::TestCliParallelExecution -v`
Expected: PASS

---

### Task 6: Run full test suite + lint

**Files:** None (validation only)

**Step 1: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: All tests pass

**Step 2: Run linter**

Run: `uv run ruff check claw_forge/ tests/`
Expected: No errors

**Step 3: Run type checker**

Run: `uv run mypy claw_forge/ --ignore-missing-imports`
Expected: No new errors

---

### Task 7: Commit

**Step 1: Stage and commit**

```bash
git add claw_forge/cli.py tests/test_e2e_gaps.py tests/test_cli_commands.py
git commit -m "fix: enable parallel CLI agent execution

Replace _cli_semaphore(1) — which serialized all claude CLI agents to
one-at-a-time — with a narrow asyncio.Lock() around env reads + options
construction. Agent connect + execution now runs fully in parallel,
gated only by the dispatcher's Semaphore(max_concurrency).

Pattern matches the proven approach from autonomous-coding:
- Pop CLAUDECODE once at the top of run(), not per-task
- asyncio.Lock protects only the env-sensitive setup phase
- AgentSession connect + streaming run concurrently outside the lock

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```
