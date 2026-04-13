"""Tests for the Jira XML and CSV extractor."""
from __future__ import annotations

import tempfile
from pathlib import Path

from claw_forge.importer.detector import FormatResult
from claw_forge.importer.extractors.jira import extract_jira

XML_FIXTURE = Path(__file__).parent / "fixtures" / "jira" / "export.xml"
CSV_FIXTURE = Path(__file__).parent / "fixtures" / "jira" / "export.csv"


def _make_result(artifact: Path) -> FormatResult:
    return FormatResult(
        format="jira",
        confidence="high",
        artifacts=[artifact],
    )


# ---------------------------------------------------------------------------
# XML tests
# ---------------------------------------------------------------------------


def test_xml_project_name():
    spec = extract_jira(_make_result(XML_FIXTURE))
    assert spec.project_name == "TaskTracker"


def test_xml_epic_count():
    spec = extract_jira(_make_result(XML_FIXTURE))
    # Authentication, Task Management
    assert spec.epic_count == 2


def test_xml_story_count():
    spec = extract_jira(_make_result(XML_FIXTURE))
    assert spec.story_count == 2


def test_xml_authentication_stories():
    spec = extract_jira(_make_result(XML_FIXTURE))
    auth_epic = next(e for e in spec.epics if e.name == "Authentication")
    assert len(auth_epic.stories) == 1
    assert auth_epic.stories[0].title == "User Registration"


def test_xml_phase_hint():
    spec = extract_jira(_make_result(XML_FIXTURE))
    all_stories = [s for e in spec.epics for s in e.stories]
    assert all(s.phase_hint != "" for s in all_stories)


def test_xml_source_format():
    spec = extract_jira(_make_result(XML_FIXTURE))
    assert spec.source_format == "jira"


def test_xml_tech_stack_empty():
    spec = extract_jira(_make_result(XML_FIXTURE))
    assert spec.tech_stack_raw == ""
    assert spec.database_tables_raw == ""
    assert spec.api_endpoints_raw == ""


def test_malformed_xml():
    with tempfile.TemporaryDirectory() as tmpdir:
        bad_xml = Path(tmpdir) / "export.xml"
        bad_xml.write_text("<<not valid xml>>", encoding="utf-8")
        spec = extract_jira(_make_result(bad_xml))
    assert spec.project_name == "Unnamed Project"
    assert spec.story_count == 0
    assert spec.epics == []


# ---------------------------------------------------------------------------
# CSV tests
# ---------------------------------------------------------------------------


def test_csv_story_count():
    spec = extract_jira(_make_result(CSV_FIXTURE))
    assert spec.story_count == 3


def test_csv_epic_grouping():
    spec = extract_jira(_make_result(CSV_FIXTURE))
    epic_names = [e.name for e in spec.epics]
    assert "Authentication" in epic_names
    assert "Task Management" in epic_names


def test_csv_project_name_unnamed():
    spec = extract_jira(_make_result(CSV_FIXTURE))
    assert spec.project_name == "Unnamed Project"


def test_csv_phase_hint():
    spec = extract_jira(_make_result(CSV_FIXTURE))
    all_stories = [s for e in spec.epics for s in e.stories]
    assert all(s.phase_hint != "" for s in all_stories)


def test_csv_source_format():
    spec = extract_jira(_make_result(CSV_FIXTURE))
    assert spec.source_format == "jira"


def test_csv_project_name_from_column(tmp_path: Path):
    csv_file = tmp_path / "export.csv"
    csv_file.write_text(
        "Issue key,Summary,Description,Epic Link,Project\n"
        "TT-1,A story,Some criteria,Authentication,MyProject\n",
        encoding="utf-8",
    )
    spec = extract_jira(_make_result(csv_file))
    assert spec.project_name == "MyProject"
