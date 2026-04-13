from __future__ import annotations

from pathlib import Path

import pytest

from claw_forge.importer.detector import FormatResult
from claw_forge.importer.extractors.generic import extract_generic

FIXTURE = Path(__file__).parent / "fixtures" / "generic" / "spec.md"


def _make_result(paths: list[Path]) -> FormatResult:
    return FormatResult(
        format="generic",
        confidence="low",
        artifacts=paths,
    )


@pytest.fixture
def spec():
    return extract_generic(_make_result([FIXTURE]))


def test_project_name():
    spec = extract_generic(_make_result([FIXTURE]))
    assert spec.project_name == "TaskTracker"


def test_overview():
    spec = extract_generic(_make_result([FIXTURE]))
    assert spec.overview == "A task management app for small teams."


def test_epic_count():
    # "Tech Stack" is NOT an epic; Authentication and Task Management are
    spec = extract_generic(_make_result([FIXTURE]))
    assert spec.epic_count == 2


def test_story_count():
    # User Registration, User Login (under Authentication) + Create Task (under Task Management)
    spec = extract_generic(_make_result([FIXTURE]))
    assert spec.story_count == 3


def test_stories_in_epic():
    spec = extract_generic(_make_result([FIXTURE]))
    auth_epic = next(e for e in spec.epics if e.name == "Authentication")
    titles = [s.title for s in auth_epic.stories]
    assert "User Registration" in titles
    assert "User Login" in titles
    assert len(auth_epic.stories) == 2


def test_phase_hint(spec):
    epic_names = {e.name for e in spec.epics}
    all_stories = [s for e in spec.epics for s in e.stories]
    assert all_stories, "expected at least one story"
    assert all(s.phase_hint in epic_names for s in all_stories)


def test_tech_stack_extracted():
    spec = extract_generic(_make_result([FIXTURE]))
    assert spec.tech_stack_raw != ""
    assert "Python" in spec.tech_stack_raw or "FastAPI" in spec.tech_stack_raw


def test_source_format():
    spec = extract_generic(_make_result([FIXTURE]))
    assert spec.source_format == "generic"


def test_empty_artifacts():
    spec = extract_generic(_make_result([]))
    assert spec.project_name == "Unnamed Project"
    assert spec.epic_count == 0
    assert spec.story_count == 0
    assert spec.epics == []


def test_no_headings_file(tmp_path: Path):
    md_file = tmp_path / "flat.md"
    md_file.write_text(
        "This file has no headings at all.\nJust plain text paragraphs.\n",
        encoding="utf-8",
    )
    spec = extract_generic(_make_result([md_file]))
    assert spec.story_count == 0
    assert spec.epic_count == 0
