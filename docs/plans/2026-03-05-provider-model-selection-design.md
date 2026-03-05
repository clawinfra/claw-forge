# Provider Model Selection Design

**Date:** 2026-03-05
**Status:** Approved

## Summary

Add per-provider model selection to the Kanban UI provider panel. Each provider row gains a collapsible accordion that shows its `model_map` entries as radio buttons. Clicking a radio switches the provider's active model at runtime via the existing `PATCH /pool/providers/{name}` endpoint (extended to accept a `model` field).

## Scope

- No new UI panels or modals — the expansion happens inline within the existing `ProviderRow` component.
- Only providers with a non-empty `model_map` show the expand chevron.
- Model switching is runtime-only unless an active run is not present, in which case the PATCH endpoint already writes to YAML.

## Backend Changes

### 1. `GET /pool/status` response

Add `model_map` to each provider object in both the live (pool manager) and idle (YAML fallback) paths:

```json
{
  "name": "anthropic-main",
  "type": "anthropic",
  "model": "claude-sonnet-4-6",
  "model_map": {
    "fast": "claude-haiku-4-5",
    "smart": "claude-opus-4-6"
  },
  ...
}
```

**Files:** `claw_forge/state/service.py` (both branches of `pool_status()`), `claw_forge/pool/manager.py` (`get_pool_status()`)

### 2. `PATCH /pool/providers/{name}` — model field

Extend `ToggleProviderRequest` (or create `PatchProviderRequest`) to accept an optional `model: str | None`. When `model` is set, update the provider's active model at runtime via a new `set_provider_model(name, model)` method on `PoolManager`.

```json
PATCH /pool/providers/anthropic-main
{ "model": "claude-opus-4-6" }
```

**Files:** `claw_forge/state/service.py`, `claw_forge/pool/manager.py`

## Frontend Changes

### 1. `ui/src/types.ts`

Add `model_map?: Record<string, string>` to `ProviderStatus`.

### 2. `ui/src/api.ts`

Add `setProviderModel(name: string, model: string): Promise<void>` calling `PATCH /pool/providers/{name}` with `{ model }`.

### 3. `ui/src/components/ProviderPoolStatus.tsx`

**`ProviderRow`** gains:
- Local `expanded: boolean` state, toggled by a chevron button (only rendered if `model_map` is non-empty)
- An accordion section below the summary line listing:
  - The provider's current `model` value as an active radio entry
  - Each `model_map` value as a selectable radio entry (label = map key, value = resolved model ID)
- Selecting a radio fires `setProviderModel`, with optimistic update + rollback on error
- Toast on success/error (reuses existing `onToast` prop)

**Layout sketch:**
```
[toggle] provider-name  [type-badge]  claude-sonnet-4-6  🟢 OK  [$0.00]  [▼]
  ──────────────────────────────────────────────────────────────────
  ● claude-sonnet-4-6          (active)
  ○ fast   →  claude-haiku-4-5
  ○ smart  →  claude-opus-4-6
```

## Data Flow

1. UI mounts → `usePoolStatus` polls `GET /pool/status` → `model_map` included in response
2. User clicks chevron → row expands, shows radio list
3. User clicks a different radio → optimistic model update in local state → `setProviderModel` PATCH call
4. On success → toast; query cache patched so next poll doesn't revert
5. On failure → rollback local state + toast error

## What is NOT in scope

- Persisting model selection to YAML (the existing `persist` button flow is separate)
- Discovering models dynamically from provider APIs (Ollama `/api/tags`, etc.)
- Changing `model_aliases` entries
