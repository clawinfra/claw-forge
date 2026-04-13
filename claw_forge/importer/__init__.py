"""claw-forge import pipeline — detect, extract, convert, write."""
from __future__ import annotations

from pathlib import Path

from claw_forge.importer.converter import ConvertedSections, convert
from claw_forge.importer.detector import FormatResult, detect
from claw_forge.importer.extractors.base import Epic, ExtractedSpec, Story
from claw_forge.importer.extractors.bmad import extract_bmad
from claw_forge.importer.extractors.generic import extract_generic
from claw_forge.importer.extractors.jira import extract_jira
from claw_forge.importer.extractors.linear import extract_linear
from claw_forge.importer.writer import write_spec

__all__ = [
    "ConvertedSections",
    "Epic",
    "ExtractedSpec",
    "FormatResult",
    "Story",
    "convert",
    "detect",
    "extract_bmad",
    "extract_generic",
    "extract_jira",
    "extract_linear",
    "import_spec",
    "write_spec",
]


def extract(result: FormatResult) -> ExtractedSpec:
    """Dispatch to the correct extractor based on format."""
    dispatch = {
        "bmad": extract_bmad,
        "linear": extract_linear,
        "jira": extract_jira,
        "generic": extract_generic,
    }
    return dispatch[result.format](result)


def import_spec(
    path: Path,
    project_dir: Path,
    api_key: str,
    model: str = "claude-opus-4-6",
    out: str = "",
) -> Path:
    """Full pipeline: detect → extract → convert → write. Returns output path."""
    result = detect(path)
    spec = extract(result)
    if spec.story_count == 0:
        raise ValueError("No features extracted — check export contains stories/issues")
    sections = convert(spec, api_key=api_key, model=model)
    return write_spec(sections, spec, project_dir, out=out)
