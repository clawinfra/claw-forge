"""Tests for claw_forge.importer public API."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from claw_forge.importer import extract, import_spec
from claw_forge.importer.converter import ConvertedSections
from claw_forge.importer.detector import FormatResult

FIXTURES = Path(__file__).parent / "fixtures"
BMAD_FIXTURE = FIXTURES / "bmad"
LINEAR_FIXTURE = FIXTURES / "linear" / "issues.json"


def test_extract_dispatch_bmad():
    result = FormatResult(
        format="bmad",
        confidence="high",
        artifacts=list(BMAD_FIXTURE.rglob("*.md")),
        summary="BMAD output",
    )
    spec = extract(result)
    assert spec.source_format == "bmad"


def test_extract_dispatch_linear():
    result = FormatResult(
        format="linear",
        confidence="high",
        artifacts=[LINEAR_FIXTURE],
        summary="Linear export",
    )
    spec = extract(result)
    assert spec.source_format == "linear"


def test_import_spec_raises_on_empty(tmp_path: Path):
    """import_spec raises ValueError when no stories are extracted."""
    # Create a minimal BMAD-like fixture with no stories
    empty_prd = tmp_path / "prd.md"
    empty_prd.write_text("# EmptyProject\n## Project Overview\nNo stories here.\n")

    dummy_sections = ConvertedSections(
        overview="<overview/>",
        technology_stack="<technology_stack/>",
        prerequisites="<prerequisites/>",
        core_features="",
        database_schema="<database_schema/>",
        api_endpoints="<api_endpoints_summary/>",
        implementation_steps="<implementation_steps/>",
        success_criteria="<success_criteria/>",
        ui_layout="<ui_layout/>",
    )

    with patch("claw_forge.importer.convert", return_value=dummy_sections), \
            pytest.raises(ValueError, match="No features extracted"):
        import_spec(
            path=tmp_path,
            project_dir=tmp_path,
            api_key="test-key",
        )
