# Computation Awareness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in CPU offloading, sub-agent guidance with soft-limits, and real-time sub-agent count on UI task cards.

**Architecture:** Three independent parts: (A) `@offload_heavy` decorator + `ProcessPoolExecutor` for CPU-bound work and `asyncio.to_thread()` for I/O-bound work, (B) factory-pattern subagent hooks with per-task counter and soft-limit, (C) `active_subagents` column on Task model with WebSocket broadcast to UI `FeatureCard`.

**Tech Stack:** Python 3.11+ asyncio, ProcessPoolExecutor, httpx, SQLAlchemy, FastAPI, React/TypeScript

**Spec:** `docs/superpowers/specs/2026-03-21-computation-awareness-design.md`

---

### Task 1: `@offload_heavy` decorator and process pool

**Files:**
- Create: `claw_forge/compute.py`
- Create: `tests/test_compute.py`

- [ ] **Step 1: Write the failing test for offload_heavy**

```python
# tests/test_compute.py
"""Tests for claw_forge.compute — @offload_heavy decorator and process pool."""
from __future__ import annotations

import asyncio
import os

import pytest

from claw_forge.compute import get_pool, offload_heavy, shutdown_pool


def _cpu_work(n: int) -> int:
    """Pure CPU-bound function — returns (n * 2) + pid to prove cross-process."""
    return n * 2 + os.getpid()


@offload_heavy
def decorated_cpu_work(n: int) -> int:
    return n * 2 + os.getpid()


class TestOffloadHeavy:
    @pytest.mark.asyncio
    async def test_returns_awaitable(self) -> None:
        result = decorated_cpu_work(5)
        assert asyncio.iscoroutine(result)
        await result  # cleanup

    @pytest.mark.asyncio
    async def test_runs_in_separate_process(self) -> None:
        result = await decorated_cpu_work(5)
        # Result includes child pid, which must differ from ours
        child_component = result - 10  # n*2 = 10, remainder is child pid
        assert child_component != os.getpid()

    @pytest.mark.asyncio
    async def test_correct_computation(self) -> None:
        result = await decorated_cpu_work(7)
        # result = 7*2 + child_pid; we just verify it's >= 14
        assert result >= 14


class TestPool:
    def test_lazy_init(self) -> None:
        # Pool should not exist at import time
        from claw_forge import compute
        # After calling get_pool, it should exist
        pool = get_pool()
        assert pool is not None
        assert pool._max_workers <= 4  # capped

    def test_shutdown_idempotent(self) -> None:
        shutdown_pool()
        shutdown_pool()  # should not raise

    def test_pool_recreated_after_shutdown(self) -> None:
        pool1 = get_pool()
        shutdown_pool()
        pool2 = get_pool()
        assert pool2 is not pool1

    @pytest.mark.asyncio
    async def test_kwargs_not_supported(self) -> None:
        """run_in_executor does not support kwargs — verify clear failure."""
        with pytest.raises(TypeError):
            await decorated_cpu_work(n=5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_compute.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'claw_forge.compute'`

- [ ] **Step 3: Implement compute.py**

```python
# claw_forge/compute.py
"""Opt-in CPU offloading via ProcessPoolExecutor."""
from __future__ import annotations

import atexit
import asyncio
import os
from concurrent.futures import ProcessPoolExecutor
from functools import wraps
from typing import Any, Callable, TypeVar

_pool: ProcessPoolExecutor | None = None
_F = TypeVar("_F", bound=Callable[..., Any])


def get_pool() -> ProcessPoolExecutor:
    """Lazy-init a process pool capped at 4 workers."""
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=min(os.cpu_count() or 2, 4))
        atexit.register(shutdown_pool)
    return _pool


def shutdown_pool() -> None:
    """Shut down the process pool. Idempotent."""
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False)
        _pool = None


def offload_heavy(fn: _F) -> _F:
    """Decorator: run a sync function in the process pool.

    The decorated function becomes a coroutine. Requirements:
    - Must be a module-level function (picklable)
    - Arguments and return value must be picklable
    - Must be pure (no shared mutable state)
    """
    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(get_pool(), fn, *args)

    return wrapper  # type: ignore[return-value]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_compute.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add claw_forge/compute.py tests/test_compute.py
git commit -m "feat: add @offload_heavy decorator and process pool"
```

---

### Task 2: Refactor `_assign_dependencies` to return data and offload

**Files:**
- Modify: `claw_forge/spec/parser.py`
- Modify: `tests/` (existing parser tests should still pass)

- [ ] **Step 1: Run existing parser tests to establish baseline**

Run: `uv run pytest tests/ -k "parser or spec" -v`
Expected: all pass

- [ ] **Step 2: Refactor `_assign_dependencies` to return data instead of mutating**

In `claw_forge/spec/parser.py`, change `_assign_dependencies` from:

```python
def _assign_dependencies(features: list[FeatureItem], phases: list[str]) -> None:
    ...
    for feat_idx in phase_feature_indices[p_idx]:
        features[feat_idx].depends_on_indices = list(prev_phase_indices)
```

To:

```python
def _assign_dependencies(
    features: list[FeatureItem], phases: list[str],
) -> list[list[int]]:
    """Compute dependency indices for each feature based on phase ordering.

    Returns a list parallel to *features* where each element is the
    list of ``depends_on_indices`` for that feature.  The caller applies
    the results — this function is pure (no mutation).
    """
    result: list[list[int]] = [list(f.depends_on_indices) for f in features]
    if not phases:
        return result

    phase_feature_indices: list[list[int]] = [[] for _ in phases]

    for i, feature in enumerate(features):
        assigned = False
        for p_idx, phase_title in enumerate(phases):
            phase_keywords = set(phase_title.lower().split())
            cat_keywords = set(feature.category.lower().split())
            if phase_keywords & cat_keywords:
                phase_feature_indices[p_idx].append(i)
                assigned = True
                break
        if not assigned:
            mid = len(phases) // 2
            phase_feature_indices[mid].append(i)

    for p_idx in range(1, len(phases)):
        prev_phase_indices = phase_feature_indices[p_idx - 1]
        for feat_idx in phase_feature_indices[p_idx]:
            result[feat_idx] = list(prev_phase_indices)

    return result
```

- [ ] **Step 3: Update the call site in `_parse_xml` (line 265)**

Change:
```python
_assign_dependencies(features, phases)
```
To:
```python
dep_indices = _assign_dependencies(features, phases)
for i, deps in enumerate(dep_indices):
    features[i].depends_on_indices = deps
```

- [ ] **Step 4: Run parser tests to verify refactor is correct**

Run: `uv run pytest tests/ -k "parser or spec" -v`
Expected: all pass (behavior unchanged)

- [ ] **Step 5: Apply `@offload_heavy` decorator to `_assign_dependencies`**

```python
from claw_forge.compute import offload_heavy

@offload_heavy
def _assign_dependencies(
    features: list[FeatureItem], phases: list[str],
) -> list[list[int]]:
    ...
```

Note: `@offload_heavy` makes this function a coroutine, so the call site must `await` it. Since `_parse_xml` is a sync classmethod, wrap the `_assign_dependencies` call with `asyncio.run()` for now — it will be called from `asyncio.to_thread()` anyway (see next step).

Update the call site in `_parse_xml`:
```python
import asyncio
dep_indices = asyncio.get_event_loop().run_until_complete(_assign_dependencies(features, phases))
for i, deps in enumerate(dep_indices):
    features[i].depends_on_indices = deps
```

Alternatively (simpler): keep `_assign_dependencies` undecorated and call it directly — the function only becomes expensive with 400+ features, and it runs once. The `asyncio.to_thread()` wrapper on `ProjectSpec.from_file()` in the initializer already offloads the entire parsing call to a thread. **Recommended: skip the decorator on this function and just rely on the existing `to_thread` offloading of the whole `from_file()` call.**

Choose the simpler approach: do NOT decorate `_assign_dependencies`. The refactor to pure function is still valuable for testability.

- [ ] **Step 6: Commit**

```bash
git add claw_forge/spec/parser.py
git commit -m "refactor: make _assign_dependencies pure (return data, no mutation)"
```

---

### Task 3: Wrap `detect_lsp_plugins` with `asyncio.to_thread`

**Files:**
- Modify: `claw_forge/lsp.py`
- Modify: `claw_forge/agent/runner.py` (call site)

- [ ] **Step 1: Find the call site in runner.py**

Run: `grep -n "detect_lsp_plugins" claw_forge/agent/runner.py`

- [ ] **Step 2: Create async wrapper in lsp.py**

Add after `detect_lsp_plugins`:

```python
async def detect_lsp_plugins_async(project_path: str | Path) -> list[SdkPluginConfig]:
    """Async wrapper — runs blocking rglob scan in a thread."""
    import asyncio
    return await asyncio.to_thread(detect_lsp_plugins, project_path)
```

- [ ] **Step 3: Update runner.py call site to use async version**

Change:
```python
from claw_forge.lsp import detect_lsp_plugins
...
lsp_plugins = detect_lsp_plugins(project_path)
```
To:
```python
from claw_forge.lsp import detect_lsp_plugins_async
...
lsp_plugins = await detect_lsp_plugins_async(project_path)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/ -k "lsp or runner" -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add claw_forge/lsp.py claw_forge/agent/runner.py
git commit -m "perf: wrap detect_lsp_plugins in asyncio.to_thread for non-blocking I/O"
```

---

### Task 4: Sub-agent hook factory with counter and soft-limit

**Files:**
- Modify: `claw_forge/agent/hooks.py`
- Create: `tests/test_hooks_subagent_limit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hooks_subagent_limit.py
"""Tests for sub-agent hooks: counter tracking and soft-limit."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from claw_forge.agent.hooks import make_subagent_hooks


class TestSubagentHooks:
    @pytest.mark.asyncio
    async def test_counter_increments_on_start(self) -> None:
        start_hook, stop_hook, state = make_subagent_hooks(max_subagents=5)
        await start_hook({"agent_id": "a1", "agent_type": "coding"}, None, {})
        assert state["total_spawned"] == 1
        assert state["active"] == 1

    @pytest.mark.asyncio
    async def test_counter_decrements_on_stop(self) -> None:
        start_hook, stop_hook, state = make_subagent_hooks(max_subagents=5)
        await start_hook({"agent_id": "a1", "agent_type": "coding"}, None, {})
        await stop_hook({"agent_id": "a1", "agent_type": "coding"}, None, {})
        assert state["active"] == 0
        assert state["total_spawned"] == 1

    @pytest.mark.asyncio
    async def test_soft_limit_warning(self) -> None:
        start_hook, stop_hook, state = make_subagent_hooks(max_subagents=2)
        await start_hook({"agent_id": "a1", "agent_type": "coding"}, None, {})
        await start_hook({"agent_id": "a2", "agent_type": "coding"}, None, {})
        result = await start_hook({"agent_id": "a3", "agent_type": "coding"}, None, {})
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "limit" in ctx.lower() or "sequentially" in ctx.lower()

    @pytest.mark.asyncio
    async def test_no_warning_below_limit(self) -> None:
        start_hook, stop_hook, state = make_subagent_hooks(max_subagents=5)
        result = await start_hook({"agent_id": "a1", "agent_type": "coding"}, None, {})
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "limit" not in ctx.lower()

    @pytest.mark.asyncio
    async def test_unlimited_when_zero(self) -> None:
        start_hook, stop_hook, state = make_subagent_hooks(max_subagents=0)
        for i in range(20):
            result = await start_hook({"agent_id": f"a{i}", "agent_type": "coding"}, None, {})
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "limit" not in ctx.lower()

    @pytest.mark.asyncio
    async def test_active_never_negative(self) -> None:
        start_hook, stop_hook, state = make_subagent_hooks(max_subagents=5)
        await stop_hook({"agent_id": "a1", "agent_type": "coding"}, None, {})
        assert state["active"] == 0  # clamped at 0

    @pytest.mark.asyncio
    async def test_stop_hook_returns_subagent_stop_event(self) -> None:
        start_hook, stop_hook, state = make_subagent_hooks(max_subagents=5)
        await start_hook({"agent_id": "a1", "agent_type": "coding"}, None, {})
        result = await stop_hook({"agent_id": "a1", "agent_type": "coding"}, None, {})
        assert result["hookSpecificOutput"]["hookEventName"] == "SubagentStop"

    @pytest.mark.asyncio
    async def test_patch_called_on_start(self) -> None:
        start_hook, stop_hook, state = make_subagent_hooks(
            max_subagents=5, state_url="http://localhost:8420",
        )
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await start_hook(
                {"agent_id": "a1", "agent_type": "coding", "task_id": "t1"}, None, {},
            )
            # Give fire-and-forget task a chance to run
            await asyncio.sleep(0.05)
            mock_client.patch.assert_called_once()

    @pytest.mark.asyncio
    async def test_patch_failure_does_not_block(self) -> None:
        start_hook, stop_hook, state = make_subagent_hooks(
            max_subagents=5, state_url="http://localhost:8420",
        )
        with patch("httpx.AsyncClient", side_effect=Exception("connection refused")):
            # Should not raise — PATCH is best-effort
            await start_hook(
                {"agent_id": "a1", "agent_type": "coding", "task_id": "t1"}, None, {},
            )
            await asyncio.sleep(0.05)
            assert state["active"] == 1  # counter still updated
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_hooks_subagent_limit.py -v`
Expected: FAIL — `ImportError: cannot import name 'make_subagent_hooks'`

- [ ] **Step 3: Implement `make_subagent_hooks` factory**

In `claw_forge/agent/hooks.py`, replace the plain `subagent_start_hook` and `subagent_stop_hook` functions with:

```python
def make_subagent_hooks(
    max_subagents: int = 5,
    state_url: str | None = None,
) -> tuple[Callable[..., Any], Callable[..., Any], dict[str, int]]:
    """Factory for SubagentStart/Stop hooks with per-task counter and soft-limit.

    Args:
        max_subagents: Max sub-agents before injecting warning. 0 = unlimited.
        state_url: Optional state service URL for PATCH updates.

    Returns:
        (start_hook, stop_hook, state_dict) — state_dict exposes counters
        for testing: {"active": int, "total_spawned": int}.
    """
    state: dict[str, int] = {"active": 0, "total_spawned": 0}

    async def _patch_subagent_count(task_id: str | None, count: int) -> None:
        """Fire-and-forget PATCH to state service."""
        if not state_url or not task_id:
            return
        try:
            import httpx
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.patch(
                    f"{state_url}/tasks/{task_id}",
                    json={"active_subagents": count},
                )
        except Exception:
            pass  # best-effort

    async def start_hook(
        input_data: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> SyncHookJSONOutput:
        data: dict[str, Any] = cast(dict[str, Any], input_data) if isinstance(input_data, dict) else {}
        agent_id = data.get("agent_id", "")
        agent_type = data.get("agent_type", "")

        state["active"] += 1
        state["total_spawned"] += 1
        print(f"[SubAgent] Starting: {agent_type} ({agent_id}) — active: {state['active']}")

        # Fire-and-forget PATCH
        task_id = data.get("task_id")
        asyncio.create_task(_patch_subagent_count(task_id, state["active"]))

        additional = f"You are a {agent_type} sub-agent. Follow claw-forge coding standards."
        if max_subagents > 0 and state["total_spawned"] > max_subagents:
            additional += (
                f" You have reached the sub-agent limit ({max_subagents}) for this task."
                " Complete remaining work sequentially — do not spawn more sub-agents."
            )

        return SyncHookJSONOutput(
            hookSpecificOutput={
                "hookEventName": "SubagentStart",
                "additionalContext": additional,
            }
        )

    async def stop_hook(
        input_data: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> SyncHookJSONOutput:
        data: dict[str, Any] = cast(dict[str, Any], input_data) if isinstance(input_data, dict) else {}
        agent_id = data.get("agent_id", "")
        agent_type = data.get("agent_type", "")

        state["active"] = max(0, state["active"] - 1)
        print(f"[SubAgent] Stopped: {agent_type} ({agent_id}) — active: {state['active']}")

        task_id = data.get("task_id")
        asyncio.create_task(_patch_subagent_count(task_id, state["active"]))

        return SyncHookJSONOutput(
            hookSpecificOutput={
                "hookEventName": "SubagentStop",
                "additionalContext": "",
            }
        )

    return start_hook, stop_hook, state
```

- [ ] **Step 4: Update `get_default_hooks` to use the factory**

Change in `get_default_hooks`:
```python
"SubagentStart": [
    HookMatcher(hooks=[subagent_start_hook]),
],
"SubagentStop": [
    HookMatcher(hooks=[subagent_stop_hook]),
],
```
To:
```python
_sa_start, _sa_stop, _ = make_subagent_hooks(
    max_subagents=max_subagents,
    state_url=state_url,
)
...
"SubagentStart": [
    HookMatcher(hooks=[_sa_start]),
],
"SubagentStop": [
    HookMatcher(hooks=[_sa_stop]),
],
```

And add `max_subagents: int = 5` and `state_url: str | None = None` parameters to `get_default_hooks`.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_hooks_subagent_limit.py -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add claw_forge/agent/hooks.py tests/test_hooks_subagent_limit.py
git commit -m "feat: sub-agent hook factory with counter and soft-limit"
```

---

### Task 5: Add `active_subagents` to Task model and state service

**Files:**
- Modify: `claw_forge/state/models.py`
- Modify: `claw_forge/state/service.py`

- [ ] **Step 1: Add column to Task model**

In `claw_forge/state/models.py`, add after the `cost_usd` field (line 145):

```python
active_subagents: Mapped[int] = mapped_column(Integer, default=0)
```

- [ ] **Step 2: Add `active_subagents` to `UpdateTaskRequest`**

In `claw_forge/state/service.py`, add to `UpdateTaskRequest`:

```python
active_subagents: int | None = None
```

- [ ] **Step 3: Handle in `update_task` endpoint**

In the `update_task` function, add after the `cost_usd` handling (around line 730):

```python
if req.active_subagents is not None:
    task.active_subagents = req.active_subagents
```

- [ ] **Step 4: Include in `_task_summary` and WebSocket broadcast**

In `_task_summary` (line 33), add:
```python
"active_subagents": task.active_subagents,
```

In the `update_task` emit_event payload (line 736), add:
```python
"active_subagents": task.active_subagents,
```

- [ ] **Step 5: Run existing state service tests**

Run: `uv run pytest tests/ -k "state or service or model" -v`
Expected: all pass

- [ ] **Step 6: Add a test for active_subagents roundtrip**

Add to the existing state service test file (or create `tests/test_active_subagents.py`):

```python
@pytest.mark.asyncio
async def test_patch_active_subagents(client: AsyncClient, task_id: str) -> None:
    resp = await client.patch(f"/tasks/{task_id}", json={"active_subagents": 3})
    assert resp.status_code == 200
    detail = await client.get(f"/tasks/{task_id}")
    assert detail.json()["active_subagents"] == 3
```

- [ ] **Step 7: Commit**

```bash
git add claw_forge/state/models.py claw_forge/state/service.py tests/
git commit -m "feat: add active_subagents column to Task model and PATCH endpoint"
```

---

### Task 6: Sub-agent guidance in plugin system prompts

**Files:**
- Modify: `claw_forge/plugins/coding.py`
- Modify: `claw_forge/plugins/bugfix.py`

- [ ] **Step 1: Add sub-agent guidance to CodingPlugin.get_system_prompt**

In `claw_forge/plugins/coding.py`, add before the final `f"Project: ..."` line (line 103):

```python
"### Parallel Sub-Agents\n"
"When your task involves 5+ independent file modifications or independent subtasks, "
"use the Agent tool to parallelize:\n"
"- Spawn one sub-agent per independent file or module\n"
"- Each sub-agent gets a focused, self-contained instruction\n"
"- Do NOT spawn sub-agents for sequential work (where step N depends on step N-1)\n\n"
```

- [ ] **Step 2: Add sub-agent guidance to BugFixPlugin**

In `claw_forge/plugins/bugfix.py`, add to `_BUG_FIX_PROTOCOL` string after the "Rules:" section:

```python
"\nParallel Sub-Agents:\n"
"If the fix requires changes to 5+ independent files, use the Agent tool to "
"parallelize independent modifications. Do NOT use sub-agents for the sequential "
"reproduce → isolate → fix → verify workflow.\n"
```

- [ ] **Step 3: Run plugin tests**

Run: `uv run pytest tests/ -k "plugin or coding or bugfix" -v`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add claw_forge/plugins/coding.py claw_forge/plugins/bugfix.py
git commit -m "feat: add sub-agent parallelism guidance to coding and bugfix plugins"
```

---

### Task 7: Wire config and CLI

**Files:**
- Modify: `claw_forge/cli.py`

- [ ] **Step 1: Read `agent.max_subagents_per_task` from config**

In `cli.py`, find where `git_cfg` is read (around line 535) and add nearby:

```python
agent_cfg = cfg.get("agent", {})
max_subagents = agent_cfg.get("max_subagents_per_task", 5)
```

- [ ] **Step 2: Pass to `get_default_hooks` call**

In `cli.py`, `get_default_hooks` is imported as the alias `_ghooks`. The call is around line 800, inside a nested async function — NOT near the config reading at line 535. The `max_subagents` variable read at ~535 is already in scope at ~800 (it's in the enclosing `run` function). Find the `_ghooks(` call and add the new parameters:

```python
agent_hooks = _ghooks(
    edit_mode=edit_mode,
    loop_detect_threshold=loop_detect_threshold,
    verify_on_exit=effective_verify_on_exit,
    auto_push=effective_auto_push,
    max_subagents=max_subagents,
    state_url=f"http://localhost:{port}",
)
```

- [ ] **Step 3: Run CLI tests**

Run: `uv run pytest tests/ -k "cli" -v`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add claw_forge/cli.py
git commit -m "feat: wire max_subagents_per_task config to hook factory"
```

---

### Task 8: UI — sub-agent badge on FeatureCard

**Files:**
- Modify: `ui/src/types.ts`
- Modify: `ui/src/components/FeatureCard.tsx`

- [ ] **Step 1: Add `active_subagents` to Feature type**

In `ui/src/types.ts`, add to the `Feature` interface after `output_tokens`:

```typescript
/** Number of currently active sub-agents for this task */
active_subagents?: number;
```

- [ ] **Step 2: Add badge to FeatureCard**

In `ui/src/components/FeatureCard.tsx`, find the status badge rendering area. Add a sub-agent badge that appears only when `active_subagents > 0`:

```tsx
{feature.active_subagents != null && feature.active_subagents > 0 && (
  <span className="inline-flex items-center gap-1 rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-700 dark:bg-violet-900 dark:text-violet-200">
    <span className="text-[10px]">&#9889;</span>
    {feature.active_subagents} sub-agent{feature.active_subagents > 1 ? "s" : ""}
  </span>
)}
```

- [ ] **Step 3: Build UI to verify no TypeScript errors**

Run: `npm --prefix ui run build`
Expected: build succeeds

- [ ] **Step 4: Commit**

```bash
git add ui/src/types.ts ui/src/components/FeatureCard.tsx
git commit -m "feat: show active sub-agent count badge on FeatureCard"
```

---

### Task 9: Full integration test and lint

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: all pass

- [ ] **Step 2: Run linter**

Run: `uv run ruff check claw_forge/ tests/`
Expected: no errors (or fix with `--fix`)

- [ ] **Step 3: Run type checker**

Run: `uv run mypy claw_forge/ --ignore-missing-imports`
Expected: no new errors

- [ ] **Step 4: Run coverage check**

Run: `uv run pytest tests/ -q --cov=claw_forge --cov-report=term-missing`
Expected: >= 90% coverage

- [ ] **Step 5: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: lint and type errors from computation awareness feature"
```
