from __future__ import annotations

from pathlib import Path

import pytest

from claw_forge.importer.detector import FormatResult, detect
from claw_forge.importer.extractors.base import Epic, ExtractedSpec, Story

FIXTURES = Path(__file__).parent / "fixtures"


def test_format_result_fields():
    fr = FormatResult(
        format="bmad",
        confidence="high",
        artifacts=[Path("prd.md")],
        summary="BMAD output with 2 epics",
    )
    assert fr.format == "bmad"
    assert fr.confidence == "high"
    assert len(fr.artifacts) == 1
    assert "2 epics" in fr.summary


def test_extracted_spec_counts():
    epics = [
        Epic(name="Auth", stories=[
            Story(title="Register", acceptance_criteria="user registers", phase_hint="Auth"),
            Story(title="Login", acceptance_criteria="user logs in", phase_hint="Auth"),
        ]),
        Epic(name="Tasks", stories=[
            Story(title="Create", acceptance_criteria="user creates task", phase_hint="Tasks"),
        ]),
    ]
    spec = ExtractedSpec(
        project_name="TestApp",
        overview="A test app.",
        epics=epics,
        tech_stack_raw="FastAPI + React",
        database_tables_raw="users, tasks",
        api_endpoints_raw="POST /auth/register",
        existing_context={},
        integration_points=[],
        constraints=[],
        source_format="bmad",
        source_path=Path("."),
        epic_count=2,
        story_count=3,
    )
    assert spec.epic_count == 2
    assert spec.story_count == 3
    assert len(spec.epics[0].stories) == 2


def test_detect_bmad(tmp_path):
    (tmp_path / "prd.md").write_text("# PRD")
    (tmp_path / "architecture.md").write_text("# Arch")
    result = detect(tmp_path)
    assert result.format == "bmad"
    assert result.confidence == "high"
    assert any(p.name == "prd.md" for p in result.artifacts)


def test_detect_bmad_stories_dir(tmp_path):
    stories = tmp_path / "stories" / "epic-1-auth"
    stories.mkdir(parents=True)
    (stories / "story-1.md").write_text("story")
    result = detect(tmp_path)
    assert result.format == "bmad"
    assert result.confidence == "high"


def test_detect_linear(tmp_path):
    (tmp_path / "issues.json").write_text(
        '{"issues": [{"identifier": "TT-1", "state": "Todo", "labels": []}], '
        '"project": {"name": "X", "description": "Y"}}'
    )
    result = detect(tmp_path)
    assert result.format == "linear"
    assert result.confidence == "high"


def test_detect_jira_xml(tmp_path):
    (tmp_path / "export.xml").write_text(
        '<?xml version="1.0"?><rss version="0.92"><channel></channel></rss>'
    )
    result = detect(tmp_path)
    assert result.format == "jira"
    assert result.confidence == "high"


def test_detect_jira_csv(tmp_path):
    (tmp_path / "export.csv").write_text(
        "Issue key,Summary,Description,Epic Link\nTT-1,foo,bar,Auth\n"
    )
    result = detect(tmp_path)
    assert result.format == "jira"
    assert result.confidence == "high"


def test_detect_generic_markdown(tmp_path):
    (tmp_path / "spec.md").write_text("# MyApp\n\n## Feature\nSome feature.")
    result = detect(tmp_path)
    assert result.format == "generic"
    assert result.confidence == "low"


def test_detect_fixture_bmad():
    result = detect(FIXTURES / "bmad")
    assert result.format == "bmad"
    assert result.confidence == "high"


def test_detect_fixture_linear():
    result = detect(FIXTURES / "linear")
    assert result.format == "linear"


def test_detect_fixture_jira_xml():
    result = detect(FIXTURES / "jira")
    assert result.format == "jira"


def test_detect_fixture_generic():
    result = detect(FIXTURES / "generic")
    assert result.format == "generic"


def test_detect_summary_contains_format():
    result = detect(FIXTURES / "bmad")
    assert result.summary


def test_detect_nonexistent_path_raises():
    with pytest.raises(FileNotFoundError):
        detect(Path("/nonexistent/path"))
