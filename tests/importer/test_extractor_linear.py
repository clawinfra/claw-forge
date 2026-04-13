from __future__ import annotations

import json
import tempfile
from pathlib import Path

from claw_forge.importer.detector import FormatResult
from claw_forge.importer.extractors.linear import extract_linear

FIXTURE = Path(__file__).parent / "fixtures" / "linear" / "issues.json"


def _make_result(json_path: Path) -> FormatResult:
    return FormatResult(
        format="linear",
        confidence="high",
        artifacts=[json_path],
    )


def test_project_name():
    spec = extract_linear(_make_result(FIXTURE))
    assert spec.project_name == "TaskTracker"


def test_overview():
    spec = extract_linear(_make_result(FIXTURE))
    assert spec.overview == "A task management app for small teams."


def test_epic_count():
    spec = extract_linear(_make_result(FIXTURE))
    # Authentication, Task Management, General
    assert spec.epic_count == 3


def test_story_count():
    spec = extract_linear(_make_result(FIXTURE))
    assert spec.story_count == 4


def test_authentication_stories():
    spec = extract_linear(_make_result(FIXTURE))
    auth_epic = next(e for e in spec.epics if e.name == "Authentication")
    assert len(auth_epic.stories) == 2
    titles = [s.title for s in auth_epic.stories]
    assert "User Registration" in titles
    assert "User Login" in titles


def test_general_epic():
    spec = extract_linear(_make_result(FIXTURE))
    general_epic = next(e for e in spec.epics if e.name == "General")
    assert len(general_epic.stories) == 1
    assert general_epic.stories[0].title == "Unlabelled story"


def test_story_acceptance_criteria():
    spec = extract_linear(_make_result(FIXTURE))
    auth_epic = next(e for e in spec.epics if e.name == "Authentication")
    reg_story = next(s for s in auth_epic.stories if s.title == "User Registration")
    assert "email" in reg_story.acceptance_criteria.lower()


def test_phase_hint():
    spec = extract_linear(_make_result(FIXTURE))
    all_stories = [s for e in spec.epics for s in e.stories]
    assert all(s.phase_hint != "" for s in all_stories)
    assert any(s.phase_hint == "Authentication" for s in all_stories)


def test_tech_stack_empty():
    spec = extract_linear(_make_result(FIXTURE))
    assert spec.tech_stack_raw == ""
    assert spec.database_tables_raw == ""
    assert spec.api_endpoints_raw == ""


def test_source_format():
    spec = extract_linear(_make_result(FIXTURE))
    assert spec.source_format == "linear"


def test_missing_project_key():
    data = {
        "issues": [
            {
                "identifier": "X-1",
                "title": "Some issue",
                "description": "desc",
                "state": "Todo",
                "labels": [],
            }
        ]
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "issues.json"
        json_path.write_text(json.dumps(data), encoding="utf-8")
        spec = extract_linear(_make_result(json_path))
    assert spec.project_name == "Unnamed Project"
    assert spec.overview == ""


def test_no_labels_goes_to_general():
    spec = extract_linear(_make_result(FIXTURE))
    epic_names = [e.name for e in spec.epics]
    assert "General" in epic_names
    general_epic = next(e for e in spec.epics if e.name == "General")
    titles = [s.title for s in general_epic.stories]
    assert "Unlabelled story" in titles
