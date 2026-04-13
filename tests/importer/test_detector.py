from __future__ import annotations

from pathlib import Path

from claw_forge.importer.detector import FormatResult
from claw_forge.importer.extractors.base import Epic, ExtractedSpec, Story


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
