"""XML and plain-text spec parser for claw-forge project specifications."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FeatureItem:
    category: str
    name: str  # short name derived from the bullet text
    description: str  # full bullet text
    steps: list[str] = field(default_factory=list)
    depends_on_indices: list[int] = field(default_factory=list)


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
    design_system: dict  # color_palette, typography, etc.
    api_endpoints: dict  # category -> list of endpoints
    database_tables: dict  # table_name -> list of columns
    raw_xml: str  # preserved for reference

    @classmethod
    def from_file(cls, path: Path) -> "ProjectSpec":
        """Parse app_spec.txt (XML or plain text) into ProjectSpec."""
        content = path.read_text(encoding="utf-8")
        if "<project_specification" in content:
            return cls._parse_xml(content)
        else:
            return cls._parse_plain_text(content)

    @classmethod
    def _parse_xml(cls, content: str) -> "ProjectSpec":
        """Parse AutoForge-style XML spec."""
        # Strip XML comments before parsing
        content_no_comments = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
        root = ET.fromstring(content_no_comments.strip())

        name = root.findtext("project_name", "").strip()
        overview = root.findtext("overview", "").strip()

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

        # Parse features from <core_features> — each bullet = one feature
        features: list[FeatureItem] = []
        cf_el = root.find("core_features")
        if cf_el is not None:
            for category_el in cf_el:
                category = category_el.tag.replace("_", " ").title()
                text = category_el.text or ""
                # Extract bullet items: lines starting with -
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

        # Assign depends_on_indices based on implementation_steps order
        # Features in later steps depend on features in earlier steps (same category)
        impl_el = root.find("implementation_steps")
        phases: list[str] = []
        if impl_el is not None:
            for step_el in impl_el:
                title = step_el.findtext("title", "").strip()
                if title:
                    phases.append(title)

        # Build category -> phase index map from step titles
        # Features in step N depend on features in steps 1..N-1 (same category group)
        _assign_dependencies(features, phases)

        # Parse success criteria
        sc_el = root.find("success_criteria")
        criteria: list[str] = []
        if sc_el is not None:
            for section in sc_el:
                for line in (section.text or "").splitlines():
                    stripped = line.strip()
                    if stripped.startswith("- "):
                        criteria.append(stripped[2:].strip())

        # Parse design system
        ds_el = root.find("design_system")
        design: dict = {}
        if ds_el is not None:
            design = _parse_key_value_el(ds_el)

        # Parse API endpoints
        api_el = root.find("api_endpoints_summary")
        endpoints: dict = {}
        if api_el is not None:
            for cat in api_el:
                cat_name = cat.tag.replace("_", " ").title()
                items = []
                for line in (cat.text or "").splitlines():
                    stripped = line.strip()
                    if stripped.startswith("- "):
                        items.append(stripped[2:].strip())
                if items:
                    endpoints[cat_name] = items

        # Parse database schema
        db_el = root.find("database_schema")
        tables: dict = {}
        if db_el is not None:
            tables_el = db_el.find("tables")
            if tables_el is not None:
                for table_el in tables_el:
                    cols = []
                    for line in (table_el.text or "").splitlines():
                        stripped = line.strip()
                        if stripped.startswith("- "):
                            cols.append(stripped[2:].strip())
                    if cols:
                        tables[table_el.tag] = cols

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
        )

    @classmethod
    def _parse_plain_text(cls, content: str) -> "ProjectSpec":
        """Parse claw-forge plain text spec (numbered features format)."""
        lines = content.splitlines()
        name = ""
        stack = ""
        features: list[FeatureItem] = []
        current_feature: dict | None = None

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("Project:"):
                name = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("Stack:"):
                stack = stripped.split(":", 1)[1].strip()
            elif re.match(r"^\d+\.\s+\S", stripped):
                # New feature: "1. Feature name"
                if current_feature:
                    features.append(_dict_to_feature(current_feature))
                current_feature = {
                    "name": re.sub(r"^\d+\.\s+", "", stripped),
                    "category": "Feature",
                    "description": "",
                    "steps": [],
                    "depends_on": [],
                }
            elif stripped.startswith("Description:") and current_feature:
                current_feature["description"] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("Depends on:") and current_feature:
                raw = stripped.split(":", 1)[1].strip()
                current_feature["depends_on"] = [
                    int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()
                ]
            elif stripped.startswith("- ") and current_feature:
                current_feature["steps"].append(stripped[2:].strip())

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


def _dict_to_feature(d: dict) -> FeatureItem:
    f = FeatureItem(
        category=d["category"],
        name=d["name"],
        description=d.get("description", d["name"]),
        steps=d.get("steps", []),
    )
    f.depends_on_indices = d.get("depends_on", [])
    return f


def _assign_dependencies(features: list[FeatureItem], phases: list[str]) -> None:
    """Assign depends_on_indices based on phase ordering.

    Features in a later phase depend on ALL features from the previous phase.
    This mirrors AutoForge's initializer agent behavior.
    """
    if not phases:
        return
    # Map category keywords to phase index
    # This is a heuristic — the initializer agent can refine it
    phase_feature_indices: list[list[int]] = [[] for _ in phases]

    # Assign each feature to a phase based on category name matching phase titles
    for i, feature in enumerate(features):
        assigned = False
        for p_idx, phase_title in enumerate(phases):
            phase_keywords = set(phase_title.lower().split())
            cat_keywords = set(feature.category.lower().split())
            if phase_keywords & cat_keywords:  # any overlap
                phase_feature_indices[p_idx].append(i)
                assigned = True
                break
        if not assigned:
            # Default to middle phase
            mid = len(phases) // 2
            phase_feature_indices[mid].append(i)

    # For each phase, all features depend on all features in the previous phase
    for p_idx in range(1, len(phases)):
        prev_phase_indices = phase_feature_indices[p_idx - 1]
        for feat_idx in phase_feature_indices[p_idx]:
            features[feat_idx].depends_on_indices = list(prev_phase_indices)


def _parse_key_value_el(el: ET.Element) -> dict:
    result: dict = {}
    for child in el:
        text = (child.text or "").strip()
        items = [line[2:].strip() for line in text.splitlines() if line.strip().startswith("- ")]
        result[child.tag] = items if items else text
    return result
