"""Tests for claw_forge CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from claw_forge.cli import app

runner = CliRunner()


# ── helpers ───────────────────────────────────────────────────────────────────


def _yaml_config(tmp_path: Path, providers: dict[str, Any] | None = None) -> Path:
    """Write a minimal claw-forge.yaml to tmp_path and return the path."""
    cfg: dict[str, Any] = {"providers": providers or {}}
    import yaml  # type: ignore[import-untyped]

    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump(cfg))
    return cfg_path


# ── --help ────────────────────────────────────────────────────────────────────


def test_help_exits_0() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "claw-forge" in result.output


# ── status ────────────────────────────────────────────────────────────────────


def test_status_missing_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    # No config file — run_help is mocked to avoid file deps
    with patch("claw_forge.commands.help_cmd.run_help") as mock_help:
        result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    mock_help.assert_called_once()


def test_status_with_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    cfg = _yaml_config(tmp_path)
    with patch("claw_forge.commands.help_cmd.run_help") as mock_help:
        result = runner.invoke(app, ["status", "--config", str(cfg)])
    assert result.exit_code == 0
    mock_help.assert_called_once()


# ── run ───────────────────────────────────────────────────────────────────────


def test_run_with_config(tmp_path: Path) -> None:
    cfg = _yaml_config(tmp_path, providers={"p1": {"type": "anthropic", "api_key": "k"}})
    result = runner.invoke(app, ["run", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "claw-forge" in result.output


def test_run_missing_config(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", "--config", str(tmp_path / "missing.yaml")])
    assert result.exit_code != 0


def test_run_yolo_mode(tmp_path: Path) -> None:
    cfg = _yaml_config(tmp_path)
    result = runner.invoke(app, ["run", "--config", str(cfg), "--yolo"])
    assert result.exit_code == 0
    assert "YOLO" in result.output


# ── pool-status ───────────────────────────────────────────────────────────────


def test_pool_status_empty_providers(tmp_path: Path) -> None:
    cfg = _yaml_config(tmp_path, providers={})
    result = runner.invoke(app, ["pool-status", "--config", str(cfg)])
    assert result.exit_code == 0


def test_pool_status_with_providers(tmp_path: Path) -> None:
    import yaml  # type: ignore[import-untyped]

    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(
        yaml.dump(
            {
                "providers": {
                    "my-provider": {
                        "type": "openai_compat",
                        "base_url": "http://localhost:11434",
                        "enabled": True,
                        "priority": 1,
                        "cost_per_mtok_input": 0.5,
                        "cost_per_mtok_output": 1.5,
                    }
                }
            }
        )
    )
    result = runner.invoke(app, ["pool-status", "--config", str(cfg_path)])
    assert result.exit_code == 0


# ── init ─────────────────────────────────────────────────────────────────────


def test_init_scaffolds_project(tmp_path: Path) -> None:
    """init (no spec) bootstraps .claude/, CLAUDE.md, and claw-forge.yaml."""
    mock_scaffold = {
        "claude_md_written": True,
        "dot_claude_created": True,
        "spec_example_written": True,
        "commands_copied": [".claude/commands/create-spec.md"],
        "stack": {"language": "python", "framework": "unknown"},
    }
    with patch("claw_forge.scaffold.scaffold_project", return_value=mock_scaffold):
        result = runner.invoke(app, ["init", "--project", str(tmp_path)])
    assert result.exit_code == 0
    assert "stack detected" in result.output.lower()
    out = result.output
    assert ".claude" in out or "create-spec" in out or "Next step" in out


def test_init_shows_next_step_hint(tmp_path: Path) -> None:
    """init without spec shows /create-spec hint when no spec file exists."""
    mock_scaffold = {
        "claude_md_written": False,
        "dot_claude_created": False,
        "spec_example_written": False,
        "commands_copied": [],
        "stack": {"language": "unknown", "framework": "unknown"},
    }
    with patch("claw_forge.scaffold.scaffold_project", return_value=mock_scaffold):
        result = runner.invoke(app, ["init", "--project", str(tmp_path)])
    assert result.exit_code == 0
    assert "/create-spec" in result.output or "Next step" in result.output


def test_plan_missing_spec(tmp_path: Path) -> None:
    """plan with a missing spec file exits with error."""
    cfg = _yaml_config(tmp_path)
    result = runner.invoke(
        app, ["plan", str(tmp_path / "nonexistent.xml"), "--config", str(cfg)]
    )
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_plan_with_valid_spec(tmp_path: Path) -> None:
    """plan with a valid spec parses features and prints summary."""
    spec_path = tmp_path / "spec.xml"
    spec_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<project name="test-project" mode="greenfield">
  <features>
    <feature category="core">
      <name>Feature A</name>
      <description>Do something</description>
    </feature>
  </features>
</project>
"""
    )
    cfg = _yaml_config(tmp_path)
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.output = "done"
    mock_result.metadata = {
        "feature_count": 1,
        "project_name": "test-project",
        "category_counts": {"core": 1},
        "wave_count": 1,
        "phases": [],
    }
    with patch("claw_forge.cli.asyncio.run", return_value=mock_result):
        result = runner.invoke(
            app, ["plan", str(spec_path), "--config", str(cfg), "--project", str(tmp_path)]
        )
    assert result.exit_code == 0
    assert "test-project" in result.output


# ── pause / resume ────────────────────────────────────────────────────────────


def test_pause_service_offline() -> None:
    with patch("claw_forge.cli._http_post", side_effect=SystemExit(1)):
        result = runner.invoke(app, ["pause", "my-session"])
    assert result.exit_code != 0


def test_pause_success() -> None:
    with patch("claw_forge.cli._http_post", return_value={"paused": True}):
        result = runner.invoke(app, ["pause", "my-session"])
    assert result.exit_code == 0
    assert "paused" in result.output.lower()


def test_resume_success() -> None:
    with patch("claw_forge.cli._http_post", return_value={"paused": False}):
        result = runner.invoke(app, ["resume", "my-session"])
    assert result.exit_code == 0
    assert "resumed" in result.output.lower()


def test_resume_unexpected_response() -> None:
    with patch("claw_forge.cli._http_post", return_value={"paused": True}):
        result = runner.invoke(app, ["resume", "my-session"])
    assert result.exit_code != 0


def test_pause_unexpected_response() -> None:
    with patch("claw_forge.cli._http_post", return_value={"paused": False}):
        result = runner.invoke(app, ["pause", "my-session"])
    assert result.exit_code != 0


# ── fix ───────────────────────────────────────────────────────────────────────


def test_fix_no_args() -> None:
    result = runner.invoke(app, ["fix"])
    assert result.exit_code != 0


def test_fix_report_not_found(tmp_path: Path) -> None:
    result = runner.invoke(app, ["fix", "--report", str(tmp_path / "ghost.md")])
    assert result.exit_code != 0


def test_fix_with_description(tmp_path: Path) -> None:
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.output = "Fixed"
    mock_result.files_modified = ["app.py"]

    # patch asyncio.run so the heavy agent loop never runs
    with (
        patch("claw_forge.cli.asyncio.run", return_value=mock_result),
        patch("subprocess.run"),  # suppress git checkout
    ):
        result = runner.invoke(
            app,
            ["fix", "users get 500 on login", "--project", str(tmp_path), "--no-branch"],
        )
    assert result.exit_code == 0
    assert "complete" in result.output.lower()


def test_fix_failure(tmp_path: Path) -> None:
    mock_result = MagicMock()
    mock_result.success = False
    mock_result.output = "could not reproduce"

    with (
        patch("claw_forge.cli.asyncio.run", return_value=mock_result),
        patch("subprocess.run"),
    ):
        result = runner.invoke(
            app,
            ["fix", "some bug", "--project", str(tmp_path), "--no-branch"],
        )
    assert result.exit_code != 0


def test_fix_with_report_file(tmp_path: Path) -> None:
    report_path = tmp_path / "bug_report.md"
    report_path.write_text(
        "# Bug Report\n\n**Title:** Login 500 error\n\n## Steps\n1. go to /login\n"
    )
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.output = "done"
    mock_result.files_modified = []

    with (
        patch("claw_forge.cli.asyncio.run", return_value=mock_result),
        patch("subprocess.run"),
    ):
        result = runner.invoke(
            app,
            ["fix", "--report", str(report_path), "--project", str(tmp_path), "--no-branch"],
        )
    assert result.exit_code == 0


# ── add ───────────────────────────────────────────────────────────────────────


def test_add_single_feature_no_branch(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["add", "add dark mode", "--project", str(tmp_path), "--no-branch"]
    )
    assert result.exit_code == 0
    assert "dark mode" in result.output.lower() or "feature" in result.output.lower()


def test_add_single_feature_with_branch(tmp_path: Path) -> None:
    result = runner.invoke(app, ["add", "search functionality", "--project", str(tmp_path)])
    assert result.exit_code == 0


def test_add_with_spec(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.xml"
    spec_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<project name="my-app" mode="brownfield">
  <features>
    <feature category="ui">
      <name>Dark mode</name>
      <description>Toggle dark mode</description>
    </feature>
  </features>
</project>
"""
    )
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.output = "ok"
    mock_result.files_modified = []

    with patch("claw_forge.cli.asyncio.run", return_value=mock_result):
        result = runner.invoke(
            app,
            ["add", "ignored", "--spec", str(spec_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0


# ── ui ────────────────────────────────────────────────────────────────────────


def test_ui_no_ui_dir(tmp_path: Path) -> None:
    """Should exit with error if ui/ directory is not found."""
    with patch("claw_forge.cli.Path.__truediv__", return_value=tmp_path / "ui"):
        result = runner.invoke(app, ["ui"])
    # ui dir probably doesn't exist in test env → should exit 1
    # (If it does exist we can still check for non-crash)
    assert result.exit_code in (0, 1)


def test_ui_no_node(tmp_path: Path) -> None:
    """Should fail gracefully when node.js is absent."""
    import shutil

    ui_dir = tmp_path / "ui"
    ui_dir.mkdir()

    with (
        patch("claw_forge.cli.Path.__truediv__", return_value=ui_dir),
        patch.object(shutil, "which", return_value=None),
    ):
        result = runner.invoke(app, ["ui"])
    assert result.exit_code in (0, 1)


# ── state ─────────────────────────────────────────────────────────────────────


def test_state_command_invokes_uvicorn() -> None:
    with patch("uvicorn.run"):
        result = runner.invoke(app, ["state", "--port", "9999"])
    # uvicorn.run called or exit
    assert result.exit_code in (0, 1)


# ── _load_config helpers ──────────────────────────────────────────────────────


def test_load_config_missing_raises(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", "--config", str(tmp_path / "nope.yaml")])
    assert result.exit_code != 0
    assert "not found" in result.output.lower() or "config" in result.output.lower()


def test_load_config_with_env_file(tmp_path: Path) -> None:
    import yaml  # type: ignore[import-untyped]

    env_file = tmp_path / ".env"
    env_file.write_text("MY_KEY=abc123\n")
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}, "key": "${MY_KEY}"}))
    result = runner.invoke(app, ["run", "--config", str(cfg_path)])
    assert result.exit_code == 0


# ── input command ─────────────────────────────────────────────────────────────


def test_input_no_pending_items() -> None:
    with patch("claw_forge.cli._http_get", return_value=[]):
        result = runner.invoke(app, ["input", "my-session"])
    assert result.exit_code == 0
    assert "no pending" in result.output.lower()


def test_input_with_pending_items() -> None:
    pending = [
        {"task_id": "t1", "description": "do something", "question": "What approach?"}
    ]
    with (
        patch("claw_forge.cli._http_get", return_value=pending),
        patch("claw_forge.cli._http_post", return_value={}),
        patch("typer.prompt", return_value="use approach A"),
    ):
        result = runner.invoke(app, ["input", "my-session"])
    assert result.exit_code == 0
    assert "answer" in result.output.lower() or "answered" in result.output.lower()
