"""Regression test: ``claw-forge run`` must call ``prune_worktrees`` at startup.

The CLAUDE.md "Startup sweep" doc claims this happens, and ``GitOps.init()``
defines the wiring, but until v0.5.34 nothing in ``cli.py`` actually invoked
that wrapper — so stale ``.claw-forge/worktrees/<slug>/`` dirs from earlier
crashed runs accumulated indefinitely.  This test mocks the state-service
init endpoint, runs the dispatcher entry point, and asserts the stale dir
is gone afterwards.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import respx
from httpx import Response
from typer.testing import CliRunner

from claw_forge.cli import app

_runner = CliRunner()


def _yaml(tmp_path: Path) -> Path:
    cfg = tmp_path / "claw-forge.yaml"
    cfg.write_text(
        "providers: {}\n"
        "git:\n"
        "  enabled: true\n"
        "  merge_strategy: auto\n"
        "  branch_prefix: feat\n"
        "agent:\n"
        "  default_model: claude-sonnet-4-6\n"
    )
    return cfg


@pytest.fixture()
def project_with_stale_worktree(tmp_path: Path) -> Path:
    """A git project with a stale ``.claw-forge/worktrees/foo/`` directory."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@x"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "f.txt").write_text("seed")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    stale = tmp_path / ".claw-forge" / "worktrees" / "stale-from-crashed-run"
    stale.mkdir(parents=True)
    (stale / "leftover.txt").write_text("crash debris")
    return tmp_path


def test_run_startup_prunes_stale_worktree_dirs(
    project_with_stale_worktree: Path,
) -> None:
    """A stale dir under .claw-forge/worktrees/ is removed at run startup."""
    project = project_with_stale_worktree
    cfg = _yaml(project)
    stale = project / ".claw-forge" / "worktrees" / "stale-from-crashed-run"
    assert stale.exists()  # precondition

    init_payload = {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "orphans_reset": 0,
        "tasks_adopted": 0,
        # Empty tasks list → run exits early after init, before agent dispatch
        "tasks": [],
    }

    base_url = "http://127.0.0.1:8420"
    with respx.mock(base_url=base_url, assert_all_called=False) as mock, \
            patch("claw_forge.cli._ensure_state_service", return_value=8420):
        mock.post("/sessions/init").mock(return_value=Response(200, json=init_payload))
        result = _runner.invoke(
            app,
            ["run", "--config", str(cfg), "--project", str(project)],
        )

    # Run completes (no tasks → graceful exit)
    assert result.exit_code == 0, result.output
    # The stale dir is gone — this is the regression we're catching.
    assert not stale.exists(), (
        f"prune_worktrees was not invoked at startup; "
        f"stale dir still exists: {stale}\nOutput: {result.output}"
    )
    # The parent ``worktrees/`` may be removed by ``git worktree remove --force``
    # cleanup or it may remain as an empty directory — either is fine.
    parent = project / ".claw-forge" / "worktrees"
    if parent.exists():
        assert list(parent.iterdir()) == [], (
            f"worktrees dir not empty after prune: {list(parent.iterdir())}"
        )


def test_run_no_op_when_no_stale_worktrees(tmp_path: Path) -> None:
    """Run startup without a worktrees dir is a clean no-op (no error)."""
    cfg = _yaml(tmp_path)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@x"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "f.txt").write_text("seed")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

    init_payload = {
        "session_id": "00000000-0000-0000-0000-000000000002",
        "orphans_reset": 0,
        "tasks_adopted": 0,
        "tasks": [],
    }

    base_url = "http://127.0.0.1:8420"
    with respx.mock(base_url=base_url, assert_all_called=False) as mock, \
            patch("claw_forge.cli._ensure_state_service", return_value=8420):
        mock.post("/sessions/init").mock(return_value=Response(200, json=init_payload))
        result = _runner.invoke(
            app,
            ["run", "--config", str(cfg), "--project", str(tmp_path)],
        )

    assert result.exit_code == 0, result.output
    # Make sure the helper didn't accidentally print the count when there's
    # nothing to prune (UX nit — but worth pinning).
    assert "Pruned 0 stale worktree" not in result.output
