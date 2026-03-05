# Provider Model Pool Selection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let each provider expose its `model_map` entries as checkboxes in the Kanban UI; checked models form a round-robin pool the pool manager cycles through when routing requests to that provider.

**Architecture:** Add `active_models: list[str]` to `ProviderConfig` and a per-provider round-robin model selector to `ProviderPoolManager`. Extend `/pool/status` to return `model_map`/`active_models`, add `PATCH /pool/providers/{name}/models` endpoint, and update the React `ProviderRow` to render checkboxes that toggle the active model pool.

**Tech Stack:** Python (FastAPI, dataclasses, asyncio), React 18, TypeScript, TanStack Query, Tailwind CSS

---

### Task 1: Add `active_models` to `ProviderConfig`

**Files:**
- Modify: `claw_forge/pool/providers/base.py`
- Test: `tests/test_pool_toggle.py` (add to `TestLoadConfigsFromYaml`)

**Step 1: Write the failing test**

Add to `tests/test_pool_toggle.py` inside `TestLoadConfigsFromYaml`:

```python
def test_active_models_loaded_from_yaml(self) -> None:
    from claw_forge.pool.providers.registry import load_configs_from_yaml
    data = {
        "providers": {
            "my-provider": {
                "type": "anthropic",
                "api_key": "sk-test",
                "model_map": {"fast": "claude-haiku-4-5", "smart": "claude-opus-4-6"},
                "active_models": ["claude-haiku-4-5", "claude-opus-4-6"],
            }
        }
    }
    configs = load_configs_from_yaml(data)
    assert configs[0].active_models == ["claude-haiku-4-5", "claude-opus-4-6"]

def test_active_models_defaults_to_empty(self) -> None:
    from claw_forge.pool.providers.registry import load_configs_from_yaml
    data = {"providers": {"p": {"type": "anthropic", "api_key": "k"}}}
    configs = load_configs_from_yaml(data)
    assert configs[0].active_models == []
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_pool_toggle.py::TestLoadConfigsFromYaml::test_active_models_loaded_from_yaml -v
```
Expected: `AttributeError: 'ProviderConfig' object has no attribute 'active_models'`

**Step 3: Add field to `ProviderConfig`**

In `claw_forge/pool/providers/base.py`, add after the `model_map` field:

```python
active_models: list[str] = field(default_factory=list)
```

(The `load_configs_from_yaml` registry already passes any known dataclass field from YAML via `**{k: v ... if k in ProviderConfig.__dataclass_fields__}`, so no registry change needed.)

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_pool_toggle.py::TestLoadConfigsFromYaml -v
```
Expected: all pass

**Step 5: Commit**

```bash
git add claw_forge/pool/providers/base.py tests/test_pool_toggle.py
git commit -m "feat: add active_models field to ProviderConfig"
```

---

### Task 2: Add model pool round-robin to `ProviderPoolManager`

**Files:**
- Modify: `claw_forge/pool/manager.py`
- Test: `tests/test_provider_model_pool.py` (new file)

**Step 1: Write the failing tests**

Create `tests/test_provider_model_pool.py`:

```python
"""Tests for per-provider model pool round-robin in ProviderPoolManager."""
from __future__ import annotations

import pytest

from claw_forge.pool.health import CircuitBreaker
from claw_forge.pool.manager import ProviderPoolManager
from claw_forge.pool.providers.base import (
    ProviderConfig, ProviderResponse, ProviderType,
)
from claw_forge.pool.providers.base import BaseProvider


class RecordingProvider(BaseProvider):
    """Records the model arg passed to each execute() call."""
    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self.calls: list[str] = []

    async def execute(self, model: str, messages: list, **kwargs) -> ProviderResponse:
        self.calls.append(model)
        return ProviderResponse(
            content="ok", model=model, provider_name=self.name,
            input_tokens=10, output_tokens=5, latency_ms=50.0,
        )

    async def health_check(self) -> bool:
        return True


def make_mgr_with_pool(active_models: list[str]) -> tuple[ProviderPoolManager, RecordingProvider]:
    cfg = ProviderConfig(
        name="p1",
        provider_type=ProviderType.ANTHROPIC,
        api_key="k",
        active_models=active_models,
    )
    mgr = ProviderPoolManager([cfg])
    provider = RecordingProvider(cfg)
    mgr._providers = [provider]
    mgr._circuits = {"p1": CircuitBreaker("p1")}
    return mgr, provider


class TestGetNextModel:
    def test_returns_none_when_pool_empty(self):
        mgr, _ = make_mgr_with_pool([])
        assert mgr.get_next_model("p1") is None

    def test_returns_none_for_unknown_provider(self):
        mgr, _ = make_mgr_with_pool(["m1"])
        assert mgr.get_next_model("ghost") is None

    def test_single_model_pool_always_returns_same(self):
        mgr, _ = make_mgr_with_pool(["claude-haiku-4-5"])
        assert mgr.get_next_model("p1") == "claude-haiku-4-5"
        assert mgr.get_next_model("p1") == "claude-haiku-4-5"

    def test_two_model_pool_round_robins(self):
        mgr, _ = make_mgr_with_pool(["haiku", "sonnet"])
        results = [mgr.get_next_model("p1") for _ in range(4)]
        assert results == ["haiku", "sonnet", "haiku", "sonnet"]


class TestSetProviderModels:
    def test_set_models_found_returns_true(self):
        mgr, _ = make_mgr_with_pool([])
        assert mgr.set_provider_models("p1", ["m1", "m2"]) is True

    def test_set_models_not_found_returns_false(self):
        mgr, _ = make_mgr_with_pool([])
        assert mgr.set_provider_models("ghost", ["m1"]) is False

    def test_set_models_resets_rr_index(self):
        mgr, _ = make_mgr_with_pool(["a", "b"])
        mgr.get_next_model("p1")  # advance index to 1
        mgr.set_provider_models("p1", ["x", "y", "z"])
        # After reset, should start from "x"
        assert mgr.get_next_model("p1") == "x"

    def test_set_empty_models_clears_pool(self):
        mgr, _ = make_mgr_with_pool(["a", "b"])
        mgr.set_provider_models("p1", [])
        assert mgr.get_next_model("p1") is None


class TestExecuteUsesModelPool:
    @pytest.mark.asyncio
    async def test_execute_uses_pool_model_not_caller_model(self):
        mgr, provider = make_mgr_with_pool(["claude-haiku-4-5", "claude-sonnet-4-6"])
        await mgr.execute("caller-supplied-model", [{"role": "user", "content": "hi"}])
        await mgr.execute("caller-supplied-model", [{"role": "user", "content": "hi"}])
        assert provider.calls == ["claude-haiku-4-5", "claude-sonnet-4-6"]

    @pytest.mark.asyncio
    async def test_execute_uses_caller_model_when_pool_empty(self):
        mgr, provider = make_mgr_with_pool([])
        await mgr.execute("caller-model", [{"role": "user", "content": "hi"}])
        assert provider.calls == ["caller-model"]

    @pytest.mark.asyncio
    async def test_get_pool_status_includes_active_models(self):
        mgr, _ = make_mgr_with_pool(["haiku", "sonnet"])
        status = await mgr.get_pool_status()
        p = status["providers"][0]
        assert "active_models" in p
        assert p["active_models"] == ["haiku", "sonnet"]
```

**Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_provider_model_pool.py -v
```
Expected: multiple failures (`AttributeError: 'ProviderPoolManager' has no attribute 'get_next_model'`)

**Step 3: Implement in `claw_forge/pool/manager.py`**

In `__init__`, add after `self._lock = asyncio.Lock()`:

```python
# Per-provider model pool for round-robin model selection.
# Initialized from config.active_models; empty list = use caller-supplied model.
self._model_pools: dict[str, list[str]] = {
    p.name: list(p.config.active_models) for p in self._providers
}
self._model_rr: dict[str, int] = {p.name: 0 for p in self._providers}
```

Add two new methods after `get_provider_enabled`:

```python
def get_next_model(self, provider_name: str) -> str | None:
    """Return the next active model for this provider in round-robin order.

    Returns None if the provider has no model pool (caller-supplied model used).
    """
    pool = self._model_pools.get(provider_name)
    if not pool:
        return None
    idx = self._model_rr.get(provider_name, 0)
    model = pool[idx % len(pool)]
    self._model_rr[provider_name] = (idx + 1) % len(pool)
    return model

def set_provider_models(self, name: str, active_models: list[str]) -> bool:
    """Update the active model pool for a provider at runtime.

    Resets the round-robin index. Returns True if the provider was found.
    """
    for p in self._providers:
        if p.name == name:
            self._model_pools[name] = list(active_models)
            self._model_rr[name] = 0
            p.config.active_models = list(active_models)
            return True
    return False
```

In the `execute()` method, inside the `for provider in ordered:` loop (before calling `provider.execute()`), add model override logic. Find:

```python
                try:
                    response: ProviderResponse = cast(
                        ProviderResponse,
                        await provider.execute(  # type: ignore[attr-defined]  # subclasses implement execute
                            model=model,
```

Replace with:

```python
                try:
                    effective_model = self.get_next_model(provider.name) or model
                    response: ProviderResponse = cast(
                        ProviderResponse,
                        await provider.execute(  # type: ignore[attr-defined]  # subclasses implement execute
                            model=effective_model,
```

Also apply the same override in the pinned-provider fast path. Find:

```python
            pinned_resp: ProviderResponse = cast(
                ProviderResponse,
                await pinned.execute(  # type: ignore[attr-defined]
                    model=model,
```

Replace with:

```python
            effective_model = self.get_next_model(provider_hint) or model
            pinned_resp: ProviderResponse = cast(
                ProviderResponse,
                await pinned.execute(  # type: ignore[attr-defined]
                    model=effective_model,
```

In `get_pool_status()`, in the provider dict being appended, add after `"model"`:

```python
"model_map": dict(p.config.model_map),
"active_models": list(self._model_pools.get(p.name, [])),
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_provider_model_pool.py tests/test_manager.py tests/test_pool_toggle.py -v
```
Expected: all pass

**Step 5: Commit**

```bash
git add claw_forge/pool/manager.py tests/test_provider_model_pool.py
git commit -m "feat: add per-provider model pool round-robin to ProviderPoolManager"
```

---

### Task 3: State service — new endpoint + pool_status model_map

**Files:**
- Modify: `claw_forge/state/service.py`
- Test: `tests/test_provider_model_pool.py` (append new class)

**Step 1: Write the failing tests**

Append to `tests/test_provider_model_pool.py`:

```python
import sys, types
if "claude_agent_sdk" not in sys.modules:
    sys.modules["claude_agent_sdk"] = types.ModuleType("claude_agent_sdk")

from fastapi.testclient import TestClient
from claw_forge.state.service import AgentStateService


def make_mgr_for_service() -> ProviderPoolManager:
    cfg = ProviderConfig(
        name="p1", provider_type=ProviderType.ANTHROPIC, api_key="k",
        model_map={"fast": "claude-haiku-4-5", "smart": "claude-opus-4-6"},
        active_models=["claude-haiku-4-5"],
    )
    mgr = ProviderPoolManager([cfg])
    mgr._providers = [RecordingProvider(cfg)]
    mgr._circuits = {"p1": CircuitBreaker("p1")}
    return mgr


class TestSetModelsEndpoint:
    @pytest.fixture
    def client_and_mgr(self):
        mgr = make_mgr_for_service()
        svc = AgentStateService(database_url="sqlite+aiosqlite:///:memory:", pool_manager=mgr)
        app = svc.create_app()
        client = TestClient(app, raise_server_exceptions=True)
        return client, mgr

    def test_set_models_updates_pool(self, client_and_mgr):
        client, mgr = client_and_mgr
        resp = client.patch(
            "/pool/providers/p1/models",
            json={"active_models": ["claude-haiku-4-5", "claude-opus-4-6"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_models"] == ["claude-haiku-4-5", "claude-opus-4-6"]
        assert mgr._model_pools["p1"] == ["claude-haiku-4-5", "claude-opus-4-6"]

    def test_set_models_unknown_provider_404(self, client_and_mgr):
        client, _ = client_and_mgr
        resp = client.patch(
            "/pool/providers/ghost/models",
            json={"active_models": ["m1"]},
        )
        assert resp.status_code == 404

    def test_set_models_no_pool_manager_503(self):
        svc = AgentStateService(database_url="sqlite+aiosqlite:///:memory:", pool_manager=None)
        app = svc.create_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.patch("/pool/providers/p1/models", json={"active_models": []})
        assert resp.status_code == 503

    def test_pool_status_includes_model_map_and_active_models(self, client_and_mgr):
        client, _ = client_and_mgr
        resp = client.get("/pool/status")
        assert resp.status_code == 200
        providers = resp.json()["providers"]
        p = next(x for x in providers if x["name"] == "p1")
        assert "model_map" in p
        assert "active_models" in p
        assert p["model_map"] == {"fast": "claude-haiku-4-5", "smart": "claude-opus-4-6"}
        assert p["active_models"] == ["claude-haiku-4-5"]
```

**Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_provider_model_pool.py::TestSetModelsEndpoint -v
```
Expected: 404 on the set_models endpoint (route doesn't exist yet)

**Step 3: Implement in `claw_forge/state/service.py`**

**3a.** Find the existing `ToggleProviderRequest` model near the top of the class or in the route registration. After it, add a new Pydantic model:

```python
class SetProviderModelsRequest(BaseModel):
    active_models: list[str]
```

**3b.** After the `persist_provider` endpoint (around line 769), add:

```python
        @app.patch("/pool/providers/{name}/models")
        async def set_provider_models(name: str, req: SetProviderModelsRequest) -> dict[str, Any]:
            """Update the active model pool for a provider at runtime."""
            pm = self._pool_manager
            if pm is None:
                raise HTTPException(503, "Pool manager not available")
            found = pm.set_provider_models(name, req.active_models)
            if not found:
                raise HTTPException(404, f"Provider {name!r} not found")
            status = await pm.get_pool_status()
            await self.ws_manager.broadcast_pool_update(status["providers"])
            return {"name": name, "active_models": req.active_models}
```

**3c.** In the idle (YAML fallback) path of `pool_status()` (around line 688), inside the `providers.append({...})` dict, add after `"model"`:

```python
                        "model_map": cfg.get("model_map", {}) or {},
                        "active_models": cfg.get("active_models", []) or [],
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_provider_model_pool.py -v
```
Expected: all pass

**Step 5: Full suite**

```bash
uv run pytest tests/ -q
```
Expected: pass (coverage ≥ 90%)

**Step 6: Commit**

```bash
git add claw_forge/state/service.py tests/test_provider_model_pool.py
git commit -m "feat: add PATCH /pool/providers/{name}/models endpoint and model_map in pool_status"
```

---

### Task 4: Frontend types and API

**Files:**
- Modify: `ui/src/types.ts`
- Modify: `ui/src/api.ts`

**Step 1: Add fields to `ProviderStatus` in `ui/src/types.ts`**

Find the `ProviderStatus` interface. After `model?: string;` add:

```typescript
/** Map of logical alias → model ID (from config model_map) */
model_map?: Record<string, string>;
/** List of currently active model IDs for round-robin pool */
active_models?: string[];
```

**Step 2: Add `setProviderModels` to `ui/src/api.ts`**

After the `persistProvider` function, add:

```typescript
/** Update the active model pool for a provider (round-robin pool). */
export async function setProviderModels(name: string, activeModels: string[]): Promise<void> {
  await fetchJSON<unknown>(`/pool/providers/${encodeURIComponent(name)}/models`, {
    method: "PATCH",
    body: JSON.stringify({ active_models: activeModels }),
  });
}
```

**Step 3: Build to verify no TypeScript errors**

```bash
npm --prefix ui run build 2>&1 | tail -20
```
Expected: build succeeds with no type errors

**Step 4: Commit**

```bash
git add ui/src/types.ts ui/src/api.ts
git commit -m "feat: add model_map/active_models to ProviderStatus type and setProviderModels API"
```

---

### Task 5: Provider row checkbox UI

**Files:**
- Modify: `ui/src/components/ProviderPoolStatus.tsx`

**Step 1: Plan the changes before writing**

`ProviderRow` needs:
1. `expanded: boolean` local state
2. A chevron button (only when `model_map` has ≥1 entry)
3. An accordion `<div>` with one checkbox row per `model_map` entry
4. Checkbox logic: checked = model ID is in `active_models`; clicking calls `setProviderModels` with the toggled list
5. Optimistic update: update local `provider.active_models` state immediately, revert on error

`ProviderPoolStatus` needs to pass model changes up through query cache patching (same pattern as provider enable/disable).

**Step 2: Add `onModelToggle` prop to `ProviderRowProps`**

In `ProviderPoolStatus.tsx`, extend `ProviderRowProps`:

```typescript
interface ProviderRowProps {
  provider: ProviderStatus;
  pendingPersist: boolean;
  toggling: boolean;
  onToggle: (name: string, enabled: boolean) => void;
  onToggleResult: (name: string, success: boolean, newEnabled: boolean) => void;
  onPersist: (name: string) => void;
  onToast: (msg: string, kind: ToastKind) => void;
  onModelToggle: (name: string, activeModels: string[]) => void;       // add
  onModelToggleResult: (name: string, success: boolean, activeModels: string[]) => void; // add
}
```

**Step 3: Implement the accordion in `ProviderRow`**

Add at top of `ProviderRow` function body:

```typescript
const [expanded, setExpanded] = useState(false);
const [togglingModel, setTogglingModel] = useState(false);

const modelMap = provider.model_map ?? {};
const modelMapEntries = Object.entries(modelMap); // [alias, modelId]
const activeModels = provider.active_models ?? [];
const hasModels = modelMapEntries.length > 0;

const handleModelCheck = useCallback(async (modelId: string, checked: boolean) => {
  if (togglingModel) return;
  const newActive = checked
    ? [...activeModels, modelId]
    : activeModels.filter((m) => m !== modelId);
  setTogglingModel(true);
  onModelToggle(provider.name, newActive);
  try {
    await setProviderModels(provider.name, newActive);
    onModelToggleResult(provider.name, true, newActive);
    onToast(`${provider.name}: model pool updated`, "success");
  } catch (err) {
    onModelToggle(provider.name, activeModels); // revert
    onModelToggleResult(provider.name, false, activeModels);
    onToast(`Model update failed: ${String(err)}`, "error");
  } finally {
    setTogglingModel(false);
  }
}, [provider.name, activeModels, togglingModel, onModelToggle, onModelToggleResult, onToast]);
```

Add the import at the top of the file:
```typescript
import { toggleProvider, persistProvider, setProviderModels } from "../api";
```

**Step 4: Add chevron button and accordion to the JSX**

In `ProviderRow`'s return, find the closing `</div>` of the outer `<div className="flex items-center gap-2 px-3 py-2">` row. Before it, add the chevron:

```tsx
{/* Expand chevron — only when model_map has entries */}
{hasModels && (
  <button
    type="button"
    onClick={() => setExpanded((v) => !v)}
    className="ml-auto p-0.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
    aria-label={expanded ? "Collapse models" : "Expand models"}
    title={expanded ? "Hide model pool" : "Show model pool"}
  >
    <span className="text-xs">{expanded ? "▲" : "▼"}</span>
  </button>
)}
```

After the summary row `</div>`, add the accordion:

```tsx
{/* Model pool accordion */}
{hasModels && expanded && (
  <div className="border-t border-slate-100 dark:border-slate-700 px-3 py-2 flex flex-col gap-1">
    {modelMapEntries.map(([alias, modelId]) => {
      const isActive = activeModels.includes(modelId);
      return (
        <label
          key={modelId}
          className="flex items-center gap-2 cursor-pointer group"
        >
          <input
            type="checkbox"
            checked={isActive}
            disabled={togglingModel}
            onChange={(e) => handleModelCheck(modelId, e.target.checked)}
            className="h-3 w-3 rounded border-slate-300 text-emerald-500 focus:ring-emerald-400
              disabled:opacity-60 disabled:cursor-not-allowed"
          />
          <span className="font-semibold text-slate-700 dark:text-slate-200 text-[11px] min-w-[48px]">
            {alias}
          </span>
          <span className="font-mono text-[10px] text-slate-400 dark:text-slate-500 truncate">
            {modelId}
          </span>
        </label>
      );
    })}
  </div>
)}
```

**Step 5: Wire up handlers in `ProviderPoolStatus`**

Add handler functions after `handlePersistSuccess`:

```typescript
const handleModelToggle = useCallback((name: string, activeModels: string[]) => {
  setProviders((prev) =>
    prev.map((p) => (p.name === name ? { ...p, active_models: activeModels } : p)),
  );
}, []);

const handleModelToggleResult = useCallback(
  (name: string, success: boolean, activeModels: string[]) => {
    if (success) {
      qc.setQueryData<PoolStatusResponse>(POOL_KEY, (old) => {
        if (!old) return old;
        return {
          ...old,
          providers: old.providers.map((p) =>
            p.name === name ? { ...p, active_models: activeModels } : p,
          ),
        };
      });
    }
  },
  [qc],
);
```

Pass them to each `ProviderRow`:

```tsx
<ProviderRow
  key={p.name}
  provider={p}
  pendingPersist={pendingPersist.has(p.name)}
  toggling={toggling.has(p.name)}
  onToggle={handleToggle}
  onToggleResult={handleToggleResult}
  onPersist={handlePersistSuccess}
  onToast={handleToast}
  onModelToggle={handleModelToggle}
  onModelToggleResult={handleModelToggleResult}
/>
```

**Step 6: Build**

```bash
npm --prefix ui run build 2>&1 | tail -20
```
Expected: build succeeds, no TypeScript errors

**Step 7: Commit**

```bash
git add ui/src/components/ProviderPoolStatus.tsx
git commit -m "feat: add expandable model pool checkboxes to provider panel"
```

---

### Task 6: Full validation

**Step 1: Run the full test suite**

```bash
uv run pytest tests/ -q --cov=claw_forge --cov-report=term-missing
```
Expected: pass, coverage ≥ 90%

**Step 2: Lint**

```bash
uv run ruff check claw_forge/ tests/
```
Expected: no errors

**Step 3: Type check**

```bash
uv run mypy claw_forge/ --ignore-missing-imports
```
Expected: no errors

**Step 4: Final commit if needed**

```bash
git add -p   # stage any remaining changes
git commit -m "chore: provider model pool — lint and type fixes"
```
