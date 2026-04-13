"""Generic markdown extractor — handles any folder of .md files."""
from __future__ import annotations

import re
from pathlib import Path

from claw_forge.importer.detector import FormatResult
from claw_forge.importer.extractors.base import Epic, ExtractedSpec, Story

# Heading patterns
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")

# Tech/arch section names (case-insensitive match against heading text)
_TECH_STACK_NAMES = {"tech stack", "technology stack", "stack", "architecture"}
_DATABASE_NAMES = {"database schema", "database", "schema"}
_API_NAMES = {"api endpoints", "api", "endpoints"}


def extract_generic(result: FormatResult) -> ExtractedSpec:
    """Extract structure from generic .md files into an ExtractedSpec."""
    if not result.artifacts:
        return _empty_spec(source_path=Path("."))

    source_path = result.artifacts[0].parent

    project_name = "Unnamed Project"
    overview = ""
    epics: list[Epic] = []
    tech_stack_raw = ""
    database_tables_raw = ""
    api_endpoints_raw = ""

    for idx, artifact in enumerate(result.artifacts):
        try:
            text = artifact.read_text(encoding="utf-8")
        except OSError:
            continue

        lines = text.splitlines()
        (
            file_project_name,
            file_overview,
            file_epics,
            file_tech,
            file_db,
            file_api,
        ) = _parse_md_file(lines, is_first_file=(idx == 0))

        if idx == 0:
            project_name = file_project_name
            overview = file_overview

        epics.extend(file_epics)
        if file_tech and not tech_stack_raw:
            tech_stack_raw = file_tech
        if file_db and not database_tables_raw:
            database_tables_raw = file_db
        if file_api and not api_endpoints_raw:
            api_endpoints_raw = file_api

    story_count = sum(len(e.stories) for e in epics)

    return ExtractedSpec(
        project_name=project_name,
        overview=overview,
        epics=epics,
        tech_stack_raw=tech_stack_raw,
        database_tables_raw=database_tables_raw,
        api_endpoints_raw=api_endpoints_raw,
        existing_context={},
        integration_points=[],
        constraints=[],
        source_format="generic",
        source_path=source_path,
        epic_count=len(epics),
        story_count=story_count,
    )


def _empty_spec(source_path: Path) -> ExtractedSpec:
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
        source_format="generic",
        source_path=source_path,
        epic_count=0,
        story_count=0,
    )


def _is_tech_section(heading_text: str) -> str | None:
    """Return the section type ('tech', 'db', 'api') or None."""
    lower = heading_text.lower().strip()
    if lower in _TECH_STACK_NAMES:
        return "tech"
    if lower in _DATABASE_NAMES:
        return "db"
    if lower in _API_NAMES:
        return "api"
    return None


def _parse_md_file(
    lines: list[str],
    is_first_file: bool,
) -> tuple[str, str, list[Epic], str, str, str]:
    """Parse a single markdown file's lines.

    Returns:
        (project_name, overview, epics, tech_stack_raw, database_tables_raw, api_endpoints_raw)
    """
    project_name = "Unnamed Project"
    overview = ""
    epics: list[Epic] = []
    tech_stack_raw = ""
    database_tables_raw = ""
    api_endpoints_raw = ""

    # State machine
    current_epic: Epic | None = None
    current_story_title: str | None = None
    current_story_lines: list[str] = []
    overview_found = False
    first_h1_seen = False

    # Tech section state
    current_section_type: str | None = None  # 'tech', 'db', 'api'
    current_section_depth: int = 0
    current_section_lines: list[str] = []

    def _flush_story() -> None:
        nonlocal current_story_title, current_story_lines
        if current_story_title is None:
            return
        body = "\n".join(current_story_lines).strip()
        epic = current_epic if current_epic is not None else _get_or_create_general(epics)
        epic.stories.append(
            Story(
                title=current_story_title,
                acceptance_criteria=body,
                phase_hint=epic.name,
            )
        )
        current_story_title = None
        current_story_lines = []

    def _flush_section() -> None:
        nonlocal current_section_type, current_section_lines
        nonlocal tech_stack_raw, database_tables_raw, api_endpoints_raw
        if current_section_type is None:
            return
        content = "\n".join(current_section_lines).strip()
        if current_section_type == "tech":
            tech_stack_raw = content
        elif current_section_type == "db":
            database_tables_raw = content
        elif current_section_type == "api":
            api_endpoints_raw = content
        current_section_type = None
        current_section_lines = []

    for line in lines:
        m = _HEADING_RE.match(line)
        if m:
            depth = len(m.group(1))
            heading_text = m.group(2).strip()

            # If we're in a tech section, check if this heading ends it
            if current_section_type is not None:
                if depth <= current_section_depth:
                    _flush_section()
                else:
                    # Subheading inside tech section — accumulate
                    current_section_lines.append(line)
                    continue

            # Check if this is a tech/arch heading
            section_type = _is_tech_section(heading_text)
            if section_type:
                _flush_story()
                current_section_type = section_type
                current_section_depth = depth
                current_section_lines = []
                continue

            # Regular heading — process as epic/story
            if depth == 1:
                # H1 → project name only (first H1 in first file); not an epic
                _flush_story()
                if not first_h1_seen and is_first_file:
                    project_name = heading_text
                first_h1_seen = True
                # H1 does NOT create an epic; reset current epic to None
                current_epic = None
            elif depth == 2:
                # H2 → new epic
                _flush_story()
                current_epic = Epic(name=heading_text)
                epics.append(current_epic)
                current_story_title = None
                current_story_lines = []
            elif depth == 3:
                # H3 → story under current epic (or General if no epic yet)
                _flush_story()
                current_story_title = heading_text
                current_story_lines = []
            # depth >= 4 inside a story → treat as story body line
            elif current_story_title is not None:
                current_story_lines.append(line)
        else:
            # Non-heading line
            if current_section_type is not None:
                current_section_lines.append(line)
            elif current_story_title is not None:
                current_story_lines.append(line)
            elif is_first_file and not overview_found and line.strip():
                # First non-empty, non-heading line in first file → overview
                overview = line.strip()
                overview_found = True

    # Flush any open state
    _flush_story()
    _flush_section()

    return project_name, overview, epics, tech_stack_raw, database_tables_raw, api_endpoints_raw


def _get_or_create_general(epics: list[Epic]) -> Epic:
    """Return the General synthetic epic, creating it if needed."""
    for e in epics:
        if e.name == "General":
            return e
    general = Epic(name="General")
    epics.append(general)
    return general
