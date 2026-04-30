"""Tests for boundaries_report.md emission and parsing."""
from __future__ import annotations

from pathlib import Path

from claw_forge.boundaries.report import emit_report, parse_report
from claw_forge.boundaries.scorer import Hotspot


def test_round_trip_emit_then_parse(tmp_path: Path) -> None:
    hotspots = [
        Hotspot(
            path="cli/main.py", score=8.7,
            signals={"dispatch": 10, "import": 6, "churn": 14, "function": 3},
            pattern="registry",
        ),
        Hotspot(
            path="parser.py", score=6.2,
            signals={"dispatch": 4, "import": 8, "churn": 5, "function": 1},
            pattern="route_table",
        ),
    ]
    out = tmp_path / "boundaries_report.md"
    emit_report(hotspots, out_path=out, project_name="myapp")
    parsed = parse_report(out)
    assert len(parsed) == 2
    assert parsed[0].path == "cli/main.py"
    assert parsed[0].pattern == "registry"
    assert parsed[0].signals["dispatch"] == 10
    assert parsed[1].path == "parser.py"
    assert parsed[1].pattern == "route_table"


def test_emit_empty_hotspots_writes_zero_count(tmp_path: Path) -> None:
    """An empty list still produces a valid (empty) report."""
    out = tmp_path / "boundaries_report.md"
    emit_report([], out_path=out, project_name="myapp")
    text = out.read_text()
    assert "0 hotspot" in text
    assert parse_report(out) == []


def test_emit_omits_pattern_line_when_pattern_empty(tmp_path: Path) -> None:
    """When the classifier didn't produce a pattern, the report still emits
    the hotspot header + signals (so the user can see the score) but skips
    the 'Proposed pattern' line."""
    out = tmp_path / "boundaries_report.md"
    emit_report(
        [Hotspot(
            path="x.py", score=5.0,
            signals={"dispatch": 5, "import": 2, "churn": 1, "function": 0},
            pattern="",
        )],
        out_path=out,
    )
    text = out.read_text()
    assert "x.py" in text
    assert "Proposed pattern" not in text


def test_parse_handles_score_with_one_decimal(tmp_path: Path) -> None:
    """The header writes scores with one decimal; parser reads them back."""
    raw = (
        "# Boundaries Audit\n\n"
        "1 hotspot(s) identified.\n\n"
        "## 1. cli.py  (score 6.2)\n"
        "- signals: dispatch=4, import=2, churn=1, function=0\n"
        "**Proposed pattern:** registry\n\n"
    )
    p = tmp_path / "r.md"
    p.write_text(raw)
    parsed = parse_report(p)
    assert len(parsed) == 1
    assert abs(parsed[0].score - 6.2) < 0.01
