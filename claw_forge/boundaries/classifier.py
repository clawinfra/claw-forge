"""Subagent that classifies a hotspot's refactor pattern.

Reads the first ~200 lines of the file plus the audit signals, asks the
agent to choose ONE of the four canonical refactor patterns, and stamps
the chosen label onto the ``Hotspot``.  The classifier never modifies
files — it just labels.

Patterns:
- ``registry`` : long if/match dispatch on a string key → extract one file per case
- ``split`` : multiple unrelated domains in one file → split by domain
- ``extract_collaborators`` : god-class with many responsibilities → extract helpers
- ``route_table`` : hardcoded route/handler list → introduce route registry

Failure modes are handled silently: agent error or unknown pattern leaves
``Hotspot.pattern`` empty, which the apply phase treats as "user must
decide manually".
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from claw_forge.agent.runner import collect_structured_result
from claw_forge.boundaries.scorer import Hotspot

_VALID_PATTERNS: frozenset[str] = frozenset({
    "registry", "split", "extract_collaborators", "route_table",
})

_PROMPT_TEMPLATE = """\
You are auditing a code file to determine the cleanest refactor pattern.

File: {path}
Lines: {lines}
Signals:
- dispatch chains: {dispatch}
- imports: {imports}
- churn: {churn}
- function refs: {functions}

File contents (first 200 lines):
{content}

Choose ONE of these patterns:
- "registry"  : long if/match dispatch on a string key → extract one file per case
- "split"     : multiple unrelated domains in one file → split by domain
- "extract_collaborators" : god-class with many responsibilities → extract helpers
- "route_table" : hardcoded route/handler list → introduce route registry

Return JSON only.  Schema:
  {{"pattern": "<one of the four>", "rationale": "<one sentence>"}}
"""

_OUTPUT_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "boundary_pattern",
        "schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "enum": list(_VALID_PATTERNS),
                },
                "rationale": {"type": "string"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
}


async def _invoke_classifier_subagent(prompt: str) -> dict[str, Any]:
    """Run the classifier subagent with a structured-output schema."""
    result = await collect_structured_result(
        prompt, output_format=_OUTPUT_FORMAT,
    )
    return result or {}


def classify_hotspot(hotspot: Hotspot, *, project_dir: Path) -> Hotspot:
    """Run the classifier subagent and stamp ``pattern`` onto the hotspot.

    Best-effort: any subagent error or invalid pattern leaves ``pattern``
    empty.  The caller should treat empty pattern as "user must decide".
    """
    target = project_dir / hotspot.path
    try:
        content = target.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return hotspot
    head = "\n".join(content[:200])
    prompt = _PROMPT_TEMPLATE.format(
        path=hotspot.path,
        lines=len(content),
        dispatch=hotspot.signals.get("dispatch", 0),
        imports=hotspot.signals.get("import", 0),
        churn=hotspot.signals.get("churn", 0),
        functions=hotspot.signals.get("function", 0),
        content=head,
    )
    try:
        result = asyncio.run(_invoke_classifier_subagent(prompt))
    except Exception:  # noqa: BLE001 — best-effort
        return hotspot
    pattern = str(result.get("pattern", "")).strip()
    if pattern in _VALID_PATTERNS:
        hotspot.pattern = pattern
    return hotspot
