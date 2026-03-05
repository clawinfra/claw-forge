# Provider Model Pool Selection Design

**Date:** 2026-03-05 (revised)
**Status:** Approved

## Summary

Each provider row in the Kanban provider panel can be expanded to reveal its `model_map` entries as checkboxes. Checked models form an active pool for that provider. When a provider handles a request, the pool manager round-robins through its active models — overriding the caller-supplied model. This allows a single provider endpoint (e.g., one Anthropic API key) to cycle through haiku/sonnet/opus for load distribution or cost management.

## Core Concept

```
provider: anthropic-main
  model_map:
    haiku:  claude-haiku-4-5       ☑  (active)
    sonnet: claude-sonnet-4-6      ☑  (active)
    opus:   claude-opus-4-6        ☐  (inactive)

→ agents alternate: haiku → sonnet → haiku → sonnet → …
```

## Backend Changes

### 1. `ProviderConfig` (`claw_forge/pool/providers/base.py`)

Add field:
```python
active_models: list[str] = field(default_factory=list)
```

Semantics: if empty, the provider uses its `model` field (existing behavior). If non-empty, the pool manager round-robins through this list when routing requests to this provider.

### 2. `ProviderPoolManager` (`claw_forge/pool/manager.py`)

Add:
- `_model_pools: dict[str, list[str]]` — effective active model list per provider (initialized from `config.active_models`, falling back to `[config.model]` if set, else `[]`)
- `_model_rr: dict[str, int]` — round-robin index per provider (starts at 0)

New methods:
```python
def get_next_model(self, provider_name: str) -> str | None:
    """Return next active model for this provider in round-robin, or None if pool has ≤1 entry."""

def set_provider_models(self, name: str, active_models: list[str]) -> bool:
    """Update active model pool at runtime. Returns True if provider found."""
```

Modify `execute()`: when selecting a provider, if `get_next_model(provider.name)` returns a non-None value, pass that as `model=` to `provider.execute()` instead of the caller-supplied model.

Modify `get_pool_status()`: include `model_map` and `active_models` in each provider dict:
```python
{
    "name": "anthropic-main",
    "model": "claude-sonnet-4-6",      # current/last-used model
    "model_map": {"haiku": "...", "sonnet": "...", "opus": "..."},
    "active_models": ["claude-haiku-4-5", "claude-sonnet-4-6"],
    ...
}
```

### 3. State service (`claw_forge/state/service.py`)

**`GET /pool/status`** (idle YAML path): read `model_map` and `active_models` from config and include in each provider's response object.

**New endpoint** `PATCH /pool/providers/{name}/models`:
```
Body: { "active_models": ["claude-haiku-4-5", "claude-sonnet-4-6"] }
```
- Active run: calls `pm.set_provider_models(name, active_models)` → broadcasts pool update
- Idle: writes `active_models` list to `claw-forge.yaml` for that provider

**New request schema** `SetProviderModelsRequest`:
```python
class SetProviderModelsRequest(BaseModel):
    active_models: list[str]
```

### 4. YAML config (`load_configs_from_yaml`)

Read `active_models` list from YAML and pass to `ProviderConfig`. No migration needed — field defaults to empty list.

## Frontend Changes

### 1. `ui/src/types.ts`

Add to `ProviderStatus`:
```typescript
model_map?: Record<string, string>;   // key=alias, value=model ID
active_models?: string[];             // currently checked model IDs
```

### 2. `ui/src/api.ts`

Add:
```typescript
export async function setProviderModels(name: string, activeModels: string[]): Promise<void>
// PATCH /pool/providers/{name}/models  { active_models: activeModels }
```

### 3. `ui/src/components/ProviderPoolStatus.tsx`

**`ProviderRow`** changes:
- Local `expanded: boolean` state
- Chevron button shown only when `model_map` has ≥ 1 entry
- Accordion section below the summary line with checkboxes:
  - One checkbox per `model_map` entry (label = alias key, subtitle = model ID)
  - A checkbox for the base `model` if it's not already a model_map value
  - Checked = model ID is in `active_models`
  - Checking/unchecking → optimistic update → `setProviderModels(name, newActiveList)` → revert on error → toast

**Layout:**
```
[toggle] anthropic-main  [anthropic]  claude-haiku-4-5  🟢 OK  [$0.12]  [▼]
──────────────────────────────────────────────────────────────────────────
  ☑ haiku   claude-haiku-4-5
  ☑ sonnet  claude-sonnet-4-6
  ☐ opus    claude-opus-4-6
```

Query cache is patched after a successful `setProviderModels` call so the optimistic update survives the next poll (same pattern as the provider enable/disable toggle).

## Data Flow

1. `GET /pool/status` → `model_map` + `active_models` in each provider object
2. User expands a provider row (chevron) → checkboxes render
3. User checks/unchecks a model → optimistic update in local state
4. `PATCH /pool/providers/{name}/models` fires with full updated `active_models` list
5. Pool manager updates `_model_pools[name]` and resets the RR index for that provider
6. On success: toast + query cache patch; on failure: rollback + toast error
7. Next `execute()` call for that provider round-robins through the new active model list

## What is NOT in scope

- Persisting model selection to YAML via the existing "Persist" button (handled automatically since idle PATCH writes to YAML)
- Dynamic model discovery from provider APIs
- Per-model health metrics or cost tracking (tracked at provider level only)
- Changes to `model_aliases` (separate section, unchanged)
