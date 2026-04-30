"""Tests for the apply lifecycle on synthetic projects."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claw_forge.boundaries.apply import apply_hotspot, run_test_command
from claw_forge.boundaries.scorer import Hotspot


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.x"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)


# ── run_test_command ──────────────────────────────────────────────────────────


def test_run_test_command_returns_true_on_zero_exit(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "passing.sh").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "passing.sh").chmod(0o755)
    assert run_test_command("./passing.sh", cwd=tmp_path) is True


def test_run_test_command_returns_false_on_nonzero(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "failing.sh").write_text("#!/bin/sh\nexit 1\n")
    (tmp_path / "failing.sh").chmod(0o755)
    assert run_test_command("./failing.sh", cwd=tmp_path) is False


def test_run_test_command_returns_false_on_timeout(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "slow.sh").write_text("#!/bin/sh\nsleep 10\n")
    (tmp_path / "slow.sh").chmod(0o755)
    assert run_test_command(
        "./slow.sh", cwd=tmp_path, timeout_seconds=0.5,
    ) is False


# ── apply_hotspot ─────────────────────────────────────────────────────────────


def _seed_repo(tmp_path: Path) -> None:
    """Init repo with cli.py + test.sh (passing) + first commit."""
    _init_repo(tmp_path)
    (tmp_path / "cli.py").write_text("# original\n")
    (tmp_path / "test.sh").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "test.sh").chmod(0o755)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)


def test_apply_hotspot_squash_merges_when_tests_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subagent edits a file; tests stay green; change is squash-merged to main."""
    _seed_repo(tmp_path)
    hotspot = Hotspot(path="cli.py", score=8.7, pattern="registry")

    async def fake_run_refactor(
        h: Hotspot, *, project_dir: Path,
    ) -> dict[str, Any]:
        (project_dir / "cli.py").write_text("# refactored\n")
        return {"changes_made": True}

    monkeypatch.setattr(
        "claw_forge.boundaries.apply.run_refactor_subagent", fake_run_refactor,
    )
    result = apply_hotspot(
        hotspot, project_dir=tmp_path, test_command="./test.sh",
    )
    assert result["status"] == "merged", result
    # main now contains the refactored content
    assert (tmp_path / "cli.py").read_text() == "# refactored\n"


def test_apply_hotspot_reverts_when_tests_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subagent edits a file but tests fail → revert; main untouched."""
    _seed_repo(tmp_path)
    # Replace test.sh with a failing one
    (tmp_path / "test.sh").write_text("#!/bin/sh\nexit 1\n")
    subprocess.run(["git", "add", "test.sh"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "fail tests"], cwd=tmp_path, check=True,
    )
    hotspot = Hotspot(path="cli.py", score=8.7, pattern="registry")

    async def fake_run_refactor(
        h: Hotspot, *, project_dir: Path,
    ) -> dict[str, Any]:
        (project_dir / "cli.py").write_text("# broken\n")
        return {"changes_made": True}

    monkeypatch.setattr(
        "claw_forge.boundaries.apply.run_refactor_subagent", fake_run_refactor,
    )
    result = apply_hotspot(
        hotspot, project_dir=tmp_path, test_command="./test.sh",
    )
    assert result["status"] == "reverted", result
    # main is unchanged
    assert (tmp_path / "cli.py").read_text() == "# original\n"


def test_apply_hotspot_skipped_when_subagent_makes_no_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subagent runs but doesn't actually change anything → skipped."""
    _seed_repo(tmp_path)
    hotspot = Hotspot(path="cli.py", score=8.7, pattern="registry")

    async def fake_run_refactor(
        h: Hotspot, *, project_dir: Path,
    ) -> dict[str, Any]:
        # No file edits
        return {"changes_made": False}

    monkeypatch.setattr(
        "claw_forge.boundaries.apply.run_refactor_subagent", fake_run_refactor,
    )
    result = apply_hotspot(
        hotspot, project_dir=tmp_path, test_command="./test.sh",
    )
    assert result["status"] == "skipped", result
    assert (tmp_path / "cli.py").read_text() == "# original\n"


def test_apply_hotspot_skipped_when_subagent_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subagent error is caught; hotspot is skipped, main untouched."""
    _seed_repo(tmp_path)
    hotspot = Hotspot(path="cli.py", score=8.7, pattern="registry")

    async def fake_run_refactor(
        h: Hotspot, *, project_dir: Path,
    ) -> dict[str, Any]:
        raise RuntimeError("agent crashed")

    monkeypatch.setattr(
        "claw_forge.boundaries.apply.run_refactor_subagent", fake_run_refactor,
    )
    result = apply_hotspot(
        hotspot, project_dir=tmp_path, test_command="./test.sh",
    )
    assert result["status"] == "skipped"
    assert "agent crashed" in result.get("reason", "")
    assert (tmp_path / "cli.py").read_text() == "# original\n"


# ── End-to-end: audit → apply on synthetic dispatcher ─────────────────────────


def test_end_to_end_audit_then_apply_on_synthetic_dispatcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit identifies a dispatcher hotspot; apply (with stubbed subagent)
    refactors it; tests stay green; squash-merged on main."""
    from claw_forge.boundaries.audit import run_audit
    from claw_forge.boundaries.report import emit_report

    _init_repo(tmp_path)
    cli = tmp_path / "main.py"
    cli.write_text(
        "\n".join(
            f"{'if' if i == 0 else 'elif'} cmd == 'c{i}':\n    do_c{i}()"
            for i in range(8)
        ) + "\n"
    )
    (tmp_path / "test.sh").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "test.sh").chmod(0o755)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    # Audit
    spots = run_audit(tmp_path, min_score=2.0)
    emit_report(
        spots, out_path=tmp_path / "boundaries_report.md", project_name="syn",
    )
    assert any(h.path == "main.py" for h in spots)

    # Apply (stubbed subagent writes a "refactored" version)
    async def fake_run_refactor(
        h: Hotspot, *, project_dir: Path,
    ) -> dict[str, Any]:
        (project_dir / "main.py").write_text("# refactored — registry pattern\n")
        return {"changes_made": True}

    monkeypatch.setattr(
        "claw_forge.boundaries.apply.run_refactor_subagent", fake_run_refactor,
    )
    main_hotspot = next(h for h in spots if h.path == "main.py")
    main_hotspot.pattern = "registry"  # would normally come from classifier
    result = apply_hotspot(
        main_hotspot, project_dir=tmp_path, test_command="./test.sh",
    )
    assert result["status"] == "merged", result
    assert (tmp_path / "main.py").read_text().startswith("# refactored")
