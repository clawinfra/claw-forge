"""Tests for claw_forge.importer.writer."""
from __future__ import annotations

from pathlib import Path

from claw_forge.importer.converter import ConvertedSections
from claw_forge.importer.extractors.base import Epic, ExtractedSpec, Story


def make_sections() -> ConvertedSections:
    return ConvertedSections(
        overview="<overview>Test overview</overview>",
        technology_stack="<technology_stack>Python</technology_stack>",
        prerequisites="<prerequisites>Docker</prerequisites>",
        core_features='<category name="Auth">• User can login</category>',
        database_schema="<database_schema>users</database_schema>",
        api_endpoints="<api_endpoints_summary>POST /login</api_endpoints_summary>",
        implementation_steps="<implementation_steps>Step 1</implementation_steps>",
        success_criteria="<success_criteria>All pass</success_criteria>",
        ui_layout="<ui_layout>SPA</ui_layout>",
    )


def make_greenfield_spec() -> ExtractedSpec:
    return ExtractedSpec(
        project_name="MyApp",
        overview="A test app",
        epics=[Epic(name="Auth", stories=[
            Story(title="Login", acceptance_criteria="User can login", phase_hint="Phase 1"),
        ])],
        tech_stack_raw="Python, FastAPI",
        database_tables_raw="users",
        api_endpoints_raw="POST /login",
        existing_context={},
        integration_points=[],
        constraints=[],
        source_format="generic",
        source_path=Path("spec.md"),
        epic_count=1,
        story_count=1,
    )


def make_brownfield_spec() -> ExtractedSpec:
    return ExtractedSpec(
        project_name="MyApp",
        overview="A test app",
        epics=[Epic(name="Auth", stories=[
            Story(title="Login", acceptance_criteria="User can login", phase_hint="Phase 1"),
        ])],
        tech_stack_raw="Python, FastAPI",
        database_tables_raw="users",
        api_endpoints_raw="POST /login",
        existing_context={"stack": "Django", "test_baseline": "pytest"},
        integration_points=["Auth service", "Payment gateway"],
        constraints=["No breaking API changes", "Must support Python 3.11"],
        source_format="generic",
        source_path=Path("spec.md"),
        epic_count=1,
        story_count=1,
    )


def test_greenfield_writes_app_spec_txt(tmp_path: Path) -> None:
    from claw_forge.importer.writer import write_spec

    result = write_spec(make_sections(), make_greenfield_spec(), tmp_path)

    assert result.name == "app_spec.txt"
    assert result.exists()


def test_brownfield_writes_additions_spec_xml(tmp_path: Path) -> None:
    from claw_forge.importer.writer import write_spec

    (tmp_path / "brownfield_manifest.json").write_text("{}")
    result = write_spec(make_sections(), make_brownfield_spec(), tmp_path)

    assert result.name == "additions_spec.xml"
    assert result.exists()


def test_greenfield_contains_project_name(tmp_path: Path) -> None:
    from claw_forge.importer.writer import write_spec

    result = write_spec(make_sections(), make_greenfield_spec(), tmp_path)
    content = result.read_text(encoding="utf-8")

    assert "MyApp" in content


def test_greenfield_contains_core_features(tmp_path: Path) -> None:
    from claw_forge.importer.writer import write_spec

    result = write_spec(make_sections(), make_greenfield_spec(), tmp_path)
    content = result.read_text(encoding="utf-8")

    assert "<core_features>" in content
    assert "</core_features>" in content
    assert "User can login" in content


def test_brownfield_contains_existing_context(tmp_path: Path) -> None:
    from claw_forge.importer.writer import write_spec

    (tmp_path / "brownfield_manifest.json").write_text("{}")
    spec = make_brownfield_spec()
    result = write_spec(make_sections(), spec, tmp_path)
    content = result.read_text(encoding="utf-8")

    assert "<existing_context>" in content
    assert "</existing_context>" in content
    assert "<stack>Django</stack>" in content
    assert "<test_baseline>pytest</test_baseline>" in content


def test_brownfield_contains_integration_points(tmp_path: Path) -> None:
    from claw_forge.importer.writer import write_spec

    (tmp_path / "brownfield_manifest.json").write_text("{}")
    spec = make_brownfield_spec()
    result = write_spec(make_sections(), spec, tmp_path)
    content = result.read_text(encoding="utf-8")

    assert "<integration_points>" in content
    assert "<point>Auth service</point>" in content
    assert "<point>Payment gateway</point>" in content


def test_out_param_overrides_filename(tmp_path: Path) -> None:
    from claw_forge.importer.writer import write_spec

    result = write_spec(make_sections(), make_greenfield_spec(), tmp_path, out="custom.xml")

    assert result.name == "custom.xml"
    assert result.exists()


def test_returns_written_path(tmp_path: Path) -> None:
    from claw_forge.importer.writer import write_spec

    result = write_spec(make_sections(), make_greenfield_spec(), tmp_path)

    assert isinstance(result, Path)
    assert result == tmp_path / "app_spec.txt"


def test_greenfield_root_element(tmp_path: Path) -> None:
    from claw_forge.importer.writer import write_spec

    result = write_spec(make_sections(), make_greenfield_spec(), tmp_path)
    content = result.read_text(encoding="utf-8")

    assert "<app_spec>" in content
    assert "</app_spec>" in content


def test_brownfield_root_element(tmp_path: Path) -> None:
    from claw_forge.importer.writer import write_spec

    (tmp_path / "brownfield_manifest.json").write_text("{}")
    result = write_spec(make_sections(), make_brownfield_spec(), tmp_path)
    content = result.read_text(encoding="utf-8")

    assert "<additions_spec>" in content
    assert "</additions_spec>" in content


def test_brownfield_contains_constraints(tmp_path: Path) -> None:
    from claw_forge.importer.writer import write_spec

    (tmp_path / "brownfield_manifest.json").write_text("{}")
    spec = make_brownfield_spec()
    result = write_spec(make_sections(), spec, tmp_path)
    content = result.read_text(encoding="utf-8")

    assert "<constraints>" in content
    assert "<constraint>No breaking API changes</constraint>" in content
    assert "<constraint>Must support Python 3.11</constraint>" in content


def test_empty_brownfield_collections(tmp_path: Path) -> None:
    """Empty integration_points and constraints render as empty wrapper elements."""
    from claw_forge.importer.writer import write_spec

    (tmp_path / "brownfield_manifest.json").write_text("{}")
    spec = make_brownfield_spec()
    spec.integration_points = []
    spec.constraints = []
    spec.existing_context = {}
    result = write_spec(make_sections(), spec, tmp_path)
    content = result.read_text(encoding="utf-8")

    assert "<integration_points>" in content
    assert "<constraints>" in content
    assert "<existing_context>" in content


def test_overwrite_existing_file(tmp_path: Path) -> None:
    """Writer overwrites an existing file without error."""
    from claw_forge.importer.writer import write_spec

    out_file = tmp_path / "app_spec.txt"
    out_file.write_text("old content", encoding="utf-8")

    result = write_spec(make_sections(), make_greenfield_spec(), tmp_path)
    content = result.read_text(encoding="utf-8")

    assert "old content" not in content
    assert "<app_spec>" in content
