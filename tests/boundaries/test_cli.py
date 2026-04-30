"""Tests for ``claw-forge boundaries`` CLI commands."""
from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from claw_forge.cli import app


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.x"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)


def test_boundaries_audit_writes_report(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "main.py").write_text(
        "\n".join(
            f"{'if' if i == 0 else 'elif'} cmd == 'c{i}':\n    do_c{i}()"
            for i in range(6)
        ) + "\n"
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["boundaries", "audit", "--project", str(tmp_path), "--min-score", "1.0"],
    )
    assert result.exit_code == 0, result.output
    report = tmp_path / "boundaries_report.md"
    assert report.exists()
    text = report.read_text()
    assert "main.py" in text


def test_boundaries_audit_writes_to_custom_out_path(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "model.py").write_text("class User:\n    pass\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    out_path = tmp_path / "custom" / "report.md"
    out_path.parent.mkdir()
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "boundaries", "audit",
            "--project", str(tmp_path),
            "--out", str(out_path),
            "--min-score", "0.0",
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_path.exists()
    # Default path should NOT be written
    assert not (tmp_path / "boundaries_report.md").exists()


def test_boundaries_status_shows_report_summary(tmp_path: Path) -> None:
    (tmp_path / "boundaries_report.md").write_text(
        "# Boundaries Audit — myapp\n\n2 hotspots\n\n"
        "## 1. cli.py  (score 8.7)\n"
        "- signals: dispatch=10, import=5, churn=7, function=2\n"
        "**Proposed pattern:** registry\n\n"
        "## 2. parser.py  (score 6.0)\n"
        "- signals: dispatch=4, import=3, churn=2, function=1\n"
        "**Proposed pattern:** route_table\n\n"
    )
    runner = CliRunner()
    result = runner.invoke(
        app, ["boundaries", "status", "--project", str(tmp_path)]
    )
    assert result.exit_code == 0
    assert "cli.py" in result.output
    assert "parser.py" in result.output
    assert "8.7" in result.output


def test_boundaries_status_exits_when_no_report(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app, ["boundaries", "status", "--project", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "No boundaries_report.md" in result.output


def test_boundaries_apply_runs_hotspots_from_existing_report(
    tmp_path: Path, monkeypatch,
) -> None:
    """``apply --auto`` reads boundaries_report.md and runs apply_hotspot
    for each hotspot in score order."""
    _init_repo(tmp_path)
    (tmp_path / "cli.py").write_text("# original\n")
    (tmp_path / "test.sh").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "test.sh").chmod(0o755)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    # Pre-write a report so apply doesn't auto-audit.
    (tmp_path / "boundaries_report.md").write_text(
        "# Boundaries Audit — test\n\n1 hotspot\n\n"
        "## 1. cli.py  (score 8.7)\n"
        "- signals: dispatch=10, import=5, churn=7, function=2\n"
        "**Proposed pattern:** registry\n\n"
    )
    calls: list[str] = []

    async def fake_run_refactor(h, *, project_dir):
        (project_dir / "cli.py").write_text("# refactored\n")
        calls.append(h.path)
        return {"changes_made": True}

    monkeypatch.setattr(
        "claw_forge.boundaries.apply.run_refactor_subagent", fake_run_refactor,
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "boundaries", "apply",
            "--project", str(tmp_path),
            "--auto",
            "--test-command", "./test.sh",
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls == ["cli.py"]
    assert (tmp_path / "cli.py").read_text() == "# refactored\n"


def test_boundaries_apply_filters_by_hotspot_path(
    tmp_path: Path, monkeypatch,
) -> None:
    """``--hotspot=<path>`` runs only that one entry from the report."""
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("# a\n")
    (tmp_path / "b.py").write_text("# b\n")
    (tmp_path / "test.sh").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "test.sh").chmod(0o755)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    (tmp_path / "boundaries_report.md").write_text(
        "# Boundaries Audit\n\n2 hotspots\n\n"
        "## 1. a.py  (score 7.0)\n"
        "- signals: dispatch=5, import=2, churn=3, function=0\n"
        "**Proposed pattern:** registry\n\n"
        "## 2. b.py  (score 6.0)\n"
        "- signals: dispatch=4, import=1, churn=2, function=0\n"
        "**Proposed pattern:** split\n\n"
    )
    calls: list[str] = []

    async def fake_run_refactor(h, *, project_dir):
        (project_dir / h.path).write_text("# done\n")
        calls.append(h.path)
        return {"changes_made": True}

    monkeypatch.setattr(
        "claw_forge.boundaries.apply.run_refactor_subagent", fake_run_refactor,
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "boundaries", "apply",
            "--project", str(tmp_path),
            "--hotspot", "b.py",
            "--auto",
            "--test-command", "./test.sh",
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls == ["b.py"]


def test_boundaries_apply_unknown_hotspot_exits(tmp_path: Path) -> None:
    """``--hotspot=<unknown>`` fails fast."""
    (tmp_path / "boundaries_report.md").write_text(
        "# Boundaries Audit\n\n0 hotspots\n\n"
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "boundaries", "apply",
            "--project", str(tmp_path),
            "--hotspot", "nope.py",
            "--auto",
        ],
    )
    assert result.exit_code == 1
    assert "No hotspot" in result.output
