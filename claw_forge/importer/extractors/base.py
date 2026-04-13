"""Shared dataclasses for the extraction → conversion pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Story:
    title: str
    acceptance_criteria: str  # raw text, may be Gherkin — converter rewrites
    phase_hint: str           # epic name or phase label from source tool


@dataclass
class Epic:
    name: str
    stories: list[Story] = field(default_factory=list)


@dataclass
class ExtractedSpec:
    # identity
    project_name: str
    overview: str

    # features
    epics: list[Epic]

    # tech context (empty string if format does not carry it)
    tech_stack_raw: str
    database_tables_raw: str
    api_endpoints_raw: str

    # brownfield context
    existing_context: dict[str, str]  # stack, test_baseline, conventions
    integration_points: list[str]
    constraints: list[str]

    # metadata
    source_format: str
    source_path: Path
    epic_count: int
    story_count: int
