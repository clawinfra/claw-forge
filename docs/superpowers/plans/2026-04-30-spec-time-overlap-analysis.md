# Spec-Time Overlap Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Phase 3.5 to `/create-spec` so feature bullets that touch the same code surface can be serialized via `depends_on` edges in the emitted XML, and surface those edges through the parser into the runtime task DAG.

**Architecture:** Extend the existing `<feature>` element to accept `index` and `depends_on` attributes; the parser already constructs `FeatureItem.depends_on_indices` (currently populated by phase order); we add attribute-level overrides. At load time, the `index → task_id` mapping is built from the feature emission order, then `FeatureItem.depends_on_indices` (1-based) is translated into `TaskNode.depends_on` (string IDs) for the existing scheduler. The `/create-spec` command grows a Phase 3.5 step that runs an LLM overlap analysis and asks the user to resolve flagged pairs.

**Tech Stack:** Python 3.12, ElementTree (existing), Typer (existing), pytest, ruff, mypy.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `claw_forge/spec/parser.py` | Modify (lines 169-191) | Read `index` and `depends_on` attributes off `<feature>` |
| `tests/spec/test_parser.py` | Modify | Add tests for new attribute parsing + legacy coexistence |
| `claw_forge/cli.py` | Modify (around the `plan` command) | Translate feature-index edges to TaskNode-id edges at load time |
| `tests/test_cli_commands.py` | Modify | Test for the index→task_id translation |
| `.claude/commands/create-spec.md` | Modify | Insert "Phase 3.5 — Overlap Analysis" between Phase 3 and Phase 4 |

---

## Task 1: Parser reads `index` attribute on `<feature>`

**Files:**
- Modify: `claw_forge/spec/parser.py` (lines 169-191)
- Test: `tests/spec/test_parser.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/spec/test_parser.py`:

```python
def test_feature_element_index_attribute_populates_index_field(tmp_path: Path) -> None:
    """A <feature index="14"> attribute is preserved on FeatureItem."""
    spec_xml = """<?xml version="1.0"?>
<project_specification>
  <project_name>Test</project_name>
  <core_features>
    <category name="X">
      <feature index="14">
        <description>User can register</description>
      </feature>
    </category>
  </core_features>
</project_specification>"""
    spec_path = tmp_path / "spec.xml"
    spec_path.write_text(spec_xml)
    spec = ProjectSpec.from_file(spec_path)
    assert len(spec.features) == 1
    assert spec.features[0].index == 14
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/spec/test_parser.py::test_feature_element_index_attribute_populates_index_field -v
```

Expected: FAIL with `AttributeError: 'FeatureItem' object has no attribute 'index'`.

- [ ] **Step 3: Add `index` field to `FeatureItem`**

Edit `claw_forge/spec/parser.py` near the existing `FeatureItem` dataclass:

```python
@dataclass
class FeatureItem:
    category: str
    name: str
    description: str
    steps: list[str] = field(default_factory=list)
    depends_on_indices: list[int] = field(default_factory=list)
    index: int | None = None  # 1-based feature number when declared on <feature index="N">
```

- [ ] **Step 4: Read `index` attribute in `_parse_xml`**

In `claw_forge/spec/parser.py` lines 169-191, change the `<feature>` parsing block to read the attribute:

```python
for feat_el in feature_els:
    desc = (feat_el.findtext("description") or "").strip()
    if not desc:
        continue
    short_name = desc[:60].rstrip(".,:;")
    feat_steps: list[str] = []
    steps_el = feat_el.find("steps")
    if steps_el is not None:
        for line in (steps_el.text or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("- ") or stripped.startswith("* "):
                feat_steps.append(stripped[2:].strip())
    # NEW: read index attribute (1-based; absent = None)
    index_attr = feat_el.get("index", "").strip()
    feat_index = int(index_attr) if index_attr.isdigit() else None
    features.append(
        FeatureItem(
            category=category,
            name=short_name,
            description=desc,
            steps=feat_steps,
            index=feat_index,
        )
    )
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/spec/test_parser.py::test_feature_element_index_attribute_populates_index_field -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add claw_forge/spec/parser.py tests/spec/test_parser.py
git commit -m "feat(spec): parse <feature index=N> attribute"
```

---

## Task 2: Parser reads `depends_on` attribute on `<feature>`

**Files:**
- Modify: `claw_forge/spec/parser.py` (same block as Task 1)
- Test: `tests/spec/test_parser.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/spec/test_parser.py`:

```python
def test_feature_element_depends_on_attribute_populates_indices(tmp_path: Path) -> None:
    """A <feature depends_on="10,12"> attribute is parsed into depends_on_indices."""
    spec_xml = """<?xml version="1.0"?>
<project_specification>
  <project_name>Test</project_name>
  <core_features>
    <category name="X">
      <feature index="10"><description>First</description></feature>
      <feature index="12"><description>Second</description></feature>
      <feature index="14" depends_on="10,12">
        <description>Third depends on both</description>
      </feature>
    </category>
  </core_features>
</project_specification>"""
    spec_path = tmp_path / "spec.xml"
    spec_path.write_text(spec_xml)
    spec = ProjectSpec.from_file(spec_path)
    assert len(spec.features) == 3
    assert spec.features[2].depends_on_indices == [10, 12]
    # Earlier features have no edges from this attribute
    assert spec.features[0].depends_on_indices == []
    assert spec.features[1].depends_on_indices == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/spec/test_parser.py::test_feature_element_depends_on_attribute_populates_indices -v
```

Expected: FAIL — `depends_on_indices` will be `[]` for the third feature (current code only populates from phases).

- [ ] **Step 3: Read `depends_on` attribute and populate indices**

In `claw_forge/spec/parser.py`, in the same `<feature>` parsing block, add the attribute read alongside `index_attr`:

```python
index_attr = feat_el.get("index", "").strip()
feat_index = int(index_attr) if index_attr.isdigit() else None
# NEW: read depends_on attribute, comma-separated 1-based indices
depends_attr = feat_el.get("depends_on", "").strip()
explicit_deps: list[int] = []
if depends_attr:
    for part in depends_attr.split(","):
        part = part.strip()
        if part.isdigit():
            explicit_deps.append(int(part))
features.append(
    FeatureItem(
        category=category,
        name=short_name,
        description=desc,
        steps=feat_steps,
        index=feat_index,
        depends_on_indices=explicit_deps,
    )
)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/spec/test_parser.py::test_feature_element_depends_on_attribute_populates_indices -v
```

Expected: PASS.

- [ ] **Step 5: Run full parser tests for no regression**

```bash
uv run pytest tests/spec/test_parser.py -v
```

Expected: all tests pass (legacy `<feature>` and bullet-format tests still green).

- [ ] **Step 6: Commit**

```bash
git add claw_forge/spec/parser.py tests/spec/test_parser.py
git commit -m "feat(spec): parse <feature depends_on=...> attribute into depends_on_indices"
```

---

## Task 3: Phase-derived dependencies merge with explicit `depends_on`

**Files:**
- Modify: `claw_forge/spec/parser.py` (around line 239 where phase-based edges are computed)
- Test: `tests/spec/test_parser.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/spec/test_parser.py`:

```python
def test_explicit_depends_on_preserved_over_phase_inference(tmp_path: Path) -> None:
    """Explicit depends_on attributes are preserved; phase-based inference
    only adds edges for features that didn't declare any explicitly.
    """
    spec_xml = """<?xml version="1.0"?>
<project_specification>
  <project_name>Test</project_name>
  <core_features>
    <category name="X">
      <feature index="1"><description>A</description></feature>
      <feature index="2" depends_on="1"><description>B explicit</description></feature>
      <feature index="3"><description>C inferred</description></feature>
    </category>
  </core_features>
  <implementation_steps>
    <phase name="P1">A</phase>
    <phase name="P2">B explicit</phase>
    <phase name="P3">C inferred</phase>
  </implementation_steps>
</project_specification>"""
    spec_path = tmp_path / "spec.xml"
    spec_path.write_text(spec_xml)
    spec = ProjectSpec.from_file(spec_path)
    # B has explicit depends_on=1 — preserved unchanged.
    assert spec.features[1].depends_on_indices == [1]
    # C has no explicit edge — phase inference may add one.
    assert spec.features[0].depends_on_indices == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/spec/test_parser.py::test_explicit_depends_on_preserved_over_phase_inference -v
```

Expected: FAIL because the existing phase-inference code at line 239+ overwrites `depends_on_indices` for all features. (Read the current code at lines 239-end of `_parse_xml` to confirm the overwrite behavior before fixing.)

- [ ] **Step 3: Modify phase-inference to skip features with explicit edges**

Open `claw_forge/spec/parser.py` and locate the block starting `# Assign depends_on_indices based on implementation_steps order` (~line 239). Wrap the assignment so it only fires when the feature has no explicit edges:

```python
# Inside the loop that assigns phase-based edges to each feature:
for feat in features:
    if feat.depends_on_indices:
        # Explicit depends_on attribute already populated — preserve it.
        continue
    # ... existing phase-based logic populates feat.depends_on_indices ...
```

The exact placement is in the loop that reads `phases` and assigns to `feature.depends_on_indices`. Read lines 239-end carefully and add the early-`continue`.

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/spec/test_parser.py::test_explicit_depends_on_preserved_over_phase_inference -v
```

Expected: PASS.

- [ ] **Step 5: Run full parser tests for no regression**

```bash
uv run pytest tests/spec/test_parser.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add claw_forge/spec/parser.py tests/spec/test_parser.py
git commit -m "feat(spec): explicit depends_on overrides phase-based inference"
```

---

## Task 4: Legacy bullet format coexists with new `<feature>` element

**Files:**
- Test: `tests/spec/test_parser.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/spec/test_parser.py`:

```python
def test_mixed_legacy_bullets_and_feature_elements_in_same_category(tmp_path: Path) -> None:
    """A category may contain a mix of legacy ``- bullet`` lines and new
    <feature> elements; both produce FeatureItems."""
    spec_xml = """<?xml version="1.0"?>
<project_specification>
  <project_name>Test</project_name>
  <core_features>
    <category name="Mixed">
      - Legacy bullet one
      - Legacy bullet two
      <feature index="3" depends_on="1"><description>New element</description></feature>
    </category>
  </core_features>
</project_specification>"""
    spec_path = tmp_path / "spec.xml"
    spec_path.write_text(spec_xml)
    spec = ProjectSpec.from_file(spec_path)
    descriptions = [f.description for f in spec.features]
    assert "Legacy bullet one" in descriptions
    assert "Legacy bullet two" in descriptions
    assert "New element" in descriptions
```

- [ ] **Step 2: Run test to verify it fails or passes**

```bash
uv run pytest tests/spec/test_parser.py::test_mixed_legacy_bullets_and_feature_elements_in_same_category -v
```

Expected: this likely FAILS today because the existing parser at lines 169-208 takes an either/or branch (`if feature_els: ... else: ...`) — it handles `<feature>` elements OR bullets, never both within the same `<category>`.

- [ ] **Step 3: Update parser to handle mixed format**

In `claw_forge/spec/parser.py` lines 169-208, change the structure so both paths run:

```python
feature_els = category_el.findall("feature")
# Always parse <feature> elements if any are present
for feat_el in feature_els:
    # ... (existing block from Tasks 1+2: index, depends_on, description, steps)
# Always parse legacy bullets from category text (independent of <feature> presence)
text = category_el.text or ""
for line in text.splitlines():
    stripped = line.strip()
    if stripped.startswith("- ") or stripped.startswith("* "):
        bullet = stripped[2:].strip()
        if bullet:
            short_name = bullet[:60].rstrip(".,:;")
            features.append(
                FeatureItem(
                    category=category,
                    name=short_name,
                    description=bullet,
                )
            )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/spec/test_parser.py::test_mixed_legacy_bullets_and_feature_elements_in_same_category -v
```

Expected: PASS.

- [ ] **Step 5: Run full parser tests**

```bash
uv run pytest tests/spec/ -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add claw_forge/spec/parser.py tests/spec/test_parser.py
git commit -m "feat(spec): allow mixed legacy bullets + <feature> elements per category"
```

---

## Task 5: Index → task_id mapping at load time

**Files:**
- Modify: `claw_forge/cli.py` (the `plan` command — find via `grep -n 'def plan' claw_forge/cli.py`)
- Test: `tests/test_cli_commands.py` (or new file `tests/test_plan_dependencies.py`)

This task wires the parsed `FeatureItem.depends_on_indices` (1-based feature numbers) onto `TaskNode.depends_on` (string IDs) when the spec is loaded into the state service.

- [ ] **Step 1: Locate the load-time conversion**

Run:

```bash
/usr/bin/grep -n "FeatureItem\|features\[" claw_forge/cli.py | head -20
/usr/bin/grep -n "task_id\|TaskNode\|/sessions/init" claw_forge/cli.py | head -20
```

Identify the function (likely `plan` or a helper inside `cli.py`) that converts `spec.features` into HTTP POSTs to the state service for task creation. That's where the index→id mapping is built.

- [ ] **Step 2: Write the failing test**

Create `tests/test_plan_dependencies.py`:

```python
"""Test that explicit depends_on edges in spec features become TaskNode.depends_on."""
from __future__ import annotations

from pathlib import Path

import pytest

from claw_forge.spec.parser import FeatureItem, ProjectSpec, TechStack


@pytest.fixture()
def spec_with_explicit_edges(tmp_path: Path) -> Path:
    spec_xml = """<?xml version="1.0"?>
<project_specification>
  <project_name>Test</project_name>
  <core_features>
    <category name="X">
      <feature index="1"><description>A</description></feature>
      <feature index="2" depends_on="1"><description>B</description></feature>
    </category>
  </core_features>
</project_specification>"""
    spec_path = tmp_path / "spec.xml"
    spec_path.write_text(spec_xml)
    return spec_path


def test_features_with_explicit_index_edges_load_as_taskdependencies(
    spec_with_explicit_edges: Path,
) -> None:
    """When a <feature index='2' depends_on='1'> is loaded, the resulting
    task for feature 2 must list feature 1's task_id in its depends_on.
    """
    from claw_forge.cli import _features_to_task_payload  # to be created

    spec = ProjectSpec.from_file(spec_with_explicit_edges)
    payloads = _features_to_task_payload(spec.features)
    assert len(payloads) == 2
    # Each payload has an "id" and "depends_on" list
    a_id = payloads[0]["id"]
    b_deps = payloads[1]["depends_on"]
    assert b_deps == [a_id], (
        f"Expected feature 2 to depend on feature 1's id; got {b_deps!r}"
    )
```

- [ ] **Step 3: Run test to verify it fails**

```bash
uv run pytest tests/test_plan_dependencies.py -v
```

Expected: FAIL with `ImportError` or `AttributeError: '_features_to_task_payload'`.

- [ ] **Step 4: Implement `_features_to_task_payload` in `cli.py`**

Add this helper near the `plan` command in `claw_forge/cli.py`:

```python
def _features_to_task_payload(features: list[FeatureItem]) -> list[dict[str, Any]]:
    """Convert parsed FeatureItems into task-creation payloads with stable ids
    and resolved depends_on edges.

    Each FeatureItem with a populated ``index`` becomes a task with id
    ``"feat-<index>"``.  ``depends_on_indices`` (1-based) are translated
    into the matching ``feat-<index>`` ids.  Features without an index
    (legacy bullets) get ids derived from their list position.
    """
    payloads: list[dict[str, Any]] = []
    # Build index → id map first
    id_for_index: dict[int, str] = {}
    for pos, feat in enumerate(features):
        if feat.index is not None:
            id_for_index[feat.index] = f"feat-{feat.index}"
        else:
            # Legacy bullet; assign a positional id
            id_for_index_pos = f"feat-pos-{pos}"
            id_for_index[-(pos + 1)] = id_for_index_pos  # negative key avoids collision
    for pos, feat in enumerate(features):
        feat_id = (
            f"feat-{feat.index}" if feat.index is not None else f"feat-pos-{pos}"
        )
        deps: list[str] = []
        for dep_idx in feat.depends_on_indices:
            if dep_idx in id_for_index:
                deps.append(id_for_index[dep_idx])
        payloads.append({
            "id": feat_id,
            "category": feat.category,
            "description": feat.description,
            "depends_on": deps,
        })
    return payloads
```

(The actual `plan` command logic that posts to the state service should call this helper; that wiring is the next step.)

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/test_plan_dependencies.py -v
```

Expected: PASS.

- [ ] **Step 6: Wire `_features_to_task_payload` into the `plan` command**

In the `plan` command body (location identified in Step 1), replace the existing per-feature task-creation loop with a single call to `_features_to_task_payload(spec.features)` and post each resulting payload to `/sessions/{id}/tasks`. The existing field set may differ from the helper's output — adapt the helper or the call site so all required state-service fields are present (the helper's output adds `id` and `depends_on`; the existing call site already sets `category`, `description`, etc.).

- [ ] **Step 7: Run full cli tests for no regression**

```bash
uv run pytest tests/test_cli_commands.py tests/test_plan_dependencies.py -v
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add claw_forge/cli.py tests/test_plan_dependencies.py
git commit -m "feat(cli): translate feature-index edges to TaskNode dependencies"
```

---

## Task 6: End-to-end DAG ordering for explicit edges

**Files:**
- Test: `tests/test_plan_dependencies.py` (extend)

- [ ] **Step 1: Write the integration test**

Append to `tests/test_plan_dependencies.py`:

```python
def test_scheduler_places_dependent_feature_in_later_wave(
    spec_with_explicit_edges: Path,
) -> None:
    """Loading a spec with explicit depends_on into the Scheduler produces
    a 2-wave execution order: independent feature in wave 1, dependent in
    wave 2.
    """
    from claw_forge.cli import _features_to_task_payload
    from claw_forge.spec.parser import ProjectSpec
    from claw_forge.state.scheduler import Scheduler, TaskNode

    spec = ProjectSpec.from_file(spec_with_explicit_edges)
    payloads = _features_to_task_payload(spec.features)
    scheduler = Scheduler()
    for p in payloads:
        scheduler.add_task(
            TaskNode(
                id=p["id"],
                plugin_name="coding",
                priority=0,
                depends_on=p["depends_on"],
                description=p["description"],
            )
        )
    waves = scheduler.get_execution_order()
    assert len(waves) == 2, f"expected 2 waves, got {len(waves)}: {waves}"
    assert waves[0] == ["feat-1"]
    assert waves[1] == ["feat-2"]
```

- [ ] **Step 2: Run test to verify it passes**

```bash
uv run pytest tests/test_plan_dependencies.py::test_scheduler_places_dependent_feature_in_later_wave -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_plan_dependencies.py
git commit -m "test(spec): end-to-end DAG ordering for explicit depends_on edges"
```

---

## Task 7: Add Phase 3.5 to `/create-spec`

**Files:**
- Modify: `.claude/commands/create-spec.md` (insert between current "Phase 3" and "Phase 4")

- [ ] **Step 1: Read the current Phase 3 / Phase 4 boundary**

```bash
/usr/bin/grep -n "^### Phase " .claude/commands/create-spec.md
```

Identify the line where Phase 3 ends and Phase 4 begins.

- [ ] **Step 2: Insert Phase 3.5 section**

Edit `.claude/commands/create-spec.md` and insert the following block immediately before the "### Phase 4" heading:

```markdown
---

### Phase 3.5: Overlap Analysis

After confirming the feature list with the user, analyze pairs that will modify the same logical code surface. Run this analysis as one inline LLM step (you, executing this command).

**Step 1 — Run the analysis prompt** on the bullet list:

> You are auditing a feature spec for merge-conflict risk. Below are N feature
> bullets, each numbered. Find pairs where implementing both would force
> conflicting edits to the same file or function — i.e. they would both modify
> the same hunks if scheduled in parallel.
>
> A pair is overlapping ONLY if changing one without the other would force a
> merge conflict. Same category alone is not overlap.
>
> Return JSON only:
> ```json
> [{"a": <int>, "b": <int>, "surface": "<file_or_concept>", "rationale": "<one sentence>"}]
> ```
> Empty list `[]` if no overlaps. No prose outside the JSON.

**Step 2 — Resolve each overlap interactively** with the user:

For every entry returned, present:

```
Overlap detected:
  #<a>  <description of feature a>
  #<b>  <description of feature b>
  Shared surface: <surface>
  Rationale: <rationale>

Resolution? [s] serialize (#<b> depends on #<a>)  [k] keep parallel  [q] quit
```

- `s` → record an explicit edge: feature `<b>` will be emitted with `depends_on="<a>"`
- `k` → record the user's decision to keep parallel; do not flag this pair again on retry
- `q` → abort `/create-spec`; do not write any files

**Step 3 — Persist resolutions** in memory until Phase 5 emission. When Phase 5
generates the XML, each `<feature>` tagged with `s` decisions includes:

```xml
<feature index="<n>" depends_on="<comma-separated indices>">
  <description>...</description>
</feature>
```

If there are no overlaps (`[]`), skip directly to Phase 4 with one line:
"No overlap risk detected — features can run in parallel."

**Failure modes:**
- LLM returns malformed JSON → re-prompt once with the schema; if still bad,
  skip the analysis with a one-line warning ("could not analyze overlaps;
  emitting spec without explicit edges") and continue to Phase 4.
- Empty feature list (Phase 3 produced 0 bullets) → skip Phase 3.5; downstream
  validation handles the empty-spec case.

---
```

- [ ] **Step 3: Verify markdown still renders cleanly**

```bash
/usr/bin/grep -nE "^### Phase " .claude/commands/create-spec.md
```

Expected: phases now include `### Phase 3.5: Overlap Analysis` between Phase 3 and Phase 4.

- [ ] **Step 4: Commit**

```bash
git add .claude/commands/create-spec.md
git commit -m "feat(create-spec): add Phase 3.5 overlap analysis with depends_on edges"
```

---

## Task 8: Lint, type-check, and full suite

- [ ] **Step 1: Lint**

```bash
uv run ruff check claw_forge/ tests/
```

Expected: All checks passed!

- [ ] **Step 2: Type check**

```bash
uv run mypy claw_forge/ --ignore-missing-imports
```

Expected: Success: no issues found.

- [ ] **Step 3: Full test suite with coverage**

```bash
uv run pytest tests/ -q --cov=claw_forge --cov-report=term
```

Expected: all tests pass, coverage ≥ 90%.

- [ ] **Step 4: Verify the new tests are included**

```bash
uv run pytest tests/spec/test_parser.py tests/test_plan_dependencies.py -v --tb=short
```

Expected: all green; new tests visible in output.

- [ ] **Step 5: No commit needed if all clean**

If lint/types/tests are clean and no new files were created in this task, no commit needed. Otherwise commit.

---

## Self-Review

**Spec coverage:**
- ✅ Parser reads `<feature index>` and `<feature depends_on>` (Tasks 1, 2)
- ✅ Explicit edges preserved over phase-inference (Task 3)
- ✅ Mixed legacy + new format coexists (Task 4)
- ✅ Index → task_id mapping at load time (Task 5)
- ✅ End-to-end DAG ordering verified (Task 6)
- ✅ Phase 3.5 added to `/create-spec` (Task 7)
- ✅ Lint / types / suite (Task 8)
- ⚠ Out of scope per spec: auto-merge of features (correctly excluded)

**Placeholder scan:** none — every step has the actual code or command.

**Type consistency:** `index: int | None` and `depends_on_indices: list[int]` consistent across parser, helper, and tests. `_features_to_task_payload` returns `list[dict[str, Any]]` matching the existing state-service POST shape.

**Notes for the implementer:**
- Task 5 step 1 does code archaeology — the exact location of the index→id wiring depends on the current `plan` command structure. The helper `_features_to_task_payload` is intentionally pure so it can be unit-tested without reaching into HTTP/state-service code.
- Task 7 modifies a markdown command file — Claude itself executes that file as `/create-spec`. No test harness; verification is manual ("`/create-spec`, watch Phase 3.5 fire on a 5-bullet sample").
