"""Refactor subagent: takes one hotspot + pattern, applies the refactor.

Each canonical pattern has its own prompt template emphasizing the right
goal.  The subagent runs via the existing ``run_agent`` helper, which
wires the SDK's sandbox, ``can_use_tool`` permissions, and tool set —
so writes are project-dir-restricted and bash is gated.

The ``run_refactor_subagent`` function is async; ``apply_hotspot`` (in
``apply.py``) bridges it to a sync context with ``asyncio.run``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from claw_forge.agent.runner import run_agent
from claw_forge.boundaries.scorer import Hotspot

_REFACTOR_PROMPTS: dict[str, str] = {
    "registry": (
        "Refactor {path} so its long if/elif chain on a string key becomes "
        "a plugin registry: extract each branch into its own file under a "
        "``commands/`` (or analogous) subdirectory; introduce a registry "
        "loader; the main file becomes only argument parsing + registry "
        "dispatch.  Preserve all behavior.  All existing tests must still "
        "pass."
    ),
    "split": (
        "Refactor {path} by splitting it into multiple files, one per "
        "logical domain.  Preserve all public APIs and behavior.  All "
        "existing tests must still pass."
    ),
    "extract_collaborators": (
        "Refactor {path} by extracting collaborator classes/objects from "
        "the god-class.  Preserve behavior and public API.  All existing "
        "tests must still pass."
    ),
    "route_table": (
        "Refactor {path} by replacing the hardcoded route/handler list "
        "with a route registry where new handlers are added by importing "
        "a decorated function.  Preserve all routes.  All existing tests "
        "must still pass."
    ),
}


async def _dispatch_agent(prompt: str, *, project_dir: Path) -> dict[str, Any]:
    """Run the SDK coding agent; return a summary dict from the final message."""
    final: dict[str, Any] = {}
    async for msg in run_agent(
        prompt=prompt,
        project_dir=project_dir,
        agent_type="coding",
    ):
        if msg.__class__.__name__ == "ResultMessage":
            text = getattr(msg, "result", "") or ""
            final = {"result_text": text, "changes_made": True}
    return final


async def run_refactor_subagent(
    hotspot: Hotspot, *, project_dir: Path,
) -> dict[str, Any]:
    """Build the prompt for the hotspot's pattern and dispatch the agent.

    Falls back to the ``registry`` template if the hotspot's pattern is
    empty or unknown — registry is the most generic refactor and gives
    the agent a starting point even without classifier confirmation.
    """
    template = _REFACTOR_PROMPTS.get(
        hotspot.pattern, _REFACTOR_PROMPTS["registry"],
    )
    prompt = template.format(path=hotspot.path)
    return await _dispatch_agent(prompt, project_dir=project_dir)
