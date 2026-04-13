"""Jira extractor — reads RSS/XML or CSV exports from Jira."""
from __future__ import annotations

import csv
import xml.etree.ElementTree as ET
from pathlib import Path

from claw_forge.importer.detector import FormatResult
from claw_forge.importer.extractors.base import Epic, ExtractedSpec, Story


def extract_jira(result: FormatResult) -> ExtractedSpec:
    """Extract structure from a Jira XML or CSV export into an ExtractedSpec."""
    artifact = result.artifacts[0] if result.artifacts else None

    if artifact is None:
        return _empty_spec(Path("."))

    suffix = artifact.suffix.lower()
    if suffix == ".xml":
        return _extract_xml(artifact)
    if suffix == ".csv":
        return _extract_csv(artifact)
    # Fallback: try XML first, then CSV
    return _empty_spec(artifact.parent)


# ---------------------------------------------------------------------------
# XML extraction
# ---------------------------------------------------------------------------


def _extract_xml(xml_path: Path) -> ExtractedSpec:
    """Parse a Jira RSS/XML export file."""
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError:
        return _empty_spec(xml_path.parent)

    root = tree.getroot()
    channel = root.find("channel")
    if channel is None:
        return _empty_spec(xml_path.parent)

    title_el = channel.find("title")
    project_name = (
        title_el.text.strip()
        if title_el is not None and title_el.text
        else "Unnamed Project"
    )

    epic_map: dict[str, list[Story]] = {}

    for item in channel.findall("item"):
        summary_el = item.find("summary")
        desc_el = item.find("description")

        title = summary_el.text.strip() if summary_el is not None and summary_el.text else ""
        description = desc_el.text.strip() if desc_el is not None and desc_el.text else ""

        epic_name = _get_epic_link_xml(item)
        story = Story(title=title, acceptance_criteria=description, phase_hint=epic_name)
        epic_map.setdefault(epic_name, []).append(story)

    epics = [Epic(name=name, stories=stories) for name, stories in epic_map.items()]
    story_count = sum(len(e.stories) for e in epics)

    return ExtractedSpec(
        project_name=project_name,
        overview="",
        epics=epics,
        tech_stack_raw="",
        database_tables_raw="",
        api_endpoints_raw="",
        existing_context={},
        integration_points=[],
        constraints=[],
        source_format="jira",
        source_path=xml_path.parent,
        epic_count=len(epics),
        story_count=story_count,
    )


def _get_epic_link_xml(item: ET.Element) -> str:
    """Return the Epic Link value from a Jira XML <item>, or 'General'."""
    # Jira XML nests customfields → customfield → customfieldname + customfieldvalues
    customfields = item.find("customfields")
    if customfields is not None:
        for cf in customfields.findall("customfield"):
            name_el = cf.find("customfieldname")
            if name_el is not None and name_el.text and name_el.text.strip() == "Epic Link":
                values_el = cf.find("customfieldvalues")
                if values_el is not None:
                    val_el = values_el.find("customfieldvalue")
                    if val_el is not None and val_el.text:
                        return val_el.text.strip()
    return "General"


# ---------------------------------------------------------------------------
# CSV extraction
# ---------------------------------------------------------------------------


def _extract_csv(csv_path: Path) -> ExtractedSpec:
    """Parse a Jira CSV export file."""
    epic_map: dict[str, list[Story]] = {}
    project_name = "Unnamed Project"

    try:
        with csv_path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            first_row = True
            for row in reader:
                if first_row:
                    project_name = (row.get("Project") or "").strip() or "Unnamed Project"
                    first_row = False

                title = (row.get("Summary") or "").strip()
                description = (row.get("Description") or "").strip()
                epic_name = (row.get("Epic Link") or "").strip() or "General"

                if not title:
                    continue

                story = Story(title=title, acceptance_criteria=description, phase_hint=epic_name)
                epic_map.setdefault(epic_name, []).append(story)
    except (OSError, csv.Error):
        return _empty_spec(csv_path.parent)

    epics = [Epic(name=name, stories=stories) for name, stories in epic_map.items()]
    story_count = sum(len(e.stories) for e in epics)

    return ExtractedSpec(
        project_name=project_name,
        overview="",
        epics=epics,
        tech_stack_raw="",
        database_tables_raw="",
        api_endpoints_raw="",
        existing_context={},
        integration_points=[],
        constraints=[],
        source_format="jira",
        source_path=csv_path.parent,
        epic_count=len(epics),
        story_count=story_count,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_spec(source_path: Path) -> ExtractedSpec:
    """Return a minimal empty ExtractedSpec for error cases."""
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
        source_format="jira",
        source_path=source_path,
        epic_count=0,
        story_count=0,
    )
