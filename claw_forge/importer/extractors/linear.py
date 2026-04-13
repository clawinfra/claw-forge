"""Linear JSON extractor — reads issues.json exported from Linear."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claw_forge.importer.detector import FormatResult
from claw_forge.importer.extractors.base import Epic, ExtractedSpec, Story


def extract_linear(result: FormatResult) -> ExtractedSpec:
    """Extract structure from a Linear JSON export into an ExtractedSpec."""
    json_path = result.artifacts[0] if result.artifacts else None

    data = _load_json(json_path)
    if data is None:
        return ExtractedSpec(
            project_name="Unnamed Project",
            overview="",
            epics=[],
            tech_stack_raw="",
            database_tables_raw="",
            api_endpoints_raw="",
            existing_context={},
            integration_points=[],
            constraints=[],
            source_format="linear",
            source_path=json_path.parent if json_path else Path("."),
            epic_count=0,
            story_count=0,
        )

    project = data.get("project") or {}
    project_name = project.get("name") or "Unnamed Project"
    overview = project.get("description") or ""

    issues = data.get("issues") or []
    epics = _group_by_label(issues)

    story_count = sum(len(e.stories) for e in epics)
    source_path = json_path.parent if json_path else Path(".")

    return ExtractedSpec(
        project_name=project_name,
        overview=overview,
        epics=epics,
        tech_stack_raw="",
        database_tables_raw="",
        api_endpoints_raw="",
        existing_context={},
        integration_points=[],
        constraints=[],
        source_format="linear",
        source_path=source_path,
        epic_count=len(epics),
        story_count=story_count,
    )


def _load_json(json_path: Path | None) -> dict[str, Any] | None:
    """Load and parse a JSON file; return None on any error."""
    if json_path is None or not json_path.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(json_path.read_text(encoding="utf-8"))
        return data
    except (json.JSONDecodeError, OSError):
        return None


def _label_name(label: object) -> str:
    """Normalise a label that may be a string or a dict with a 'name' key."""
    if isinstance(label, dict):
        return label.get("name") or ""
    if isinstance(label, str):
        return label
    return ""


def _group_by_label(issues: list[dict[str, Any]]) -> list[Epic]:
    """Group issues into Epics by their first label; unlabelled → 'General'."""
    # Use an ordered dict to preserve insertion order
    epic_map: dict[str, list[Story]] = {}

    for issue in issues:
        labels = issue.get("labels") or []
        epic_name = _label_name(labels[0]) or "General" if labels else "General"

        title = issue.get("title") or ""
        description = issue.get("description") or ""
        story = Story(title=title, acceptance_criteria=description, phase_hint=epic_name)
        epic_map.setdefault(epic_name, []).append(story)

    return [Epic(name=name, stories=stories) for name, stories in epic_map.items()]
