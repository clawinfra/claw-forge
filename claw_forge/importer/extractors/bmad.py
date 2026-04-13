"""BMAD extractor — reads prd.md, architecture.md, stories/**/*.md."""
from __future__ import annotations

import re
from pathlib import Path

from claw_forge.importer.detector import FormatResult
from claw_forge.importer.extractors.base import Epic, ExtractedSpec, Story


def extract_bmad(result: FormatResult) -> ExtractedSpec:
    """Extract structure from BMAD artifacts into an ExtractedSpec."""
    prd_path = next((p for p in result.artifacts if p.name == "prd.md"), None)
    arch_path = next((p for p in result.artifacts if p.name == "architecture.md"), None)
    story_paths = sorted(p for p in result.artifacts if "stories" in str(p) and p.suffix == ".md")

    project_name, overview, prd_epics = _parse_prd(prd_path)
    tech_stack_raw, database_tables_raw, api_endpoints_raw = _parse_architecture(arch_path)
    epics = _parse_stories(story_paths, prd_epics)

    story_count = sum(len(e.stories) for e in epics)
    if prd_path:
        source_path = prd_path.parent
    elif result.artifacts:
        source_path = result.artifacts[0].parent
    else:
        source_path = Path(".")

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
        source_format="bmad",
        source_path=source_path,
        epic_count=len(epics),
        story_count=story_count,
    )


def _parse_prd(prd_path: Path | None) -> tuple[str, str, dict[int, str]]:
    """Return (project_name, overview, epic_index_map) from prd.md.

    epic_index_map maps epic number (1-based) to epic name, e.g. {1: "Authentication"}.
    """
    if prd_path is None or not prd_path.exists():
        return "Unnamed Project", "", {}

    text = prd_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    project_name = "Unnamed Project"
    for line in lines:
        if line.startswith("# ") and not line.startswith("## "):
            raw = line.lstrip("# ").strip()
            # Strip common suffixes like " PRD", " Product Requirements Document"
            project_name = re.sub(r"\s+PRD$", "", raw, flags=re.IGNORECASE).strip()
            break

    overview = ""
    in_overview = False
    for line in lines:
        if re.match(r"^## Overview", line, re.IGNORECASE):
            in_overview = True
            continue
        if in_overview:
            if line.startswith("#"):
                break
            if line.strip():
                overview += line.strip() + " "

    if not overview:
        for line in lines:
            if line.strip() and not line.startswith("#"):
                overview = line.strip()
                break

    # Parse epic names: "### Epic 1: Authentication" → {1: "Authentication"}
    epic_map: dict[int, str] = {}
    for line in lines:
        m = re.match(r"^#{1,4}\s+Epic\s+(\d+)[:\s]+(.+)", line, re.IGNORECASE)
        if m:
            epic_map[int(m.group(1))] = m.group(2).strip()

    return project_name, overview.strip(), epic_map


def _parse_architecture(arch_path: Path | None) -> tuple[str, str, str]:
    """Return (tech_stack_raw, database_tables_raw, api_endpoints_raw)."""
    if arch_path is None or not arch_path.exists():
        return "", "", ""

    text = arch_path.read_text(encoding="utf-8")
    tech_stack_raw = _extract_section(text, ["Tech Stack", "Technology Stack", "Stack"])
    database_tables_raw = _extract_section(text, ["Database Schema", "Database", "Schema"])
    api_endpoints_raw = _extract_section(text, ["API Endpoints", "API", "Endpoints"])

    return tech_stack_raw, database_tables_raw, api_endpoints_raw


def _extract_section(text: str, headings: list[str]) -> str:
    """Extract text under the first matching H2/H3 heading."""
    lines = text.splitlines()
    in_section = False
    collected: list[str] = []

    for line in lines:
        stripped = line.lstrip("#").strip()
        if line.startswith("#") and any(h.lower() in stripped.lower() for h in headings):
            in_section = True
            continue
        if in_section:
            if line.startswith("## ") or line.startswith("### "):
                break
            collected.append(line)

    return "\n".join(collected).strip()


def _parse_stories(story_paths: list[Path], prd_epics: dict[int, str]) -> list[Epic]:
    """Group story files into Epics by their parent directory name."""
    epic_map: dict[str, list[Story]] = {}

    for path in story_paths:
        epic_dir = path.parent.name
        epic_name = _dir_to_epic_name(epic_dir, prd_epics)
        title, criteria = _parse_story_file(path)
        story = Story(title=title, acceptance_criteria=criteria, phase_hint=epic_name)
        epic_map.setdefault(epic_name, []).append(story)

    return [Epic(name=name, stories=stories) for name, stories in epic_map.items()]


def _dir_to_epic_name(dir_name: str, prd_epics: dict[int, str]) -> str:
    """Map a directory name like 'epic-1-auth' to a canonical epic name.

    If prd_epics contains a matching epic number, use that name.
    Otherwise fall back to capitalizing the slug parts.
    """
    m = re.match(r"epic-(\d+)", dir_name, re.IGNORECASE)
    if m:
        epic_num = int(m.group(1))
        if epic_num in prd_epics:
            return prd_epics[epic_num]
    parts = dir_name.split("-")
    name_parts = [p for p in parts if p.lower() != "epic" and not p.isdigit()]
    return " ".join(p.capitalize() for p in name_parts)


def _parse_story_file(path: Path) -> tuple[str, str]:
    """Return (title, acceptance_criteria) from a story markdown file."""
    text = path.read_text(encoding="utf-8")
    title = path.stem.replace("-", " ").replace("_", " ").title()
    body = text

    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            frontmatter = text[3:end]
            body = text[end + 3:].strip()
            for line in frontmatter.splitlines():
                if line.lower().startswith("title:"):
                    title = line.split(":", 1)[1].strip().strip('"\'')
                    break

    if not title or title == path.stem:
        for line in body.splitlines():
            if line.startswith("#"):
                title = line.lstrip("#").strip()
                break

    return title, body.strip()
