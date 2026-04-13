"""Write app_spec.txt (greenfield) or additions_spec.xml (brownfield) from ConvertedSections."""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

from claw_forge.importer.converter import ConvertedSections
from claw_forge.importer.extractors.base import ExtractedSpec

_BROWNFIELD_MANIFEST = "brownfield_manifest.json"


def write_spec(
    sections: ConvertedSections,
    spec: ExtractedSpec,
    project_dir: Path,
    out: str = "",
) -> Path:
    """Write app_spec.txt (greenfield) or additions_spec.xml (brownfield).

    Returns the path of the written file.
    """
    is_brownfield = (project_dir / _BROWNFIELD_MANIFEST).exists()

    if out:
        filename = out
    elif is_brownfield:
        filename = "additions_spec.xml"
    else:
        filename = "app_spec.txt"

    if is_brownfield:
        content = _assemble_brownfield(sections, spec)
    else:
        content = _assemble_greenfield(sections, spec)

    out_path = project_dir / filename
    out_path.write_text(content, encoding="utf-8")
    return out_path


def _assemble_greenfield(sections: ConvertedSections, spec: ExtractedSpec) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<app_spec>\n"
        f"  <project_name>{spec.project_name}</project_name>\n"
        f"  {sections.overview}\n"
        f"  {sections.technology_stack}\n"
        f"  {sections.prerequisites}\n"
        "  <core_features>\n"
        f"    {sections.core_features}\n"
        "  </core_features>\n"
        f"  {sections.database_schema}\n"
        f"  {sections.api_endpoints}\n"
        f"  {sections.implementation_steps}\n"
        f"  {sections.success_criteria}\n"
        f"  {sections.ui_layout}\n"
        "</app_spec>\n"
    )


def _assemble_brownfield(sections: ConvertedSections, spec: ExtractedSpec) -> str:
    existing_context_xml = "\n    ".join(
        f"<{key}>{_xml_escape(value)}</{key}>" for key, value in spec.existing_context.items()
    )
    integration_points_xml = "\n    ".join(
        f"<point>{_xml_escape(item)}</point>" for item in spec.integration_points
    )
    constraints_xml = "\n    ".join(
        f"<constraint>{_xml_escape(item)}</constraint>" for item in spec.constraints
    )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<additions_spec>\n"
        "  <existing_context>\n"
        f"    {existing_context_xml}\n"
        "  </existing_context>\n"
        "  <features_to_add>\n"
        "    <core_features>\n"
        f"      {sections.core_features}\n"
        "    </core_features>\n"
        f"    {sections.database_schema}\n"
        f"    {sections.api_endpoints}\n"
        "  </features_to_add>\n"
        "  <integration_points>\n"
        f"    {integration_points_xml}\n"
        "  </integration_points>\n"
        "  <constraints>\n"
        f"    {constraints_xml}\n"
        "  </constraints>\n"
        f"  {sections.implementation_steps}\n"
        f"  {sections.success_criteria}\n"
        "</additions_spec>\n"
    )
