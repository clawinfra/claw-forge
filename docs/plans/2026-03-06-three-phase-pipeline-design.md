# Three-Phase Per-Feature Pipeline Design

**Date:** 2026-03-06
**Status:** Approved

## Problem

Every feature task is currently created with `plugin_name="coding"` only. Testing and
code review are collapsed into the coding agent's internal execution, invisible on the
Kanban board. Users cannot see whether a feature has been tested or reviewed.

## Goal

Generate three chained tasks per feature — `coding → testing → reviewer` — so each
phase is a distinct card on the Kanban board. The scheduler's existing `depends_on`
mechanism blocks downstream phases when an upstream phase fails or is blocked.

## Scope

- **In scope:** task generation in `cli.py` (`_plan_project` / bulk task creation path)
- **Out of scope:** the `RegressionHealthBar` / `_project_path` bug (separate issue)

## Approach

For each feature coming out of the spec parser:

| Category | Phases created |
|---|---|
| `docs`, `infra` | `coding` only (no testable artifact) |
| all others | `coding` → `testing` → `reviewer` |

### Task naming

```
coding:   "<feature name>"               e.g. "Create User model"
testing:  "Test: <feature name>"         e.g. "Test: Create User model"
reviewer: "Review: <feature name>"       e.g. "Review: Create User model"
```

### Dependency wiring

`index_to_uuid` must map `feature_index → terminal_task_id` (the last phase for that
feature). Cross-feature `depends_on` edges attach to the terminal task so that, for
example, coding on Feature B cannot start until Feature A has been reviewed.

```
Feature A (backend):          Feature B (backend, depends_on=[A]):
  coding_A  (no deps)           coding_B  → depends_on [reviewer_A]
  testing_A → depends_on [coding_A]         testing_B → depends_on [coding_B]
  reviewer_A→ depends_on [testing_A]        reviewer_B→ depends_on [testing_B]

Feature C (docs):             Feature D (backend, depends_on=[C]):
  coding_C  (no deps)           coding_D  → depends_on [coding_C]  ← terminal is coding
  (no testing/reviewer)         testing_D → depends_on [coding_D]
                                reviewer_D→ depends_on [testing_D]
```

### Failure / blocked propagation

Uses existing scheduler behaviour — no new logic required:
- `coding` fails → `testing` and `reviewer` become `blocked`
- `coding` blocked (its deps failed) → `testing` and `reviewer` stay `pending` until
  the scheduler can evaluate them, then become `blocked`

## Implementation Plan

### 1. `claw_forge/cli.py` — bulk task creation

Replace the single-task loop with a three-task generator:

```python
NON_CODING_CATEGORIES = {"docs", "infra"}

for feat in features:
    is_coding_only = feat.get("category", "").lower() in NON_CODING_CATEGORIES

    coding_tid   = str(uuid.uuid4())
    testing_tid  = str(uuid.uuid4()) if not is_coding_only else None
    reviewer_tid = str(uuid.uuid4()) if not is_coding_only else None

    # terminal task for cross-feature dep wiring
    terminal_tid = reviewer_tid if reviewer_tid else coding_tid
    index_to_uuid[feat["index"]] = terminal_tid
    ...
```

Create up to three `Task` objects per feature, wiring:
- `coding`:   `depends_on = [cross-feature deps resolved via index_to_uuid]`
- `testing`:  `depends_on = [coding_tid]`
- `reviewer`: `depends_on = [testing_tid]`

### 2. Tests

- Unit test: verify three tasks created for backend/frontend/security/testing categories
- Unit test: verify only one task created for docs/infra categories
- Unit test: verify `depends_on` chain is correct across features
- Unit test: terminal task of upstream feature is in `depends_on` of downstream coding task

## Trade-offs Considered

| Option | Decision |
|---|---|
| Apply to all categories | Rejected — docs/infra don't produce testable code |
| Add `--phases` CLI flag | Rejected — YAGNI |
| Cancel downstream on failure | Rejected — use existing blocked behaviour |
