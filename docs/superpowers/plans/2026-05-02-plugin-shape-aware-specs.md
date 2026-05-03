# Plugin-Shape-Aware Spec Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `claw-forge run` safe at high concurrency (≥10 agents) by encoding **architectural shape** in the spec — every feature declares whether it's a plugin (vertical, lives in its own directory) or core (horizontal, cross-cutting). The dispatcher reads the shape, auto-derives non-overlapping `touches_files` for plugins, and serializes `shape="core"` tasks single-flight. File-claim conflicts become impossible by construction for plugin features; cross-cutting features serialize honestly.

**Architecture:** Four independently shippable phases that compose:

1. **Phase 1 — Spec parser extension.** Add `shape`, `plugin`, and explicit `touches_files` attributes to the `<feature>` element. Auto-derive `touches_files` from `plugin=`. Persists through `_write_plan_to_db` to the state DB.
2. **Phase 2 — `/create-spec` Phase 3.25 (Architectural Shape).** Greenfield: classify each confirmed feature as plugin or core. Emit the new attributes in Phase 5.
3. **Phase 3 — Scheduler shape-awareness.** `TaskNode` carries `shape` + `plugin`. Dispatcher's ready-task selection respects `shape="core"` single-flight and groups tasks by plugin for predictable parallelism.
4. **Phase 4 — Brownfield integration with `boundaries_report.md`.** Brownfield `/create-spec` detects existing hotspots and suggests `claw-forge boundaries apply` before generating the spec; once hotspots are refactored, new features can land as plugins.

Each phase produces a working, testable, releasable artifact on its own. Phase 1 is foundational — Phases 2/3/4 depend on it but are independent of each other.

**Tech Stack:** Python 3.11+, `xml.etree.ElementTree`, dataclasses, `asyncio`, `pytest` with `tmp_path` fixtures, FastAPI/SQLAlchemy for state-service additions. No new external dependencies.

**Single-agent invariant proven:** Plugin-shape features have file-disjoint `touches_files` by construction; the file-claim lock never rejects two same-plugin tasks running in parallel because they're in the same plugin (intra-plugin tasks serialize via `depends_on`). Cross-plugin tasks can't share files (they live in different directories), so locks always succeed. Core tasks single-flight via the scheduler. Conflicts are reduced to "user declared two core features that both edit the same file" — caught at spec-validation time, not runtime.

---

## File Structure

| File | Role | Action |
|---|---|---|
| `claw_forge/spec/parser.py` | XML/text spec → ProjectSpec | Modify — extend `FeatureItem` + `<feature>` parser |
| `claw_forge/state/scheduler.py` | DAG scheduling | Modify — extend `TaskNode` with `shape` + `plugin` |
| `claw_forge/state/models.py` | SQLAlchemy ORM | Modify — add `shape`, `plugin` columns to `Task` |
| `claw_forge/state/service.py` | REST API | Modify — accept `shape`/`plugin` in `CreateTaskRequest`, expose in summaries, schema migration |
| `claw_forge/cli.py` | Dispatcher + plan→DB writer | Modify — write `shape`/`plugin` in `_write_plan_to_db`, propagate to TaskNode, add scheduler hook |
| `.claude/commands/create-spec.md` | Slash-command flow | Modify — insert Phase 3.25, update Phase 5 emit, update brownfield Step 2 |
| `skills/app_spec.template.xml` | XML template | Modify — show plugin/core examples |
| `skills/app_spec.brownfield.template.xml` | Brownfield template | Modify — show shape attribute usage |
| `tests/spec/test_parser.py` | Spec parser tests | Modify — new test class for shape/plugin |
| `tests/state/test_scheduler.py` | Scheduler tests | Modify — new test class for shape-aware dispatch |
| `tests/test_cli_commands.py` (or appropriate) | CLI integration | Modify — write_plan_to_db round-trip |
| `CLAUDE.md` | Architecture docs | Modify — Spec & Export section, Key Conventions |
| `docs/commands.md` | User-facing CLI docs | Modify — `claw-forge plan` notes the new shape attribute |
| `README.md` | High-level project docs | Modify — Writing a Project Spec section |

---

## Phase 1: Spec Parser Extension

Foundational primitive. Phases 2/3/4 depend on this. After Phase 1 ships, users can hand-write specs with `shape="plugin"` and the file-claim locks already become trivially correct for those features. So even Phase 1 alone is shippable.

### Task 1.1: Extend `FeatureItem` with `shape` and `plugin` fields

**Files:**
- Modify: `claw_forge/spec/parser.py:12-21` (the `FeatureItem` dataclass)
- Test: `tests/spec/test_parser.py` (new test class at end)

- [ ] **Step 1: Write the failing test**

Append to `tests/spec/test_parser.py`:

```python
# ── <feature shape> and <feature plugin> attributes ───────────────────────────


class TestFeatureShapeAndPluginAttrs:
    def test_feature_shape_plugin_is_parsed(self) -> None:
        from claw_forge.spec.parser import parse_spec

        xml = """
        <project_specification>
          <project_name>x</project_name>
          <core_features>
            <category name="Auth">
              <feature index="1" shape="plugin" plugin="auth">
                <description>User can register with email and password</description>
              </feature>
            </category>
          </core_features>
        </project_specification>
        """
        spec = parse_spec(xml)
        assert len(spec.features) == 1
        feat = spec.features[0]
        assert feat.shape == "plugin"
        assert feat.plugin == "auth"

    def test_feature_shape_core_is_parsed(self) -> None:
        from claw_forge.spec.parser import parse_spec

        xml = """
        <project_specification>
          <project_name>x</project_name>
          <core_features>
            <category name="Middleware">
              <feature index="1" shape="core">
                <description>All endpoints validate JWT on incoming requests</description>
              </feature>
            </category>
          </core_features>
        </project_specification>
        """
        spec = parse_spec(xml)
        assert spec.features[0].shape == "core"
        assert spec.features[0].plugin is None

    def test_feature_without_shape_defaults_none(self) -> None:
        """Backward-compat: features without shape attr have shape=None."""
        from claw_forge.spec.parser import parse_spec

        xml = """
        <project_specification>
          <project_name>x</project_name>
          <core_features>
            <category name="Misc">
              <feature index="1"><description>Legacy feature</description></feature>
            </category>
          </core_features>
        </project_specification>
        """
        spec = parse_spec(xml)
        assert spec.features[0].shape is None
        assert spec.features[0].plugin is None

    def test_legacy_bullet_features_have_shape_none(self) -> None:
        """Bullet-form features pre-date shape; they parse to shape=None."""
        from claw_forge.spec.parser import parse_spec

        xml = """
        <project_specification>
          <project_name>x</project_name>
          <core_features>
            <category name="Bullets">
              - User can do something
              - System returns response
            </category>
          </core_features>
        </project_specification>
        """
        spec = parse_spec(xml)
        for feat in spec.features:
            assert feat.shape is None
            assert feat.plugin is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/spec/test_parser.py::TestFeatureShapeAndPluginAttrs -v`
Expected: 4 tests fail with `AttributeError: 'FeatureItem' object has no attribute 'shape'`.

- [ ] **Step 3: Add `shape` and `plugin` fields to `FeatureItem`**

In `claw_forge/spec/parser.py`, replace the `FeatureItem` dataclass (lines 12-21):

```python
@dataclass
class FeatureItem:
    category: str
    name: str  # short name derived from the bullet text
    description: str  # full bullet text
    steps: list[str] = field(default_factory=list)
    depends_on_indices: list[int] = field(default_factory=list)
    # 1-based feature number when declared via <feature index="N">.
    # None for legacy bullets and <feature> elements without an explicit index.
    index: int | None = None
    # Architectural shape of this feature.  ``"plugin"`` = vertical, lives in
    # its own directory under the project's plugin root and never edits files
    # outside it.  ``"core"`` = cross-cutting (middleware, errors, db setup)
    # that legitimately touches files used by every plugin.  ``None`` =
    # unclassified (legacy bullets, pre-Phase-3.25 specs).  The dispatcher
    # uses shape to decide parallel-vs-serial dispatch.
    shape: str | None = None
    # Plugin name when ``shape="plugin"``.  Used to derive ``touches_files``
    # via the project's plugin-root convention (default ``src/plugins/<name>/``).
    # ``None`` when ``shape != "plugin"``.
    plugin: str | None = None
```

- [ ] **Step 4: Parse the new attributes in the `<feature>` element loop**

In `claw_forge/spec/parser.py` around line 188 (where `index_attr` is parsed), insert two lines after the `depends_attr` parsing block (around line 200, after the `explicit_deps` for-loop), so the `FeatureItem(...)` constructor gets the new values:

Find the existing block:

```python
                    depends_attr = feat_el.get("depends_on", "").strip()
                    explicit_deps: list[int] = []
                    if depends_attr:
                        for part in depends_attr.split(","):
                            token = part.strip()
                            if token.isdigit():
                                explicit_deps.append(int(token))
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

Replace with:

```python
                    depends_attr = feat_el.get("depends_on", "").strip()
                    explicit_deps: list[int] = []
                    if depends_attr:
                        for part in depends_attr.split(","):
                            token = part.strip()
                            if token.isdigit():
                                explicit_deps.append(int(token))
                    # Architectural shape.  Empty / unrecognized → None.
                    shape_attr = feat_el.get("shape", "").strip().lower()
                    feat_shape: str | None = (
                        shape_attr if shape_attr in {"plugin", "core"} else None
                    )
                    plugin_attr = feat_el.get("plugin", "").strip()
                    feat_plugin: str | None = plugin_attr if plugin_attr else None
                    features.append(
                        FeatureItem(
                            category=category,
                            name=short_name,
                            description=desc,
                            steps=feat_steps,
                            index=feat_index,
                            depends_on_indices=explicit_deps,
                            shape=feat_shape,
                            plugin=feat_plugin,
                        )
                    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/spec/test_parser.py::TestFeatureShapeAndPluginAttrs -v`
Expected: 4 passed.

- [ ] **Step 6: Run full spec test suite to confirm no regressions**

Run: `uv run pytest tests/spec/ -q`
Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add claw_forge/spec/parser.py tests/spec/test_parser.py
git commit -m "feat(spec): parse <feature shape> and <feature plugin> attributes"
```

---

### Task 1.2: Auto-derive `touches_files` from `plugin=`

**Files:**
- Modify: `claw_forge/spec/parser.py:12-` (extend `FeatureItem` with `touches_files`)
- Modify: `claw_forge/spec/parser.py:188-` (derivation logic in `<feature>` parser)
- Test: `tests/spec/test_parser.py` (extend `TestFeatureShapeAndPluginAttrs`)

- [ ] **Step 1: Write the failing tests**

Append to the `TestFeatureShapeAndPluginAttrs` class in `tests/spec/test_parser.py`:

```python
    def test_plugin_shape_auto_derives_touches_files(self) -> None:
        """``shape="plugin"`` + ``plugin="auth"`` auto-fills touches_files
        with the canonical plugin directory glob.
        """
        from claw_forge.spec.parser import parse_spec

        xml = """
        <project_specification>
          <project_name>x</project_name>
          <core_features>
            <category name="Auth">
              <feature index="1" shape="plugin" plugin="auth">
                <description>User can register</description>
              </feature>
            </category>
          </core_features>
        </project_specification>
        """
        spec = parse_spec(xml)
        feat = spec.features[0]
        assert feat.touches_files == ["src/plugins/auth/**"]

    def test_core_shape_uses_explicit_touches_files(self) -> None:
        """``shape="core"`` requires an explicit touches_files attribute —
        cross-cutting features can't be auto-derived from a directory.
        """
        from claw_forge.spec.parser import parse_spec

        xml = """
        <project_specification>
          <project_name>x</project_name>
          <core_features>
            <category name="Middleware">
              <feature index="1" shape="core"
                       touches_files="src/core/middleware/auth.py">
                <description>JWT middleware</description>
              </feature>
            </category>
          </core_features>
        </project_specification>
        """
        spec = parse_spec(xml)
        assert spec.features[0].touches_files == ["src/core/middleware/auth.py"]

    def test_explicit_touches_files_overrides_plugin_default(self) -> None:
        """When both ``plugin=`` and an explicit ``touches_files=`` are set,
        the explicit value wins — escape hatch for plugins that legitimately
        edit shared infrastructure.
        """
        from claw_forge.spec.parser import parse_spec

        xml = """
        <project_specification>
          <project_name>x</project_name>
          <core_features>
            <category name="Auth">
              <feature index="1" shape="plugin" plugin="auth"
                       touches_files="src/plugins/auth/,src/core/db/migrations/0042_users.sql">
                <description>User can register (extends DB schema)</description>
              </feature>
            </category>
          </core_features>
        </project_specification>
        """
        spec = parse_spec(xml)
        assert spec.features[0].touches_files == [
            "src/plugins/auth/",
            "src/core/db/migrations/0042_users.sql",
        ]

    def test_legacy_feature_has_empty_touches_files(self) -> None:
        """No shape, no plugin → no auto-derivation.  Existing specs are
        unaffected; the dispatcher's file-claim layer treats this as
        opt-out (no claims attempted).
        """
        from claw_forge.spec.parser import parse_spec

        xml = """
        <project_specification>
          <project_name>x</project_name>
          <core_features>
            <category name="Misc">
              <feature index="1"><description>Legacy</description></feature>
            </category>
          </core_features>
        </project_specification>
        """
        spec = parse_spec(xml)
        assert spec.features[0].touches_files == []
```

- [ ] **Step 2: Run tests — confirm they fail**

Run: `uv run pytest tests/spec/test_parser.py::TestFeatureShapeAndPluginAttrs -v -k touches_files`
Expected: 4 fails with `AttributeError: 'FeatureItem' object has no attribute 'touches_files'`.

- [ ] **Step 3: Add `touches_files` to `FeatureItem`**

Replace the `FeatureItem` dataclass in `claw_forge/spec/parser.py` (the version from Task 1.1 plus this addition):

```python
@dataclass
class FeatureItem:
    category: str
    name: str
    description: str
    steps: list[str] = field(default_factory=list)
    depends_on_indices: list[int] = field(default_factory=list)
    index: int | None = None
    shape: str | None = None
    plugin: str | None = None
    # Files this feature is allowed to edit during dispatch.  Auto-derived
    # from ``plugin=`` when ``shape="plugin"`` (becomes
    # ``["src/plugins/<plugin>/**"]``) unless an explicit ``touches_files``
    # attribute overrides.  Required (must be non-empty) for ``shape="core"``.
    # Empty list for legacy bullets — the dispatcher's file-claim layer
    # treats empty as opt-out (no locking attempted).
    touches_files: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Add a derivation helper near the top of `parser.py`**

Insert after the imports block (around line 10, before `FeatureItem`):

```python
# Default plugin-directory glob used when ``shape="plugin"`` and no
# explicit ``touches_files`` attribute is provided.  Matches the layout
# the boundaries-harness ``split`` and ``registry`` patterns produce.
DEFAULT_PLUGIN_ROOT = "src/plugins"


def _derive_touches_files(
    explicit: str,
    shape: str | None,
    plugin: str | None,
) -> list[str]:
    """Resolve the ``touches_files`` list for a single ``<feature>``.

    Precedence (highest to lowest):

    1. Explicit ``touches_files="a,b,c"`` attribute.  Comma-separated
       (whitespace-tolerant); each non-empty entry kept verbatim.
    2. Plugin auto-derivation: ``shape="plugin"`` + ``plugin="X"`` →
       ``[f"{DEFAULT_PLUGIN_ROOT}/X/**"]``.
    3. Empty list — feature opts out of file-claim locking.

    Returns an empty list rather than ``None`` so dispatcher code can do
    ``if feat.touches_files:`` without a ``None`` guard.
    """
    explicit = (explicit or "").strip()
    if explicit:
        parts = [p.strip() for p in explicit.split(",")]
        return [p for p in parts if p]
    if shape == "plugin" and plugin:
        return [f"{DEFAULT_PLUGIN_ROOT}/{plugin}/**"]
    return []
```

- [ ] **Step 5: Wire derivation into the `<feature>` parser**

In `claw_forge/spec/parser.py`, find the block from Task 1.1 that ends with the `features.append(FeatureItem(...))` call.  Update it to read the explicit attribute and derive the list:

```python
                    shape_attr = feat_el.get("shape", "").strip().lower()
                    feat_shape: str | None = (
                        shape_attr if shape_attr in {"plugin", "core"} else None
                    )
                    plugin_attr = feat_el.get("plugin", "").strip()
                    feat_plugin: str | None = plugin_attr if plugin_attr else None
                    explicit_touches = feat_el.get("touches_files", "")
                    feat_touches = _derive_touches_files(
                        explicit_touches, feat_shape, feat_plugin,
                    )
                    features.append(
                        FeatureItem(
                            category=category,
                            name=short_name,
                            description=desc,
                            steps=feat_steps,
                            index=feat_index,
                            depends_on_indices=explicit_deps,
                            shape=feat_shape,
                            plugin=feat_plugin,
                            touches_files=feat_touches,
                        )
                    )
```

- [ ] **Step 6: Run tests — confirm they pass**

Run: `uv run pytest tests/spec/test_parser.py::TestFeatureShapeAndPluginAttrs -v`
Expected: all 8 tests pass (the 4 from Task 1.1 + 4 new).

- [ ] **Step 7: Run full spec test suite**

Run: `uv run pytest tests/spec/ -q`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add claw_forge/spec/parser.py tests/spec/test_parser.py
git commit -m "feat(spec): auto-derive touches_files from <feature plugin>"
```

---

### Task 1.3: Validate `shape="core"` requires non-empty `touches_files`

**Files:**
- Modify: `claw_forge/spec/parser.py` (the `<feature>` parser block)
- Test: `tests/spec/test_parser.py`

- [ ] **Step 1: Write the failing test**

Append to `TestFeatureShapeAndPluginAttrs`:

```python
    def test_core_shape_without_touches_files_raises(self) -> None:
        """``shape="core"`` features can't be auto-derived; missing
        ``touches_files`` is a spec error rather than a silent opt-out.
        """
        import pytest as _pytest
        from claw_forge.spec.parser import parse_spec

        xml = """
        <project_specification>
          <project_name>x</project_name>
          <core_features>
            <category name="Middleware">
              <feature index="1" shape="core">
                <description>JWT middleware</description>
              </feature>
            </category>
          </core_features>
        </project_specification>
        """
        with _pytest.raises(ValueError, match="touches_files"):
            parse_spec(xml)
```

- [ ] **Step 2: Run test — confirm it fails**

Run: `uv run pytest tests/spec/test_parser.py::TestFeatureShapeAndPluginAttrs::test_core_shape_without_touches_files_raises -v`
Expected: fail (no ValueError currently).

- [ ] **Step 3: Add the validation immediately after derivation**

In `claw_forge/spec/parser.py`, after the `feat_touches = _derive_touches_files(...)` line and before the `features.append(...)`, insert:

```python
                    if feat_shape == "core" and not feat_touches:
                        raise ValueError(
                            f"<feature shape='core'> '{short_name}' "
                            "requires an explicit touches_files attribute "
                            "(core features are cross-cutting and can't "
                            "be auto-derived from a directory)."
                        )
```

- [ ] **Step 4: Run test — confirm it passes**

Run: `uv run pytest tests/spec/test_parser.py::TestFeatureShapeAndPluginAttrs::test_core_shape_without_touches_files_raises -v`
Expected: pass.

- [ ] **Step 5: Run full spec suite**

Run: `uv run pytest tests/spec/ -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add claw_forge/spec/parser.py tests/spec/test_parser.py
git commit -m "feat(spec): validate shape='core' requires explicit touches_files"
```

---

### Task 1.4: Persist `shape` + `plugin` through `_write_plan_to_db` to the state DB

**Files:**
- Modify: `claw_forge/state/models.py` (add `shape`, `plugin` columns to `Task`)
- Modify: `claw_forge/state/service.py` (extend `CreateTaskRequest` schema, add column-migration in `_ensure_task_columns`)
- Modify: `claw_forge/cli.py` (`_write_plan_to_db` reads from FeatureItem, passes to API)
- Test: `tests/state/test_service.py` (round-trip a task with shape/plugin)

- [ ] **Step 1: Write the failing test**

Append to `tests/state/test_service.py`:

```python
class TestTaskShapeAndPlugin:
    def test_create_task_round_trips_shape_and_plugin(self) -> None:
        """POST /sessions/{id}/tasks accepts shape + plugin and they survive
        the round-trip via GET /sessions/{id}/tasks.
        """
        # Reuse the existing in-process state-service fixture pattern from
        # this file — adapt to whatever the test harness provides.
        client, session_id = _make_client_with_session()
        resp = client.post(
            f"/sessions/{session_id}/tasks",
            json={
                "plugin_name": "coding",
                "description": "User can register",
                "category": "Auth",
                "shape": "plugin",
                "plugin": "auth",
                "touches_files": ["src/plugins/auth/**"],
            },
        )
        assert resp.status_code == 200, resp.text
        task_id = resp.json()["id"]

        listing = client.get(f"/sessions/{session_id}/tasks").json()
        match = next(t for t in listing if t["id"] == task_id)
        assert match["shape"] == "plugin"
        assert match["plugin"] == "auth"
```

The harness helper `_make_client_with_session` should match the convention used elsewhere in the file — copy the pattern from an existing passing test in `test_service.py`.

- [ ] **Step 2: Run test — confirm it fails**

Run: `uv run pytest tests/state/test_service.py::TestTaskShapeAndPlugin -v`
Expected: fail with `KeyError: 'shape'` or `400 Bad Request` (extra fields rejected by Pydantic).

- [ ] **Step 3: Add columns to the SQLAlchemy `Task` model**

In `claw_forge/state/models.py` (around the existing `touches_files` column at line ~139), add:

```python
    shape: Mapped[str | None] = mapped_column(String(16), nullable=True)
    plugin: Mapped[str | None] = mapped_column(String(64), nullable=True)
```

Place them above the `created_at` column so the schema reads logically.

- [ ] **Step 4: Add the columns to the legacy-DB migration**

In `claw_forge/state/service.py`, find the `_ensure_task_columns` (or equivalent) function that runs `ALTER TABLE tasks ADD COLUMN ...` for new fields.  Append two new tries:

```python
    "ALTER TABLE tasks ADD COLUMN shape VARCHAR(16)",
    "ALTER TABLE tasks ADD COLUMN plugin VARCHAR(64)",
```

These mirror the existing pattern (e.g. the `touches_files` migration around line 326) — wrap each in the same try/except suppressing duplicate-column errors.

- [ ] **Step 5: Extend `CreateTaskRequest` Pydantic schema**

In `claw_forge/state/service.py`, find `CreateTaskRequest` (or whatever the POST-body model is named — search for `class CreateTask` near line 800).  Add fields:

```python
    shape: str | None = None
    plugin: str | None = None
```

Where the request is converted to a `Task(...)` instance (the same function that constructed `bugfix_retry_count=req.bugfix_retry_count`), pass them through:

```python
                    shape=req.shape,
                    plugin=req.plugin,
```

- [ ] **Step 6: Update `_task_summary` to expose them**

The helper that converts a `Task` row to the summary dict for `GET /sessions/{id}/tasks` (search for `def _task_summary` near the top half of `service.py`).  Add the two fields:

```python
    "shape": t.shape,
    "plugin": t.plugin,
```

- [ ] **Step 7: Wire `FeatureItem.shape` / `plugin` through `_write_plan_to_db`**

In `claw_forge/cli.py`, find `async def _write_plan_to_db` (line 2262 approx).  When it constructs the JSON body for each feature's task POST, add the new fields.  Locate the `payload = {...}` dict (or however the body is built) and add:

```python
            "shape": feat.shape,
            "plugin": feat.plugin,
```

`feat` is the `FeatureItem` being iterated.  No fallback needed — `None` is the legacy behaviour the schema already accepts.

- [ ] **Step 8: Run tests — confirm they pass**

Run: `uv run pytest tests/state/test_service.py::TestTaskShapeAndPlugin -v`
Expected: pass.

- [ ] **Step 9: Run state + cli + spec test suites**

Run: `uv run pytest tests/state/ tests/spec/ tests/test_cli_commands.py -q`
Expected: all green.

- [ ] **Step 10: Commit**

```bash
git add claw_forge/state/models.py claw_forge/state/service.py claw_forge/cli.py tests/state/test_service.py
git commit -m "feat(state): persist <feature shape> + <feature plugin> on tasks"
```

---

### Task 1.5: Phase-1 docs

**Files:**
- Modify: `CLAUDE.md` (Spec & Export section)
- Modify: `docs/commands.md` (`claw-forge plan` section)
- Modify: `README.md` (Writing a Project Spec section)
- Modify: `skills/app_spec.template.xml` (greenfield example)

- [ ] **Step 1: Update CLAUDE.md**

In `CLAUDE.md` find the `### spec/parser.py` section (around line ~210).  Add a paragraph documenting the new attributes:

```markdown
The XML schema also accepts two architectural-shape attributes on `<feature>`:

- **`shape="plugin" | "core"`** — declares whether the feature is vertical
  (lives in its own directory under the project's plugin root) or
  cross-cutting.  Plugin-shape features auto-derive `touches_files`;
  core-shape features must declare `touches_files` explicitly.
- **`plugin="<name>"`** — directory ownership for plugin-shape features.
  When `shape="plugin"` and `plugin="auth"`, `touches_files` defaults to
  `["src/plugins/auth/**"]` (override via the explicit `touches_files`
  attribute).  Used by the dispatcher's file-claim locks for parallel
  conflict prevention.

```xml
<feature index="14" shape="plugin" plugin="auth">
  <description>User can register with email and password</description>
</feature>
<feature index="20" shape="core"
         touches_files="src/core/middleware/auth.py">
  <description>All endpoints validate JWT</description>
</feature>
```

`shape="core"` without an explicit `touches_files` attribute raises a
parse error (cross-cutting features can't be auto-derived from a
directory).  Specs without `shape` attributes parse identically to
before — pure backward compatibility.
```

- [ ] **Step 2: Update docs/commands.md**

In the `### claw-forge plan` section, add a subsection at the end:

```markdown
#### Architectural shape attributes

The parser accepts two attributes on `<feature>` that affect dispatcher
behaviour:

| Attribute | Values | Effect |
|---|---|---|
| `shape` | `plugin` / `core` | Plugin = lives in its own directory; core = cross-cutting |
| `plugin` | string | Directory name (under `src/plugins/<name>/`) when `shape="plugin"` |
| `touches_files` | comma-separated paths | Explicit file globs (overrides plugin auto-derivation) |

When `shape="plugin"` and a `plugin=` attribute is set, `touches_files`
defaults to `["src/plugins/<plugin>/**"]`, giving the dispatcher's
file-claim locks an unambiguous file set per feature.  See
[CLAUDE.md → spec/parser.py](../CLAUDE.md) for detailed semantics.
```

- [ ] **Step 3: Update README.md**

In the "Writing a Project Spec" section, append after the existing XML examples:

```markdown
### Architectural shape (parallel-safety hint)

Add a `shape` attribute to each `<feature>` so the dispatcher knows
how to schedule it for parallel-safe execution:

```xml
<feature index="14" shape="plugin" plugin="auth">
  <description>User can register with email and password</description>
</feature>
<feature index="20" shape="core"
         touches_files="src/core/middleware/auth.py">
  <description>All endpoints validate JWT</description>
</feature>
```

Plugin-shape features can run in parallel (their files don't overlap by
construction).  Core-shape features serialize via the dispatcher's
single-flight rule for cross-cutting changes.
```

- [ ] **Step 4: Update `skills/app_spec.template.xml`**

Update one of the existing `<feature>` examples in the template to demonstrate the new attributes — pick a category where it's natural (e.g. an Auth example).  Add a comment:

```xml
<!-- shape="plugin" + plugin="auth" auto-fills touches_files=["src/plugins/auth/**"] -->
<feature index="1" shape="plugin" plugin="auth">
  <description>User can register with email and password</description>
</feature>
```

- [ ] **Step 5: Run docs-related tests if any**

Run: `uv run pytest tests/spec/ tests/test_init.py -q`
Expected: green (the template is parsed by some fixtures).

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md docs/commands.md README.md skills/app_spec.template.xml
git commit -m "docs: document <feature shape> / <feature plugin> attributes"
```

---

### Phase 1 wrap-up: full verification

- [ ] **Run full test suite**: `uv run pytest tests/ -q --ignore=tests/e2e/test_pool_e2e.py` → expect all green.
- [ ] **Run lint**: `uv run ruff check claw_forge/ tests/` → expect clean.
- [ ] **Run mypy**: `uv run mypy claw_forge/ --ignore-missing-imports` → expect clean.
- [ ] **Open PR with title `feat(spec): plugin/core shape attributes for parallel-safe scheduling (Phase 1 of 4)`**.

Phase 1 ships value alone: hand-written specs with `shape="plugin"` already give the dispatcher unambiguous file ownership, and the file-claim locks become trivially correct for plugin features.  Phases 2-4 layer on top.

---

## Phase 2: `/create-spec` Phase 3.25 — Architectural Shape

Adds the interactive classification step to greenfield `/create-spec`.  Users see "your features map to these plugins / these core concerns; sound right?" and the slash command emits the spec with `shape` / `plugin` attributes filled in.

### Task 2.1: Insert Phase 3.25 markdown section

**Files:**
- Modify: `.claude/commands/create-spec.md` (insert between Phase 3 at line 174 and Phase 3.5 at line 216)

- [ ] **Step 1: Insert Phase 3.25 directly above Phase 3.5**

In `.claude/commands/create-spec.md`, find the line `### Phase 3.5: Overlap Analysis` (line 216) and insert immediately above it:

```markdown
### Phase 3.25: Architectural Shape

After confirming the feature list with the user (Phase 3) and before
overlap analysis (Phase 3.5), classify each feature as either a
**plugin** (vertical, lives in its own directory) or **core**
(cross-cutting, edits files used by every plugin).  The classification
ends up in the emitted XML as `<feature shape>` / `<feature plugin>`
attributes — the dispatcher reads these for parallel-safe scheduling.

#### Step 1 — Group features by likely shape

Read through the confirmed feature list and silently group:

- **Plugin candidates**: features whose description names a single
  domain noun ("user", "task", "billing", "notifications") and whose
  acceptance criteria all read like "user can …" or "system returns …
  for the X resource".  These typically own their own data model,
  routes, and tests, and can be added or removed without touching
  sibling plugins.
- **Core candidates**: features that say "all endpoints …", "every
  request …", "uniform error format", "shared logging", "global rate
  limit", "authentication middleware", "database migrations".  These
  are cross-cutting — they're touched by every plugin's request path.

A feature can be plugin-shape even if it depends on a core concern.
"User can register" is plugin-shape (lives in `plugins/auth/`) even
though it relies on the core `core/db/` connection pool.

#### Step 2 — Confirm with the user

Present the grouping back, naming the plugin directories:

```
Looking at your features, I'd structure them as:

Plugins (parallel-safe — each in its own directory):
  • plugins/auth/      — registration, login, password reset (5 features)
  • plugins/profile/   — view/edit profile, avatar upload (4 features)
  • plugins/tasks/     — CRUD, search, tag filter, pagination (8 features)

Core (cross-cutting — touch every plugin's request path):
  • core/middleware/   — JWT validation, request logging (2 features)
  • core/errors/       — RFC7807 error envelope (1 feature)
  • core/db/           — connection pool, migrations runner (2 features)

Sound right?  Edits welcome:
  - Reclassify a feature: "move feature 14 to core"
  - Rename a plugin:      "rename profile to user-profile"
  - Add a category:       "add plugins/notifications"
```

The user can:
- **Accept** → record the classification.
- **Edit** by line: "move 14 to core", "rename profile to user-profile",
  "split tasks into tasks-crud and tasks-search".
- **Skip** → emit the spec without `shape`/`plugin` attributes (legacy
  behaviour).  Phase 5 emits unchanged.

#### Step 3 — Persist the classification

Build a per-feature dict in memory:

```
feature_shape[<index>] = {
    "shape": "plugin" | "core",
    "plugin": "<plugin_name>" | None,         # set when shape="plugin"
    "touches_files": ["..."] | None,           # set when shape="core" only
}
```

Phase 5 reads this when emitting `<feature>` elements.  Plugin features
get `shape="plugin" plugin="X"` and the parser auto-derives `touches_files`.
Core features get `shape="core" touches_files="..."` (the prose from Step
2 — typically a single file path the user names — becomes the
`touches_files` value).

#### Failure modes

- **User skips classification** → emit Phase 5 unchanged; no `shape`
  attributes.  The legacy parsing path still works; the dispatcher's
  file-claim layer treats every feature as opt-out (no locking
  attempted).
- **A feature can't be classified** (LLM unsure or user says "I don't
  know") → leave that feature unclassified in `feature_shape`.  Phase 5
  emits without `shape` for that feature.
- **User declares a plugin name that conflicts with an existing
  filesystem path** in brownfield mode → warn but accept (the
  boundaries-harness can refactor the colliding file later).

---
```

- [ ] **Step 2: Update Phase 5's emit examples**

In `.claude/commands/create-spec.md`, find Phase 5 (line 317).  After the existing Phase 3.5 example XML (with `<feature index>` + `<feature depends_on>`), add a new example showing the shape attributes:

```xml
<!-- Phase 3.25 + Phase 3.5 combined: plugin-shape + dependency edge -->
<feature index="14" shape="plugin" plugin="auth">
  <description>User can register with email and password</description>
</feature>
<feature index="18" shape="plugin" plugin="auth" depends_on="14">
  <description>System sends welcome email after registration</description>
</feature>
<feature index="20" shape="core"
         touches_files="src/core/middleware/auth.py">
  <description>All endpoints validate JWT on incoming requests</description>
</feature>
```

- [ ] **Step 3: Update Phase 6 next-steps to mention parallel-safety**

In Phase 6 of `.claude/commands/create-spec.md`, append a tip:

```markdown
**Tip:** Features with `shape="plugin"` in your spec can be dispatched
in parallel without merge conflicts (their `touches_files` are
disjoint by construction).  Features with `shape="core"` serialize
single-flight via the scheduler's cross-cutting rule.  See
docs/commands.md → "claw-forge run" for parallelism settings.
```

- [ ] **Step 4: Commit**

```bash
git add .claude/commands/create-spec.md
git commit -m "feat(create-spec): add Phase 3.25 architectural-shape classification"
```

---

### Task 2.2: Phase-2 verification

Phase 2 is documentation-only (no Python changes).  Verification consists of:

- [ ] **Step 1: Open `/create-spec.md` in a Claude Code chat panel** and run the slash command against a small example spec input.  Confirm Phase 3.25 fires after Phase 3 and that the emitted XML contains `shape` / `plugin` attributes parsable by Phase 1's parser.
- [ ] **Step 2: Run a tight round-trip test**

Add to `tests/spec/test_parser.py`:

```python
    def test_phase_325_example_round_trip(self) -> None:
        """The XML example written into create-spec.md Phase 5 must round-
        trip cleanly through the parser — guards against doc/code drift.
        """
        from claw_forge.spec.parser import parse_spec

        xml = """
        <project_specification>
          <project_name>round-trip</project_name>
          <core_features>
            <category name="Auth">
              <feature index="14" shape="plugin" plugin="auth">
                <description>User can register with email and password</description>
              </feature>
              <feature index="18" shape="plugin" plugin="auth" depends_on="14">
                <description>System sends welcome email after registration</description>
              </feature>
            </category>
            <category name="Middleware">
              <feature index="20" shape="core"
                       touches_files="src/core/middleware/auth.py">
                <description>All endpoints validate JWT on incoming requests</description>
              </feature>
            </category>
          </core_features>
        </project_specification>
        """
        spec = parse_spec(xml)
        plugin_feats = [f for f in spec.features if f.shape == "plugin"]
        core_feats = [f for f in spec.features if f.shape == "core"]
        assert len(plugin_feats) == 2
        assert all(f.plugin == "auth" for f in plugin_feats)
        assert all(f.touches_files == ["src/plugins/auth/**"] for f in plugin_feats)
        assert len(core_feats) == 1
        assert core_feats[0].touches_files == ["src/core/middleware/auth.py"]
```

- [ ] **Step 3: Run test**

Run: `uv run pytest tests/spec/test_parser.py::TestFeatureShapeAndPluginAttrs::test_phase_325_example_round_trip -v`
Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add tests/spec/test_parser.py
git commit -m "test(spec): round-trip the Phase 3.25 example from create-spec.md"
```

- [ ] **Step 5: Open PR** with title `feat(create-spec): Phase 3.25 architectural-shape classification (Phase 2 of 4)`.

---

## Phase 3: Scheduler Shape-Awareness

Makes the dispatcher honour the `shape` field: plugin-shape tasks dispatch freely up to `max_concurrency`; core-shape tasks single-flight (only one in flight at a time, regardless of concurrency setting).

### Task 3.1: Add `shape` + `plugin` fields to `TaskNode`

**Files:**
- Modify: `claw_forge/state/scheduler.py:9-25` (the `TaskNode` dataclass)
- Modify: `claw_forge/cli.py` (the `_task_dict_to_node` helper at line 259-)
- Test: `tests/state/test_scheduler.py` (or wherever `TaskNode` is tested)

- [ ] **Step 1: Write the failing test**

Append to `tests/state/test_scheduler.py`:

```python
class TestTaskNodeShape:
    def test_task_node_carries_shape_and_plugin(self) -> None:
        from claw_forge.state.scheduler import TaskNode

        node = TaskNode(
            id="t1", plugin_name="coding", priority=0, depends_on=[],
            shape="plugin", plugin="auth",
        )
        assert node.shape == "plugin"
        assert node.plugin == "auth"

    def test_task_node_shape_defaults_none(self) -> None:
        from claw_forge.state.scheduler import TaskNode

        node = TaskNode(
            id="t1", plugin_name="coding", priority=0, depends_on=[],
        )
        assert node.shape is None
        assert node.plugin is None
```

- [ ] **Step 2: Run test — confirm it fails**

Run: `uv run pytest tests/state/test_scheduler.py::TestTaskNodeShape -v`
Expected: fail with `TypeError: TaskNode.__init__() got an unexpected keyword argument 'shape'`.

- [ ] **Step 3: Add fields to `TaskNode`**

In `claw_forge/state/scheduler.py`, replace the `TaskNode` dataclass:

```python
@dataclass
class TaskNode:
    """Lightweight task representation for scheduling."""

    id: str
    plugin_name: str
    priority: int
    depends_on: list[str]
    status: str = "pending"
    category: str = ""
    steps: list[str] = field(default_factory=list)
    description: str = ""
    merged_to_target_branch: bool = True  # gate: dep not satisfied until merged
    touches_files: list[str] = field(default_factory=list)
    resumable: bool = False
    # Architectural shape from the spec — drives parallel-vs-serial dispatch.
    # ``"plugin"`` features have disjoint ``touches_files`` and dispatch
    # freely up to ``max_concurrency``.  ``"core"`` features single-flight
    # (cross-cutting; only one runs at a time).  ``None`` falls back to
    # legacy behaviour (concurrency-cap + file-claim locks only).
    shape: str | None = None
    plugin: str | None = None
```

- [ ] **Step 4: Update `_task_dict_to_node` in cli.py**

In `claw_forge/cli.py` (line 259), find the helper that converts a task summary dict into a `TaskNode`.  Add to the construction:

```python
        shape=payload.get("shape"),
        plugin=payload.get("plugin"),
```

(Add next to the existing `touches_files=...` line.)

- [ ] **Step 5: Run test — confirm it passes**

Run: `uv run pytest tests/state/test_scheduler.py::TestTaskNodeShape -v`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add claw_forge/state/scheduler.py claw_forge/cli.py tests/state/test_scheduler.py
git commit -m "feat(scheduler): TaskNode carries shape + plugin from spec"
```

---

### Task 3.2: Single-flight gate for `shape="core"` tasks

**Files:**
- Modify: `claw_forge/state/scheduler.py` (the ready-task selection logic)
- Test: `tests/state/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/state/test_scheduler.py`:

```python
class TestSchedulerCoreSingleFlight:
    def test_core_task_excludes_other_core_tasks_from_ready_set(self) -> None:
        """When a ``shape="core"`` task is in flight (status='running'),
        no other ``shape="core"`` task is ready, even if its dependencies
        are satisfied.  Cross-cutting changes serialize.
        """
        from claw_forge.state.scheduler import Scheduler, TaskNode

        sched = Scheduler()
        sched.add_task(TaskNode(
            id="c1", plugin_name="coding", priority=0, depends_on=[],
            shape="core", status="running",
        ))
        sched.add_task(TaskNode(
            id="c2", plugin_name="coding", priority=0, depends_on=[],
            shape="core", status="pending",
        ))
        ready = sched.get_ready_tasks()
        assert "c2" not in {t.id for t in ready}, (
            "second core task must not be ready while another core task runs"
        )

    def test_core_task_does_not_block_plugin_tasks(self) -> None:
        """A running ``shape="core"`` task only excludes other core tasks —
        plugin tasks are unaffected and still dispatch in parallel.
        """
        from claw_forge.state.scheduler import Scheduler, TaskNode

        sched = Scheduler()
        sched.add_task(TaskNode(
            id="c1", plugin_name="coding", priority=0, depends_on=[],
            shape="core", status="running",
        ))
        sched.add_task(TaskNode(
            id="p1", plugin_name="coding", priority=0, depends_on=[],
            shape="plugin", plugin="auth", status="pending",
        ))
        ready_ids = {t.id for t in sched.get_ready_tasks()}
        assert "p1" in ready_ids

    def test_no_core_in_flight_lets_one_core_through(self) -> None:
        """When no core task is running, exactly one of the queued core
        tasks should appear in the ready set per call (the highest-priority
        one — same as the existing priority rule).
        """
        from claw_forge.state.scheduler import Scheduler, TaskNode

        sched = Scheduler()
        sched.add_task(TaskNode(
            id="c1", plugin_name="coding", priority=10, depends_on=[],
            shape="core",
        ))
        sched.add_task(TaskNode(
            id="c2", plugin_name="coding", priority=5, depends_on=[],
            shape="core",
        ))
        ready_ids = [t.id for t in sched.get_ready_tasks()]
        # Both can be in the candidate set; the dispatcher caps to
        # max_concurrency.  We only assert that core tasks aren't being
        # filtered out when no other core is in flight.
        assert "c1" in ready_ids
```

- [ ] **Step 2: Run tests — confirm they fail**

Run: `uv run pytest tests/state/test_scheduler.py::TestSchedulerCoreSingleFlight -v`
Expected: 1-2 fail (the existing scheduler doesn't have core-aware filtering yet).

- [ ] **Step 3: Add the single-flight filter to `get_ready_tasks`**

Find the existing `get_ready_tasks` method in `claw_forge/state/scheduler.py` (search by `def get_ready_tasks`).  At the end of its filter chain, add:

```python
        # Cross-cutting (shape="core") tasks single-flight: drop any
        # candidate ``core`` task from the ready set if another core task
        # is already running.
        any_core_running = any(
            t.status == "running" and t.shape == "core"
            for t in self._tasks.values()
        )
        if any_core_running:
            ready = [t for t in ready if t.shape != "core"]
```

(`ready` is the list being built by the existing function; if its name is different, adapt.)

- [ ] **Step 4: Run tests — confirm they pass**

Run: `uv run pytest tests/state/test_scheduler.py::TestSchedulerCoreSingleFlight -v`
Expected: pass.

- [ ] **Step 5: Run full scheduler suite**

Run: `uv run pytest tests/state/test_scheduler.py -q`
Expected: green (existing tests should be unaffected — the new filter is a no-op when no core task is running).

- [ ] **Step 6: Commit**

```bash
git add claw_forge/state/scheduler.py tests/state/test_scheduler.py
git commit -m "feat(scheduler): single-flight core-shape tasks across the dispatcher"
```

---

### Task 3.3: Phase-3 docs

**Files:**
- Modify: `CLAUDE.md` (Key Conventions block)
- Modify: `docs/commands.md` (`claw-forge run` parallelism notes)

- [ ] **Step 1: Add a "Shape-aware scheduling" entry to CLAUDE.md → Key Conventions**

Append to the Key Conventions list:

```markdown
- **Shape-aware scheduling** (`<feature shape>` from spec → `TaskNode.shape`):
  the scheduler honours two architectural shapes from the spec.
  `shape="plugin"` tasks dispatch freely up to `max_concurrency` (their
  `touches_files` are disjoint by construction since each plugin owns
  its own directory).  `shape="core"` tasks **single-flight** — at most
  one cross-cutting task runs at a time, regardless of `max_concurrency`,
  so middleware/error/database changes don't race each other.  Tasks
  without `shape` (legacy specs) fall through to the existing
  concurrency-cap + file-claim-locks behaviour.
```

- [ ] **Step 2: Update docs/commands.md `claw-forge run`**

Append to the run section, before "Failure modes":

```markdown
#### Parallelism + architectural shape

The dispatcher consults each task's `shape` attribute when selecting the
next ready task:

| Shape | Dispatch policy |
|---|---|
| `plugin` | Up to `--concurrency N` in parallel; `touches_files` auto-derived from plugin directory |
| `core` | Single-flight (only one core task at a time, regardless of `--concurrency`) |
| _unset_ | Legacy: concurrency cap + file-claim locks only |

This makes high-concurrency runs structurally safe: plugin-shape tasks
operate on disjoint files, so the file-claim locks rarely contend; core
tasks queue serially so cross-cutting middleware/error/DB changes don't
race.  Spec-time classification is the input — see [`/create-spec` Phase
3.25](#claw-forge-create-spec) for how to populate it.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/commands.md
git commit -m "docs: shape-aware scheduling rules in CLAUDE.md + commands.md"
```

- [ ] **Step 4: Open PR** with title `feat(scheduler): shape-aware single-flight for core tasks (Phase 3 of 4)`.

---

## Phase 4: Brownfield Integration with `boundaries_report.md`

Brownfield `/create-spec` reads `boundaries_report.md` (if present in the project root) and surfaces hotspots before generating the spec.  Users get a chance to refactor hotspots via `claw-forge boundaries apply` first; the resulting plugin-extensible patterns then make new feature additions land cleanly as `shape="plugin"`.

### Task 4.1: Brownfield `/create-spec` reads `boundaries_report.md`

**Files:**
- Modify: `.claude/commands/create-spec.md` (Brownfield Step 1, around line 29)

- [ ] **Step 1: Add a sub-step that detects the boundaries report**

In `.claude/commands/create-spec.md`, find Brownfield Flow → Step 1 (line 29) and replace it with:

```markdown
### Step 1: Load manifest + check for hotspot report

Read `brownfield_manifest.json` and extract:
- `stack` (language, framework, database)
- `test_baseline` (N tests, X% coverage)
- `conventions` (naming style, patterns, etc.)

Then check whether `boundaries_report.md` is present in the project root
(emitted by a prior `claw-forge boundaries audit`).  If it exists and
contains entries with score >= 5.0, surface them to the user before
proceeding:

```
Found a boundaries audit at boundaries_report.md.  These files are
extension hotspots — adding new features as <feature shape="plugin">
will collide with them unless they're refactored first:

  cli/main.py        score=8.4  pattern=registry
  core/router.py     score=6.7  pattern=route_table

Recommended:
  claw-forge boundaries apply --auto

Refactoring these into plugin-extensible patterns first will let your
new features land cleanly as plugins.

Proceed anyway?  [y / yes]   Refactor first?  [b / boundaries]
```

If the user picks `b`, stop the slash command — they'll come back
after the refactor.  If they pick `y`, record the hotspot list as a
warning in `<existing_context>` and continue to Step 2.

If `boundaries_report.md` doesn't exist, continue to Step 2 silently.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/commands/create-spec.md
git commit -m "feat(create-spec): brownfield checks boundaries_report.md before spec emit"
```

---

### Task 4.2: Brownfield Step 2 asks for `shape` + `plugin` per feature

**Files:**
- Modify: `.claude/commands/create-spec.md` (Brownfield Step 2, around line 38)

- [ ] **Step 1: Update the Step 2 question list**

Replace the Step 2 numbered question list with:

```markdown
### Step 2: Gather addition details

Ask the user (one at a time):

1. **What are you adding?** Give it a name and one-sentence summary.
   - Example: "Stripe payments — let users subscribe to Pro plan via Stripe Checkout"

2. **Where does it live in the codebase?**
   - **Plugin** (lives in its own directory): "I'll add `plugins/payments/`
     for the Stripe code."  Used when the addition is vertical and isolated.
   - **Core** (cross-cutting): "I'll edit `core/middleware/auth.py` and
     `core/db/models/user.py`."  Used when the addition modifies shared
     infrastructure.

   For each feature, record either `plugin="<name>"` (plugin shape) or
   `touches_files="..."` (core shape).  This populates the new
   `<feature shape>` attributes in Phase 3 of the parser, which lets
   the dispatcher schedule for parallel safety.

3. **What must NOT change?** List any constraints.
   - Example: "Must not modify auth flow. All 47 existing tests must stay green."

4. **List the features to add in plain English** (one per line, action-verb format):
   - Example: "User can add a payment method via Stripe Elements"
   - Aim for 10–50 features for a medium addition.

5. **Break them into implementation phases** (optional — offer to auto-group).
```

- [ ] **Step 2: Update Step 3 emit example**

Find Step 3's example XML and update the `<features_to_add>` block to use the new attributes:

```xml
<features_to_add>
  <category name="Payments">
    <feature index="1" shape="plugin" plugin="payments">
      <description>User can add a payment method via Stripe Elements</description>
    </feature>
    <feature index="2" shape="plugin" plugin="payments" depends_on="1">
      <description>User can subscribe to Pro plan via Stripe Checkout</description>
    </feature>
    <feature index="3" shape="core"
             touches_files="src/core/db/models/user.py">
      <description>Extends User model with stripe_customer_id field</description>
    </feature>
  </category>
</features_to_add>
```

Match this example to the existing prose around it.

- [ ] **Step 3: Commit**

```bash
git add .claude/commands/create-spec.md
git commit -m "feat(create-spec): brownfield asks for shape + plugin per feature"
```

---

### Task 4.3: Phase-4 docs

**Files:**
- Modify: `docs/commands.md` (`claw-forge add` and `claw-forge boundaries` sections)
- Modify: `CLAUDE.md` (Boundaries Harness section — link to spec-time use)

- [ ] **Step 1: Add a "Brownfield workflow with boundaries" subsection to docs/commands.md**

Append under `### claw-forge boundaries`:

```markdown
#### Brownfield workflow

When adding features to an existing codebase, the recommended sequence
is:

1. **`claw-forge analyze`** — generate `brownfield_manifest.json` with
   stack/conventions/test-baseline.
2. **`claw-forge boundaries audit`** — emit `boundaries_report.md`
   with extension hotspots (files where adding a feature would collide
   with existing dispatch logic).
3. **`claw-forge boundaries apply --auto`** — refactor each hotspot
   into a plugin-extensible pattern (registry / split / route-table /
   extract-collaborators).  Squash-merges to main on green tests,
   reverts on red.
4. **`/create-spec`** in Claude Code — generates `additions_spec.xml`.
   The slash command reads `boundaries_report.md` and warns about any
   un-refactored hotspots before proceeding.  Each feature is asked
   about its `shape` (plugin vs core) so the spec carries the right
   attributes for parallel-safe scheduling.
5. **`claw-forge add --spec additions_spec.xml`** — runs the
   plan-to-DB writer and starts the dispatcher.

Skipping step 3 means new features may collide with the un-refactored
hotspots; the dispatcher's pre-dispatch sync will surface those as
`resume_conflict` failures, but the agent will have already wasted time
on stale state by then.  Refactoring up front is cheaper.
```

- [ ] **Step 2: Update CLAUDE.md → Boundaries Harness**

Find `### Boundaries Harness (`claw_forge/boundaries/`)` and append a sentence at the end:

```markdown
The boundaries harness composes with shape-aware specs: refactoring a
hotspot file into a registry / split / route-table pattern (the four
canonical patterns the harness emits) means future feature additions
can land as `<feature shape="plugin">` cleanly — the file ownership is
unambiguous so the dispatcher's parallel-safety guarantees apply.  See
`docs/commands.md` → `claw-forge boundaries` → "Brownfield workflow"
for the recommended sequence.
```

- [ ] **Step 3: Commit**

```bash
git add docs/commands.md CLAUDE.md
git commit -m "docs: brownfield workflow combining boundaries + shape-aware spec"
```

- [ ] **Step 4: Open PR** with title `feat(create-spec): brownfield integration with boundaries_report.md (Phase 4 of 4)`.

---

## Phase 5: Final Verification + Release

After all four phases land on `main` (each as its own PR), run a final cross-cutting verification.

- [ ] **Step 1: Round-trip end-to-end smoke test**

Build a tiny synthetic spec with one plugin feature and one core feature, run `claw-forge plan` against it, then `claw-forge status` to see the tasks landed in the DB with the expected shape/plugin fields.

```bash
cd /tmp && rm -rf shape-smoke && mkdir shape-smoke && cd shape-smoke
cat > app_spec.xml << 'EOF'
<project_specification>
  <project_name>shape-smoke</project_name>
  <overview>Smoke test for shape-aware scheduling.</overview>
  <core_features>
    <category name="Auth">
      <feature index="1" shape="plugin" plugin="auth">
        <description>User can register</description>
      </feature>
    </category>
    <category name="Middleware">
      <feature index="2" shape="core"
               touches_files="src/core/middleware/auth.py">
        <description>JWT validation</description>
      </feature>
    </category>
  </core_features>
</project_specification>
EOF
git init -q -b main && git commit -q --allow-empty -m "init"
claw-forge plan app_spec.xml
claw-forge status | grep -E "shape|plugin"
```

Expected: two tasks visible, one with `shape=plugin plugin=auth`, one with `shape=core`.

- [ ] **Step 2: Cut release**

After all PRs merge and CI is green on main:

```bash
gh release create v0.6.0 --target main \
  --title "v0.6.0 — Plugin-shape-aware spec generation + shape-aware dispatch" \
  --notes-file docs/superpowers/plans/2026-05-02-plugin-shape-aware-specs.md
```

Use a minor-version bump (0.5.x → 0.6.0) since this introduces a new XML schema feature and dispatcher policy.

---

## Self-Review Checklist (run before handoff)

- [ ] **Spec coverage:** Every requirement from the conversation maps to a task. Plugin/core schema = Phase 1. `/create-spec` Phase 3.25 = Phase 2. Scheduler shape-awareness = Phase 3. Brownfield + boundaries integration = Phase 4. Docs included in each phase per the standing convention.
- [ ] **Placeholder scan:** No "TODO", "implement later", "similar to Task N", or step descriptions without code blocks. Each task has actual test code, actual implementation code, exact commit messages.
- [ ] **Type consistency:** `FeatureItem.shape: str | None`, `FeatureItem.plugin: str | None`, `FeatureItem.touches_files: list[str]` defined in Phase 1 Task 1.1/1.2 are referenced consistently in Phase 1 Task 1.4 (DB persistence), Phase 3 Task 3.1 (TaskNode mirroring), and the `/create-spec` examples in Phase 2/4. Method signatures (`_derive_touches_files(explicit, shape, plugin)`) match across the parser code and tests.
- [ ] **Docs included:** Each phase has an explicit docs task — Phase 1 Task 1.5, Phase 2 inline in the slash command, Phase 3 Task 3.3, Phase 4 Task 4.3 — per the standing project convention that new behaviour requires `CLAUDE.md` + `docs/commands.md` + `README.md` updates.

---

## Out of Scope (call-outs for follow-up)

- **Static `touches_files` inference for legacy specs.** Phase 1 makes `touches_files` empty for features without `shape`; the dispatcher's file-claim layer treats empty as opt-out. A follow-up could static-analyse the description text + existing codebase to populate `touches_files` for legacy specs without requiring the user to add `shape` attributes. Not blocking — legacy behaviour is unchanged.
- **Plugin host scaffolding generator.** Greenfield projects need a plugin-discovery mechanism (entry-points, filesystem walk, etc.) for `shape="plugin"` features to actually wire up. `claw-forge init` could scaffold this when the user picks a "plugin-architected" project template. Big enough to deserve its own plan; not blocking shape-aware scheduling.
- **Predictive overlap at scheduler-time.** With `branch_overlap_files` already shipped (PR #23), the scheduler could pre-check overlap between in-flight task branches and queued tasks, deferring queued tasks predicted to conflict. Composes with Phase 3's single-flight rule but is a strictly bigger change. Suggest a follow-up plan after Phase 3 lands and we observe how often conflicts still surface.
- **LLM-driven shape classification.** Phase 2 has the user manually classify each feature. A follow-up plugin (or `/create-spec` Phase 3.25 Step 1.5) could use the LLM to propose classifications automatically and have the user confirm. Reduces friction; skipped here to keep the first version reviewable.
