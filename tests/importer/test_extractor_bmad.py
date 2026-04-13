from __future__ import annotations

from pathlib import Path

from claw_forge.importer.detector import detect
from claw_forge.importer.extractors.bmad import extract_bmad

FIXTURE = Path(__file__).parent / "fixtures" / "bmad"


def test_extract_bmad_project_name():
    result = detect(FIXTURE)
    spec = extract_bmad(result)
    assert spec.project_name == "TaskTracker"


def test_extract_bmad_overview():
    result = detect(FIXTURE)
    spec = extract_bmad(result)
    assert "task management" in spec.overview.lower()


def test_extract_bmad_epics():
    result = detect(FIXTURE)
    spec = extract_bmad(result)
    assert spec.epic_count == 2
    epic_names = [e.name for e in spec.epics]
    assert "Authentication" in epic_names
    assert "Task Management" in epic_names


def test_extract_bmad_stories():
    result = detect(FIXTURE)
    spec = extract_bmad(result)
    assert spec.story_count == 3
    auth_epic = next(e for e in spec.epics if e.name == "Authentication")
    assert len(auth_epic.stories) == 2


def test_extract_bmad_story_titles():
    result = detect(FIXTURE)
    spec = extract_bmad(result)
    auth_epic = next(e for e in spec.epics if e.name == "Authentication")
    titles = [s.title for s in auth_epic.stories]
    assert "User Registration" in titles
    assert "User Login" in titles


def test_extract_bmad_acceptance_criteria_not_empty():
    result = detect(FIXTURE)
    spec = extract_bmad(result)
    for epic in spec.epics:
        for story in epic.stories:
            assert story.acceptance_criteria.strip()


def test_extract_bmad_tech_stack():
    result = detect(FIXTURE)
    spec = extract_bmad(result)
    assert "FastAPI" in spec.tech_stack_raw


def test_extract_bmad_database_raw():
    result = detect(FIXTURE)
    spec = extract_bmad(result)
    assert "users" in spec.database_tables_raw.lower()


def test_extract_bmad_api_endpoints():
    result = detect(FIXTURE)
    spec = extract_bmad(result)
    assert "/api/auth" in spec.api_endpoints_raw


def test_extract_bmad_source_format():
    result = detect(FIXTURE)
    spec = extract_bmad(result)
    assert spec.source_format == "bmad"
