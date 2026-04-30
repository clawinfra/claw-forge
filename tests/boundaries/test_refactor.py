"""Tests for the refactor subagent invocation.

The actual subagent dispatch (`_dispatch_agent`) is mocked because
running the SDK in unit tests is slow.  These tests verify the prompt-
construction wiring and project_dir routing.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from claw_forge.boundaries.refactor import run_refactor_subagent
from claw_forge.boundaries.scorer import Hotspot


def test_refactor_subagent_passes_hotspot_to_agent(tmp_path: Path) -> None:
    """The agent prompt names the file path and the chosen pattern."""
    hotspot = Hotspot(
        path="cli.py", score=8.7,
        signals={"dispatch": 10, "import": 5, "churn": 7, "function": 2},
        pattern="registry",
    )
    (tmp_path / "cli.py").write_text("if cmd == 'a':\n    pass\n")
    captured: dict[str, object] = {}

    async def fake_dispatch(prompt: str, *, project_dir: Path) -> dict[str, object]:
        captured["prompt"] = prompt
        captured["project_dir"] = project_dir
        return {"changes_made": True}

    with patch(
        "claw_forge.boundaries.refactor._dispatch_agent",
        side_effect=fake_dispatch,
    ):
        import asyncio
        asyncio.run(run_refactor_subagent(hotspot, project_dir=tmp_path))

    prompt = str(captured["prompt"])
    assert "cli.py" in prompt
    assert "registry" in prompt or "plugin registry" in prompt
    assert captured["project_dir"] == tmp_path


def test_refactor_subagent_uses_pattern_specific_template(tmp_path: Path) -> None:
    """Each pattern gets its own prompt template emphasizing the right
    refactor goal."""
    (tmp_path / "x.py").write_text("pass\n")

    captured_prompts: list[str] = []

    async def fake_dispatch(prompt: str, *, project_dir: Path) -> dict[str, object]:
        captured_prompts.append(prompt)
        return {}

    with patch(
        "claw_forge.boundaries.refactor._dispatch_agent",
        side_effect=fake_dispatch,
    ):
        import asyncio
        for pattern in ["registry", "split", "extract_collaborators", "route_table"]:
            asyncio.run(run_refactor_subagent(
                Hotspot(path="x.py", score=5.0, pattern=pattern),
                project_dir=tmp_path,
            ))

    assert len(captured_prompts) == 4
    # Prompts differ per pattern (basic sanity).
    assert len({p for p in captured_prompts}) == 4


def test_refactor_subagent_falls_back_to_registry_on_unknown_pattern(
    tmp_path: Path,
) -> None:
    """If the hotspot has an empty/unknown pattern, default to the registry
    template (the most generic refactor)."""
    (tmp_path / "x.py").write_text("pass\n")
    captured: dict[str, str] = {}

    async def fake_dispatch(prompt: str, *, project_dir: Path) -> dict[str, object]:
        captured["prompt"] = prompt
        return {}

    with patch(
        "claw_forge.boundaries.refactor._dispatch_agent",
        side_effect=fake_dispatch,
    ):
        import asyncio
        asyncio.run(run_refactor_subagent(
            Hotspot(path="x.py", score=5.0, pattern=""),
            project_dir=tmp_path,
        ))
    # Registry template mentions "plugin registry" or "if/elif chain"
    prompt = captured["prompt"].lower()
    assert "registry" in prompt or "if/elif" in prompt
