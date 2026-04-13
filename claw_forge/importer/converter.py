"""Convert an ExtractedSpec into XML section strings via Claude."""
from __future__ import annotations

from dataclasses import dataclass

import anthropic

from claw_forge.importer.extractors.base import ExtractedSpec


@dataclass
class ConvertedSections:
    overview: str           # <overview>...</overview>
    technology_stack: str   # <technology_stack>...</technology_stack>
    prerequisites: str      # <prerequisites>...</prerequisites>
    core_features: str      # one or more <category name="...">...</category> blocks
    database_schema: str    # <database_schema>...</database_schema>
    api_endpoints: str      # <api_endpoints_summary>...</api_endpoints_summary>
    implementation_steps: str  # <implementation_steps>...</implementation_steps>
    success_criteria: str   # <success_criteria>...</success_criteria>
    ui_layout: str          # <ui_layout>...</ui_layout>


def _call_claude(
    client: anthropic.Anthropic,
    model: str,
    system: str,
    user: str,
) -> str:
    """Call Claude with one retry on failure. Returns response text."""
    try:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text
    except Exception:
        # One retry
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text


def convert(
    spec: ExtractedSpec,
    api_key: str,
    model: str = "claude-opus-4-6",
) -> ConvertedSections:
    """Convert an ExtractedSpec into XML sections via Claude. One call per section group."""
    client = anthropic.Anthropic(api_key=api_key)

    # -------------------------------------------------------------------------
    # Call 1 — overview + tech stack + prerequisites
    # -------------------------------------------------------------------------
    call1_system = (
        "Output only the three XML sections requested. "
        "No surrounding prose. Write in clear technical English."
    )
    call1_user = (
        f"Project overview:\n{spec.overview}\n\n"
        f"Tech stack:\n{spec.tech_stack_raw}\n\n"
        "Produce exactly these three XML sections:\n"
        "1. <overview>...</overview>\n"
        "2. <technology_stack>...</technology_stack>\n"
        "3. <prerequisites>...</prerequisites>"
    )
    call1_text = _call_claude(client, model, call1_system, call1_user)

    overview = _extract_tag(call1_text, "overview")
    technology_stack = _extract_tag(call1_text, "technology_stack")
    prerequisites = _extract_tag(call1_text, "prerequisites")

    # -------------------------------------------------------------------------
    # Call 2 — one call per epic → core_features
    # -------------------------------------------------------------------------
    call2_system = (
        "Output only a single <category name='...'>...</category> XML block. "
        "Write bullets as action-verb sentences: 'User can…', 'System returns…', "
        "'API validates…'. One testable behaviour per bullet. "
        "Use &amp; for & in XML content."
    )
    category_blocks: list[str] = []
    for epic in spec.epics:
        stories_text = "\n".join(
            f"- {story.title}: {story.acceptance_criteria}"
            for story in epic.stories
        )
        call2_user = (
            f"Epic name: {epic.name}\n\n"
            f"Stories:\n{stories_text}\n\n"
            f"Produce a single <category name=\"{epic.name}\"> XML block "
            "with 8-15 bullet items describing testable behaviours."
        )
        block_text = _call_claude(client, model, call2_system, call2_user)
        category_blocks.append(block_text.strip())

    core_features = "\n".join(category_blocks)

    # -------------------------------------------------------------------------
    # Call 3 — database schema + API endpoints
    # -------------------------------------------------------------------------
    call3_system = "Output only the two XML sections requested."
    call3_user = (
        f"Database tables:\n{spec.database_tables_raw}\n\n"
        f"API endpoints:\n{spec.api_endpoints_raw}\n\n"
        "Produce exactly these two XML sections:\n"
        "1. <database_schema>...</database_schema>\n"
        "2. <api_endpoints_summary>...</api_endpoints_summary>"
    )
    call3_text = _call_claude(client, model, call3_system, call3_user)

    database_schema = _extract_tag(call3_text, "database_schema")
    api_endpoints = _extract_tag(call3_text, "api_endpoints_summary")

    # -------------------------------------------------------------------------
    # Call 4 — implementation steps + success criteria + UI layout
    # -------------------------------------------------------------------------
    call4_system = "Output only the three XML sections requested."
    epic_summary = "\n".join(
        f"- {epic.name} ({len(epic.stories)} stories)" for epic in spec.epics
    )
    call4_user = (
        f"Project name: {spec.project_name}\n\n"
        f"Epics:\n{epic_summary}\n\n"
        "Produce exactly these three XML sections:\n"
        "1. <implementation_steps>...</implementation_steps>\n"
        "2. <success_criteria>...</success_criteria>\n"
        "3. <ui_layout>...</ui_layout>"
    )
    call4_text = _call_claude(client, model, call4_system, call4_user)

    implementation_steps = _extract_tag(call4_text, "implementation_steps")
    success_criteria = _extract_tag(call4_text, "success_criteria")
    ui_layout = _extract_tag(call4_text, "ui_layout")

    return ConvertedSections(
        overview=overview,
        technology_stack=technology_stack,
        prerequisites=prerequisites,
        core_features=core_features,
        database_schema=database_schema,
        api_endpoints=api_endpoints,
        implementation_steps=implementation_steps,
        success_criteria=success_criteria,
        ui_layout=ui_layout,
    )


def _extract_tag(text: str, tag: str) -> str:
    """Extract the content of the first matching XML tag including the tags themselves.

    Returns the full ``<tag>...</tag>`` string, or the entire response text if the
    opening tag is not found (preserves whatever Claude returned).
    """
    open_tag = f"<{tag}>"
    close_tag = f"</{tag}>"
    start = text.find(open_tag)
    if start == -1:
        return text.strip()
    end = text.find(close_tag, start)
    if end == -1:
        return text[start:].strip()
    return text[start : end + len(close_tag)].strip()
