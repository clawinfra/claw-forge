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
    assert "Python" in spec.tech_stack_raw
    assert "FastAPI" in spec.tech_stack_raw


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


def test_oserror_artifact_skipped(tmp_path: Path):
    """An artifact that raises OSError is silently skipped."""
    missing = tmp_path / "nonexistent.md"
    # Do NOT create the file — read_text will raise OSError
    spec = extract_generic(_make_result([missing]))
    assert spec.story_count == 0
    assert spec.epic_count == 0


def test_database_section_extracted(tmp_path: Path):
    """A ## Database Schema section populates database_tables_raw."""
    md_file = tmp_path / "spec.md"
    md_file.write_text(
        "# MyApp\n\n"
        "## Database Schema\nusers table\nposts table\n\n"
        "## Features\n\n### Create Post\nUser can create a post.\n",
        encoding="utf-8",
    )
    spec = extract_generic(_make_result([md_file]))
    assert "users table" in spec.database_tables_raw


def test_api_section_extracted(tmp_path: Path):
    """A ## API Endpoints section populates api_endpoints_raw."""
    md_file = tmp_path / "spec.md"
    md_file.write_text(
        "# MyApp\n\n"
        "## API Endpoints\nGET /users\nPOST /users\n\n"
        "## Features\n\n### List Users\nUser can list users.\n",
        encoding="utf-8",
    )
    spec = extract_generic(_make_result([md_file]))
    assert "GET /users" in spec.api_endpoints_raw


def test_subheading_inside_tech_section(tmp_path: Path):
    """Subheadings inside a tech section are accumulated as part of the section content."""
    md_file = tmp_path / "spec.md"
    md_file.write_text(
        "# MyApp\n\n"
        "## Tech Stack\nMain stack info.\n### Frontend\nReact\n### Backend\nFastAPI\n\n"
        "## Features\n\n### Login\nUser logs in.\n",
        encoding="utf-8",
    )
    spec = extract_generic(_make_result([md_file]))
    assert "React" in spec.tech_stack_raw
    assert "FastAPI" in spec.tech_stack_raw


def test_story_without_epic_goes_to_general(tmp_path: Path):
    """H3 story before any H2 epic is placed into a synthetic 'General' epic."""
    md_file = tmp_path / "spec.md"
    md_file.write_text(
        "# MyApp\n\nOverview line.\n\n### Orphan Story\nThis story has no parent epic.\n",
        encoding="utf-8",
    )
    spec = extract_generic(_make_result([md_file]))
    assert spec.story_count == 1
    assert spec.epics[0].name == "General"


def test_second_file_tech_not_overwritten(tmp_path: Path):
    """Tech section from the first file is not overwritten by a later file."""
    first = tmp_path / "a.md"
    second = tmp_path / "b.md"
    first.write_text("# First\n\n## Tech Stack\nPython\n\n## Feats\n\n### Story A\ndesc\n")
    second.write_text("# Second\n\n## Tech Stack\nJava\n\n## Feats\n\n### Story B\ndesc\n")
    spec = extract_generic(_make_result([first, second]))
    assert "Python" in spec.tech_stack_raw
    assert "Java" not in spec.tech_stack_raw
