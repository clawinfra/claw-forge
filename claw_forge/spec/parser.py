"""XML and plain-text spec parser for claw-forge project specifications."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    if explicit:
        parts = [p.strip() for p in explicit.split(",")]
        return [p for p in parts if p]
    if shape == "plugin" and plugin:
        return [f"{DEFAULT_PLUGIN_ROOT}/{plugin}/**"]
    return []


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
    # Files this feature is allowed to edit during dispatch.  Auto-derived
    # from ``plugin=`` when ``shape="plugin"`` (becomes
    # ``["src/plugins/<plugin>/**"]``) unless an explicit ``touches_files``
    # attribute overrides.  Required (must be non-empty) for ``shape="core"``.
    # Empty list for legacy bullets — the dispatcher's file-claim layer
    # treats empty as opt-out (no locking attempted).
    touches_files: list[str] = field(default_factory=list)


@dataclass
class TechStack:
    frontend_framework: str = ""
    frontend_port: int = 3000
    backend_runtime: str = ""
    backend_db: str = ""
    backend_port: int = 3001
    raw: str = ""


@dataclass
class ProjectSpec:
    project_name: str
    overview: str
    tech_stack: TechStack
    features: list[FeatureItem]  # all features, 100-400 items
    implementation_phases: list[str]  # phase titles in order
    success_criteria: list[str]
    design_system: dict[str, Any]  # color_palette, typography, etc.
    api_endpoints: dict[str, Any]  # category -> list of endpoints
    database_tables: dict[str, Any]  # table_name -> list of columns
    raw_xml: str  # preserved for reference
    mode: str = "greenfield"  # "greenfield" or "brownfield"
    addition_summary: str = ""
    existing_context: dict[str, str] = field(default_factory=dict)  # stack, test_baseline, etc.
    integration_points: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)

    @property
    def is_brownfield(self) -> bool:
        """Return True if this is a brownfield (addition) spec."""
        return self.mode == "brownfield"

    def to_agent_context(self, manifest: dict[str, Any] | None = None) -> str:
        """Return a formatted string for injection into agent system prompts.

        Greenfield specs return a brief overview.
        Brownfield specs return existing_context + integration_points + constraints.
        """
        if not self.is_brownfield:
            return (
                f"## Project: {self.project_name}\n"
                f"{self.overview}\n\n"
                f"Stack: {self.tech_stack.raw or 'see spec'}\n"
                f"Features: {len(self.features)}"
            )

        # Merge manifest into existing_context (manifest wins)
        ctx = dict(self.existing_context)
        if manifest:
            for key in ("stack", "test_baseline", "conventions"):
                if key in manifest:
                    ctx[key] = str(manifest[key])

        lines: list[str] = ["## Existing Codebase Context"]
        for key, value in ctx.items():
            label = key.replace("_", " ").title()
            lines.append(f"{label}: {value}")

        if self.integration_points:
            lines.append("\n## Integration Points")
            for point in self.integration_points:
                lines.append(f"- {point}")

        if self.constraints:
            lines.append("\n## Constraints (must not violate)")
            for constraint in self.constraints:
                lines.append(f"- {constraint}")

        return "\n".join(lines)

    @classmethod
    def from_file(cls, path: Path) -> ProjectSpec:
        """Parse app_spec.txt (XML or plain text) into ProjectSpec."""
        content = path.read_text(encoding="utf-8")
        if "<project_specification" in content:
            return cls._parse_xml(content)
        else:
            return cls._parse_plain_text(content)

    @classmethod
    def _parse_xml(cls, content: str) -> ProjectSpec:
        """Parse AutoForge-style XML spec."""
        # Strip XML comments before parsing
        content_no_comments = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
        root = ET.fromstring(content_no_comments.strip())

        mode = root.get("mode", "greenfield")
        name = root.findtext("project_name", "").strip()
        overview = root.findtext("overview", "").strip()

        # Brownfield: addition_summary
        addition_summary = root.findtext("addition_summary", "").strip()

        # Brownfield: existing_context children → dict
        existing_context: dict[str, str] = {}
        ec_el = root.find("existing_context")
        if ec_el is not None:
            for child in ec_el:
                text = (child.text or "").strip()
                if text:
                    existing_context[child.tag] = text

        # Brownfield: integration_points (one per non-empty line)
        integration_points: list[str] = []
        ip_el = root.find("integration_points")
        if ip_el is not None:
            for line in (ip_el.text or "").splitlines():
                stripped = line.strip()
                if stripped:
                    integration_points.append(stripped)

        # Brownfield: constraints (one per non-empty line)
        constraints: list[str] = []
        con_el = root.find("constraints")
        if con_el is not None:
            for line in (con_el.text or "").splitlines():
                stripped = line.strip()
                if stripped:
                    constraints.append(stripped)

        # Parse tech stack
        ts_el = root.find("technology_stack")
        tech = TechStack()
        if ts_el is not None:
            fe = ts_el.find("frontend")
            be = ts_el.find("backend")
            if fe is not None:
                tech.frontend_framework = fe.findtext("framework", "").strip()
                port_text = fe.findtext("port", "3000").strip()
                tech.frontend_port = int(port_text) if port_text.isdigit() else 3000
            if be is not None:
                tech.backend_runtime = be.findtext("runtime", "").strip()
                tech.backend_db = be.findtext("database", "").strip()
                port_text = be.findtext("port", "3001").strip()
                tech.backend_port = int(port_text) if port_text.isdigit() else 3001
            tech.raw = ET.tostring(ts_el, encoding="unicode")

        # Parse features from <core_features> or <features_to_add> — each bullet = one feature
        features: list[FeatureItem] = []
        _cf = root.find("core_features")
        _fta = root.find("features_to_add")
        feature_root_el = _cf if _cf is not None else _fta
        if feature_root_el is not None:
            for category_el in feature_root_el:
                # Support both <category name="…"> and legacy <tag_name> formats
                _name_attr = category_el.get("name", "")
                category = _name_attr if _name_attr else category_el.tag.replace("_", " ").title()
                feature_els = category_el.findall("feature")
                # New format: parse every <feature> child if present.  This
                # runs in addition to (not instead of) legacy-bullet parsing
                # so a category can mix both forms during migration.
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
                    # Optional <feature index="N"> attribute (1-based)
                    index_attr = feat_el.get("index", "").strip()
                    feat_index = int(index_attr) if index_attr.isdigit() else None
                    # Optional <feature depends_on="N,M,..."> — comma-separated
                    # 1-based feature indices.  Whitespace and non-digit fragments
                    # are tolerated (skipped).  Empty / missing → no edges.
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
                    explicit_touches = feat_el.get("touches_files", "").strip()
                    feat_touches = _derive_touches_files(
                        explicit_touches, feat_shape, feat_plugin,
                    )
                    if feat_shape == "core" and not feat_touches:
                        raise ValueError(
                            f"<feature shape='core'> '{short_name}' "
                            "requires an explicit touches_files attribute "
                            "(core features are cross-cutting and can't "
                            "be auto-derived from a directory)."
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
                # Legacy bullet format: text bullets directly in category element text.
                # Runs alongside the <feature> branch above so categories can mix forms.
                text = category_el.text or ""
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("- ") or stripped.startswith("* "):
                        bullet = stripped[2:].strip()
                        if bullet:
                            # Derive a short name: first 60 chars, title-cased
                            short_name = bullet[:60].rstrip(".,:;")
                            features.append(
                                FeatureItem(
                                    category=category,
                                    name=short_name,
                                    description=bullet,
                                )
                            )

        # Brownfield: if <features_to_add> has plain-text lines (not sub-elements),
        # parse them directly as flat feature list under "Addition" category.
        if feature_root_el is None:  # pragma: no cover
            fta_el = root.find("features_to_add")
            if fta_el is not None and not list(fta_el):
                # No child elements — flat text block
                for line in (fta_el.text or "").splitlines():
                    stripped = line.strip()
                    if stripped.startswith("- ") or stripped.startswith("* "):
                        bullet = stripped[2:].strip()
                        if bullet:
                            short_name = bullet[:60].rstrip(".,:;")
                            features.append(
                                FeatureItem(
                                    category="Addition",
                                    name=short_name,
                                    description=bullet,
                                )
                            )
                    elif stripped and not stripped.startswith("#"):
                        short_name = stripped[:60].rstrip(".,:;")
                        features.append(
                            FeatureItem(
                                category="Addition",
                                name=short_name,
                                description=stripped,
                            )
                        )

        # Assign depends_on_indices based on implementation_steps order
        # Features in later steps depend on features in earlier steps (same category)
        impl_el = root.find("implementation_steps")
        phases: list[str] = []
        if impl_el is not None:
            for step_el in impl_el:
                # Greenfield format: <step><title>...</title></step>
                title = step_el.findtext("title", "").strip()
                if title:
                    phases.append(title)
                else:
                    # Brownfield format: <phase name="...">
                    phase_name = step_el.get("name", "").strip()
                    if phase_name:
                        phases.append(phase_name)
                        # Assign features listed in this phase to it
                        for line in (step_el.text or "").splitlines():
                            stripped = line.strip()
                            if stripped and not stripped.startswith("#"):
                                # Match features by description and assign phase category
                                for feat in features:
                                    if feat.description == stripped and feat.category == "Addition":
                                        feat.category = phase_name

        # Resolve attribute-based depends_on (1-based feature numbers via
        # <feature index="N">) into 0-based positional indices, matching the
        # convention used by ``_assign_dependencies`` and downstream consumers
        # (``initializer.py``, ``_write_plan_to_db``).  This runs BEFORE
        # phase inference so the post-condition ("depends_on_indices is always
        # 0-based positional") is uniform across both edge sources.
        index_to_pos: dict[int, int] = {
            f.index: pos for pos, f in enumerate(features) if f.index is not None
        }
        for feat in features:
            if not feat.depends_on_indices:
                continue
            feat.depends_on_indices = [
                index_to_pos[ref] for ref in feat.depends_on_indices
                if ref in index_to_pos
            ]

        # Build category -> phase index map from step titles
        # Features in step N depend on features in steps 1..N-1 (same category group)
        dep_indices = _assign_dependencies(features, phases)
        for i, deps in enumerate(dep_indices):
            # Preserve explicit <feature depends_on="..."> edges — phase-based
            # inference only fills in features that didn't declare any.
            if features[i].depends_on_indices:
                continue
            features[i].depends_on_indices = deps

        # Parse success criteria
        sc_el = root.find("success_criteria")
        criteria: list[str] = []
        if sc_el is not None:
            # Greenfield: child elements with bullet lines
            if list(sc_el):
                for section in sc_el:
                    for line in (section.text or "").splitlines():
                        stripped = line.strip()
                        if stripped.startswith("- "):
                            criteria.append(stripped[2:].strip())
            else:
                # Brownfield: flat text, one criterion per non-empty line
                for line in (sc_el.text or "").splitlines():
                    stripped = line.strip()
                    if stripped:
                        criteria.append(stripped)

        # Parse design system
        ds_el = root.find("design_system")
        design: dict[str, Any] = {}
        if ds_el is not None:
            design = _parse_key_value_el(ds_el)

        # Parse API endpoints
        api_el = root.find("api_endpoints_summary")
        endpoints: dict[str, Any] = {}
        if api_el is not None:
            for cat in api_el:
                # Support both <domain name="…"> and legacy <tag_name> formats
                _domain_name = cat.get("name", "")
                cat_name = _domain_name if _domain_name else cat.tag.replace("_", " ").title()
                items = []
                for line in (cat.text or "").splitlines():
                    stripped = line.strip()
                    if stripped.startswith("- "):
                        items.append(stripped[2:].strip())
                    elif stripped:
                        # Plain lines like "POST /api/auth/register - Register …"
                        items.append(stripped)
                if items:
                    endpoints[cat_name] = items

        # Parse database schema
        db_el = root.find("database_schema")
        tables: dict[str, Any] = {}
        if db_el is not None:
            tables_el = db_el.find("tables")
            if tables_el is not None:
                for table_el in tables_el:
                    # Support new <table name="…"><column> format and legacy <tablename>- …
                    table_name = table_el.get("name") or table_el.tag
                    cols = []
                    col_els = table_el.findall("column")
                    if col_els:
                        for col_el in col_els:
                            text = (col_el.text or "").strip()
                            if text:
                                cols.append(text)
                    else:
                        for line in (table_el.text or "").splitlines():
                            stripped = line.strip()
                            if stripped.startswith("- "):
                                cols.append(stripped[2:].strip())
                    if cols:
                        tables[table_name] = cols

        return cls(
            project_name=name,
            overview=overview,
            tech_stack=tech,
            features=features,
            implementation_phases=phases,
            success_criteria=criteria,
            design_system=design,
            api_endpoints=endpoints,
            database_tables=tables,
            raw_xml=content,
            mode=mode,
            addition_summary=addition_summary,
            existing_context=existing_context,
            integration_points=integration_points,
            constraints=constraints,
        )

    @classmethod
    def _parse_plain_text(cls, content: str) -> ProjectSpec:
        """Parse claw-forge plain text spec.

        Supports two feature formats:
        1. Numbered list::

              1. Feature name
                 Description: ...
                 Depends on: 1

        2. Bullet list under a ``Features:`` (or ``Features`` / category) header::

              Features:
              - Feature one
              - Feature two

              Authentication:
              - Login endpoint
              - JWT token generation
        """
        lines = content.splitlines()
        name = ""
        stack = ""
        features: list[FeatureItem] = []
        current_feature: dict[str, Any] | None = None
        # Track whether we're inside a bullet-list section and its category name
        _bullet_section: str | None = None

        # Regex patterns
        _numbered = re.compile(r"^\d+\.\s+\S")
        # Section header: "Features:" or "Authentication:" etc. — a non-blank line
        # ending in ":" that is NOT a known key:value field
        _KNOWN_KV = {"project", "stack", "description", "depends on", "version"}
        _section_header = re.compile(r"^([A-Za-z][A-Za-z0-9 _-]*):\s*$")

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith("Project:"):
                name = stripped.split(":", 1)[1].strip()
                _bullet_section = None
                continue
            if stripped.startswith("Stack:"):
                stack = stripped.split(":", 1)[1].strip()
                _bullet_section = None
                continue

            # Numbered feature: "1. Feature name"
            if _numbered.match(stripped):
                if current_feature:
                    features.append(_dict_to_feature(current_feature))
                _bullet_section = None
                current_feature = {
                    "name": re.sub(r"^\d+\.\s+", "", stripped),
                    "category": "Feature",
                    "description": "",
                    "steps": [],
                    "depends_on": [],
                }
                continue

            if stripped.startswith("Description:") and current_feature:
                current_feature["description"] = stripped.split(":", 1)[1].strip()
                continue
            if stripped.startswith("Depends on:") and current_feature:
                raw = stripped.split(":", 1)[1].strip()
                current_feature["depends_on"] = [
                    int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()
                ]
                continue

            # Bullet item: "-" or "*" prefix
            if stripped.startswith("- ") or stripped.startswith("* "):
                bullet = stripped[2:].strip()
                if not bullet:
                    continue
                if _bullet_section is not None:
                    # Top-level feature under a section header
                    if current_feature:
                        features.append(_dict_to_feature(current_feature))
                        current_feature = None
                    features.append(FeatureItem(
                        category=_bullet_section,
                        name=bullet[:60].rstrip(".,:;"),
                        description=bullet,
                    ))
                elif current_feature is not None:
                    # Step/detail line inside a numbered feature
                    current_feature["steps"].append(bullet)
                else:
                    # Bare bullet with no section — treat as a feature
                    features.append(FeatureItem(
                        category="Feature",
                        name=bullet[:60].rstrip(".,:;"),
                        description=bullet,
                    ))
                continue

            # Section header: "Features:" / "Authentication:" / "Core:" etc.
            m = _section_header.match(stripped)
            if m and m.group(1).lower() not in _KNOWN_KV:
                if current_feature:
                    features.append(_dict_to_feature(current_feature))
                    current_feature = None
                _bullet_section = m.group(1).strip()
                continue

            # Any other line inside a numbered feature is treated as a description
            if current_feature and not current_feature.get("description"):
                current_feature["description"] = stripped

        if current_feature:
            features.append(_dict_to_feature(current_feature))

        tech = TechStack(raw=stack)
        return cls(
            project_name=name or "project",
            overview="",
            tech_stack=tech,
            features=features,
            implementation_phases=[],
            success_criteria=[],
            design_system={},
            api_endpoints={},
            database_tables={},
            raw_xml=content,
        )


def _dict_to_feature(d: dict[str, Any]) -> FeatureItem:
    f = FeatureItem(
        category=d["category"],
        name=d["name"],
        description=d.get("description", d["name"]),
        steps=d.get("steps", []),
    )
    f.depends_on_indices = d.get("depends_on", [])
    return f


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


def _parse_key_value_el(el: ET.Element) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for child in el:
        text = (child.text or "").strip()
        items = [line[2:].strip() for line in text.splitlines() if line.strip().startswith("- ")]
        result[child.tag] = items if items else text
    return result


def generate_brownfield_manifest(
    spec: ProjectSpec,
    completed_tasks: int,
    project_path: Path,
) -> dict[str, str]:
    """Build a brownfield manifest dict from a completed greenfield run.

    Args:
        spec: The parsed project spec.
        completed_tasks: Number of tasks that completed successfully.
        project_path: Root of the target project (used to detect conventions).

    Returns:
        A dict with ``stack``, ``test_baseline``, and ``conventions`` keys.
    """
    # ── stack ──────────────────────────────────────────────────────────
    ts = spec.tech_stack
    parts: list[str] = []
    if ts.backend_runtime:
        parts.append(ts.backend_runtime)
    if ts.frontend_framework:
        parts.append(ts.frontend_framework)
    if ts.backend_db:
        parts.append(ts.backend_db)
    stack = " / ".join(parts) if parts else (ts.raw.strip() or "unknown")

    # ── test_baseline ─────────────────────────────────────────────────
    test_baseline = f"{completed_tasks} features completed"

    # ── conventions (detect from project config files) ────────────────
    conventions: list[str] = []
    if (project_path / "pyproject.toml").exists():
        _pyproject = (project_path / "pyproject.toml").read_text(encoding="utf-8")
        if "ruff" in _pyproject:
            conventions.append("ruff")
        if "mypy" in _pyproject:
            conventions.append("mypy")
        if "pytest" in _pyproject:
            conventions.append("pytest")
    if (project_path / ".eslintrc.json").exists() or (
        project_path / ".eslintrc.js"
    ).exists() or (project_path / "eslint.config.js").exists():
        conventions.append("eslint")
    if (project_path / "biome.json").exists():
        conventions.append("biome")
    if (project_path / "tsconfig.json").exists():
        conventions.append("typescript")
    if (project_path / "tailwind.config.js").exists() or (
        project_path / "tailwind.config.ts"
    ).exists():
        conventions.append("tailwind")

    return {
        "stack": stack,
        "test_baseline": test_baseline,
        "conventions": ", ".join(conventions) if conventions else "see project config",
    }
