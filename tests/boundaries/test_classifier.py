"""Tests for the hotspot pattern classifier subagent.

The classifier is mocked in unit tests because exercising
claude-agent-sdk against a real agent is slow and flaky.  These tests
verify input/output wiring against a stubbed agent response.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from claw_forge.boundaries.classifier import classify_hotspot
from claw_forge.boundaries.scorer import Hotspot


def test_classify_hotspot_returns_pattern_from_subagent(tmp_path: Path) -> None:
    cli = tmp_path / "cli.py"
    cli.write_text("# big dispatcher\n" + "if x == 'a':\n    pass\n" * 10)
    hotspot = Hotspot(
        path="cli.py",
        score=8.7,
        signals={"dispatch": 10, "churn": 5, "import": 3, "function": 2},
    )
    with patch(
        "claw_forge.boundaries.classifier._invoke_classifier_subagent",
        return_value={"pattern": "registry", "rationale": "10 if/elif on cmd"},
    ):
        result = classify_hotspot(hotspot, project_dir=tmp_path)
    assert result.pattern == "registry"


def test_classify_hotspot_ignores_unknown_pattern(tmp_path: Path) -> None:
    """Subagent returning a value outside the four known patterns is ignored —
    the hotspot is returned with empty pattern, signaling the user should
    decide manually rather than us applying a wrong refactor."""
    cli = tmp_path / "cli.py"
    cli.write_text("pass\n")
    hotspot = Hotspot(path="cli.py", score=5.0, signals={})
    with patch(
        "claw_forge.boundaries.classifier._invoke_classifier_subagent",
        return_value={"pattern": "wat", "rationale": "?"},
    ):
        result = classify_hotspot(hotspot, project_dir=tmp_path)
    assert result.pattern == ""


def test_classify_hotspot_handles_subagent_failure(tmp_path: Path) -> None:
    """Subagent error doesn't crash classify_hotspot — pattern stays empty."""
    cli = tmp_path / "cli.py"
    cli.write_text("pass\n")
    hotspot = Hotspot(path="cli.py", score=5.0, signals={})
    with patch(
        "claw_forge.boundaries.classifier._invoke_classifier_subagent",
        side_effect=RuntimeError("agent unreachable"),
    ):
        result = classify_hotspot(hotspot, project_dir=tmp_path)
    assert result.pattern == ""


def test_classify_hotspot_handles_missing_target_file(tmp_path: Path) -> None:
    """If the hotspot path doesn't exist on disk, return unchanged."""
    hotspot = Hotspot(path="vanished.py", score=5.0, signals={})
    result = classify_hotspot(hotspot, project_dir=tmp_path)
    assert result.pattern == ""
