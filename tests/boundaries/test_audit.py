"""End-to-end audit tests on synthetic projects."""
from __future__ import annotations

import subprocess
from pathlib import Path

from claw_forge.boundaries.audit import run_audit


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.x"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)


def test_audit_flags_dispatcher_file_above_simple_files(tmp_path: Path) -> None:
    """An 8-branch dispatcher file ranks above a simple data class."""
    _init_repo(tmp_path)
    cli = tmp_path / "cli.py"
    cli.write_text(
        "def main(args):\n"
        + "\n".join(
            f"    {'if' if i == 0 else 'elif'} args.cmd == 'c{i}':\n"
            f"        do_c{i}()"
            for i in range(8)
        )
        + "\n    else:\n        raise ValueError\n"
    )
    (tmp_path / "model.py").write_text("class User:\n    name: str\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    hotspots = run_audit(tmp_path, min_score=2.0)
    paths = [h.path for h in hotspots]
    assert "cli.py" in paths
    assert "model.py" not in paths


def test_audit_returns_empty_for_low_score_project(tmp_path: Path) -> None:
    """A simple project with no dispatchers and no churn returns no hotspots
    above a reasonable threshold."""
    _init_repo(tmp_path)
    (tmp_path / "model.py").write_text("class User:\n    name: str\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    hotspots = run_audit(tmp_path, min_score=5.0)
    assert hotspots == []


def test_audit_records_signals_per_hotspot(tmp_path: Path) -> None:
    """Each Hotspot in the result carries the signal counts that produced
    its score, so the report can explain why."""
    _init_repo(tmp_path)
    cli = tmp_path / "cli.py"
    cli.write_text(
        "def main(args):\n"
        + "\n".join(
            f"    {'if' if i == 0 else 'elif'} args.cmd == 'c{i}':\n"
            f"        pass"
            for i in range(10)
        )
        + "\n"
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    hotspots = run_audit(tmp_path, min_score=2.0)
    assert hotspots
    h = next(h for h in hotspots if h.path == "cli.py")
    assert h.signals["dispatch"] >= 9  # 1 if + 9 elif on string keys
    assert "import" in h.signals
    assert "churn" in h.signals
    assert "function" in h.signals
