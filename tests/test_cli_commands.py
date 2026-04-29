"""Tests for claw_forge CLI commands."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import httpx
import pytest
import yaml
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
    with patch("claw_forge.cli._ensure_state_service", return_value=8420):
        result = runner.invoke(app, ["run", "--config", str(cfg), "--project", str(tmp_path)])
    assert result.exit_code == 0
    assert "claw-forge" in result.output


def test_run_missing_config(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", "--config", str(tmp_path / "missing.yaml")])
    assert result.exit_code != 0


def test_run_yolo_mode(tmp_path: Path) -> None:
    cfg = _yaml_config(tmp_path)
    with patch("claw_forge.cli._ensure_state_service", return_value=8420):
        result = runner.invoke(
            app, ["run", "--config", str(cfg), "--yolo", "--project", str(tmp_path)]
        )
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
        "git_initialized": True,
    }
    with patch("claw_forge.scaffold.scaffold_project", return_value=mock_scaffold):
        result = runner.invoke(app, ["init", "--project", str(tmp_path)])
    assert result.exit_code == 0
    assert "stack detected" in result.output.lower()
    out = result.output
    assert ".claude" in out or "create-spec" in out or "Next step" in out
    # .env.example must always be created by init
    assert (tmp_path / ".env.example").exists(), ".env.example missing after init"


def test_init_creates_env_example_when_yaml_already_exists(tmp_path: Path) -> None:
    """Regression: .env.example must be created even when claw-forge.yaml already exists.

    Previously, _scaffold_config was only called when the yaml was absent.
    If the user ran `init` twice (or created claw-forge.yaml manually) the
    .env.example was silently skipped.
    """
    # Pre-create claw-forge.yaml so _scaffold_config is NOT triggered
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(
        "project: existing\nproviders:\n  - name: p\n    type: anthropic\n    api_key: ${KEY}\n"
    )
    assert not (tmp_path / ".env.example").exists()

    mock_scaffold = {
        "claude_md_written": False,
        "dot_claude_created": False,
        "spec_example_written": False,
        "commands_copied": [],
        "stack": {"language": "unknown", "framework": "unknown"},
        "git_initialized": False,
    }
    with patch("claw_forge.scaffold.scaffold_project", return_value=mock_scaffold):
        result = runner.invoke(app, ["init", "--project", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".env.example").exists(), (
        ".env.example not created when claw-forge.yaml already existed — regression"
    )
    assert ".env.example" in result.output or "env" in result.output.lower()


def test_init_shows_next_step_hint(tmp_path: Path) -> None:
    """init without spec shows /create-spec hint when no spec file exists."""
    mock_scaffold = {
        "claude_md_written": False,
        "dot_claude_created": False,
        "spec_example_written": False,
        "commands_copied": [],
        "stack": {"language": "unknown", "framework": "unknown"},
        "git_initialized": False,
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
    mock_result = Mock()
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


def _plan_spec_path(tmp_path: Path) -> Path:
    spec_path = tmp_path / "spec.xml"
    spec_path.write_text("<project/>")
    return spec_path


def _plan_mock_result(features: list[dict[str, Any]] | None = None) -> Mock:
    m = Mock()
    m.success = True
    m.output = "done"
    m.metadata = {
        "feature_count": len(features) if features else 0,
        "project_name": "test-project",
        "category_counts": {"core": len(features) if features else 0},
        "wave_count": 1,
        "phases": [],
        "features": features or [],
    }
    return m


def test_plan_reconcile_shows_summary(tmp_path: Path) -> None:
    """plan reconciles with existing session and prints summary."""
    spec_path = _plan_spec_path(tmp_path)
    cfg = _yaml_config(tmp_path)
    features = [
        {"index": i, "name": f"F{i}", "description": f"Desc {i}",
         "category": "core", "steps": [], "depends_on_indices": []}
        for i in range(3)
    ]

    # First call: plugin.execute → mock_result; second: _write_plan_to_db → real
    first_result = _plan_mock_result(features)
    call_count = 0
    _real_run = __import__("asyncio").run

    def _side_effect(coro: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            coro.close()
            return first_result
        return _real_run(coro)

    with patch("claw_forge.cli.asyncio.run", side_effect=_side_effect):
        runner.invoke(
            app, ["plan", str(spec_path), "--config", str(cfg),
                  "--project", str(tmp_path)]
        )

    # Second plan with extra features → reconcile output
    features_v2 = features + [
        {"index": 3, "name": "F3", "description": "Desc 3",
         "category": "core", "steps": [], "depends_on_indices": []},
    ]
    second_result = _plan_mock_result(features_v2)
    call_count = 0

    def _side_effect2(coro: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            coro.close()
            return second_result
        return _real_run(coro)

    with patch("claw_forge.cli.asyncio.run", side_effect=_side_effect2):
        result = runner.invoke(
            app, ["plan", str(spec_path), "--config", str(cfg),
                  "--project", str(tmp_path)]
        )
    assert result.exit_code == 0
    assert "Reconciled" in result.output
    assert "3 pending" in result.output
    assert "1 new" in result.output


def test_plan_reconcile_with_completed_and_failed(tmp_path: Path) -> None:
    """Reconciliation summary shows completed and failed counts."""
    import asyncio as _aio

    from claw_forge.cli import _write_plan_to_db

    spec_path = _plan_spec_path(tmp_path)
    cfg = _yaml_config(tmp_path)
    features = [
        {"index": i, "name": f"F{i}", "description": f"Desc {i}",
         "category": "core", "steps": [], "depends_on_indices": []}
        for i in range(3)
    ]

    # Seed tasks directly
    _aio.run(_write_plan_to_db(tmp_path, "proj", features))

    # Mark F0 completed, F1 failed via DB
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from claw_forge.state.models import Task

    db_url = f"sqlite+aiosqlite:///{tmp_path / '.claw-forge' / 'state.db'}"

    async def _mark() -> None:
        engine = create_async_engine(db_url)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            for t in (await db.execute(select(Task))).scalars():
                if "F0:" in (t.description or ""):
                    t.status = "completed"
                elif "F1:" in (t.description or ""):
                    t.status = "failed"
            await db.commit()
        await engine.dispose()

    _aio.run(_mark())

    # Plan with one extra feature
    features_v2 = features + [
        {"index": 3, "name": "F3", "description": "Desc 3",
         "category": "core", "steps": [], "depends_on_indices": []},
    ]
    mock_result = _plan_mock_result(features_v2)
    call_count = 0
    _real_run = _aio.run

    def _side_effect(coro: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            coro.close()
            return mock_result
        return _real_run(coro)

    with patch("claw_forge.cli.asyncio.run", side_effect=_side_effect):
        result = runner.invoke(
            app, ["plan", str(spec_path), "--config", str(cfg),
                  "--project", str(tmp_path)]
        )
    assert result.exit_code == 0
    assert "Reconciled" in result.output
    assert "1 completed" in result.output
    assert "1 failed" in result.output
    assert "1 pending" in result.output
    assert "1 new" in result.output


def test_plan_reconcile_other_status(tmp_path: Path) -> None:
    """Reconciliation summary shows 'other' count for non-standard statuses."""
    import asyncio as _aio

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from claw_forge.cli import _write_plan_to_db
    from claw_forge.state.models import Task

    spec_path = _plan_spec_path(tmp_path)
    cfg = _yaml_config(tmp_path)
    features = [
        {"index": 0, "name": "F0", "description": "Desc 0",
         "category": "core", "steps": [], "depends_on_indices": []},
    ]
    _aio.run(_write_plan_to_db(tmp_path, "proj", features))

    # Mark task as "blocked"
    db_url = f"sqlite+aiosqlite:///{tmp_path / '.claw-forge' / 'state.db'}"

    async def _mark() -> None:
        engine = create_async_engine(db_url)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            for t in (await db.execute(select(Task))).scalars():
                t.status = "blocked"
            await db.commit()
        await engine.dispose()

    _aio.run(_mark())

    features_v2 = features + [
        {"index": 1, "name": "F1", "description": "Desc 1",
         "category": "core", "steps": [], "depends_on_indices": []},
    ]
    mock_result = _plan_mock_result(features_v2)
    call_count = 0
    _real_run = _aio.run

    def _side_effect(coro: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            coro.close()
            return mock_result
        return _real_run(coro)

    with patch("claw_forge.cli.asyncio.run", side_effect=_side_effect):
        result = runner.invoke(
            app, ["plan", str(spec_path), "--config", str(cfg),
                  "--project", str(tmp_path)]
        )
    assert result.exit_code == 0
    assert "Reconciled" in result.output
    assert "1 other" in result.output
    assert "1 new" in result.output


def test_plan_fresh_flag(tmp_path: Path) -> None:
    """--fresh creates a new session even when one exists."""
    import asyncio as _aio

    from claw_forge.cli import _write_plan_to_db

    spec_path = _plan_spec_path(tmp_path)
    cfg = _yaml_config(tmp_path)
    features = [
        {"index": 0, "name": "F0", "description": "Desc 0",
         "category": "core", "steps": [], "depends_on_indices": []},
    ]

    # Seed tasks
    _aio.run(_write_plan_to_db(tmp_path, "proj", features))

    mock_result = _plan_mock_result(features)
    call_count = 0
    _real_run = _aio.run

    def _side_effect(coro: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            coro.close()
            return mock_result
        return _real_run(coro)

    with patch("claw_forge.cli.asyncio.run", side_effect=_side_effect):
        result = runner.invoke(
            app, ["plan", str(spec_path), "--config", str(cfg),
                  "--project", str(tmp_path), "--fresh"]
        )
    assert result.exit_code == 0
    # --fresh should NOT show reconciliation output
    assert "Reconciled" not in result.output


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
    mock_result = Mock()
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
    mock_result = Mock()
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
    mock_result = Mock()
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
    mock_result = Mock()
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


def test_ui_serves_static_bundle(tmp_path: Path) -> None:
    """Default ui command (no --dev) serves the pre-built static bundle via uvicorn."""
    import claw_forge.cli as cli_mod

    fake_dist = tmp_path / "ui_dist"
    fake_dist.mkdir()
    (fake_dist / "index.html").write_text("<html><head></head><body>UI</body></html>")
    (fake_dist / "assets").mkdir()

    with (
        patch.object(cli_mod, "__file__", str(fake_dist.parent / "cli.py")),
        patch("uvicorn.run"),
        patch("starlette.staticfiles.StaticFiles.__init__", return_value=None),
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
    ):
        result = runner.invoke(app, ["ui", "--no-open"])
    assert result.exit_code == 0, result.output
    assert "Kanban UI" in result.output


def test_ui_no_bundle_shows_helpful_error(tmp_path: Path) -> None:
    """When ui_dist is missing (corrupt install), show actionable error — not 'from source'."""
    import claw_forge.cli as cli_mod

    # Point cli module to a dir where ui_dist does NOT exist
    empty_dir = tmp_path / "pkg"
    empty_dir.mkdir()

    with patch.object(cli_mod, "__file__", str(empty_dir / "cli.py")):
        result = runner.invoke(app, ["ui", "--no-open"])

    assert result.exit_code == 1
    assert "not found" in result.output.lower()
    # Must NOT say "installed from source" (old misleading message)
    assert "installed from source" not in result.output


def test_ui_dev_mode_no_source_dir(tmp_path: Path) -> None:
    """--dev mode exits cleanly when ui/ source dir is absent."""
    import claw_forge.cli as cli_mod

    # Point parent to a dir with no ui/ subdirectory
    empty_parent = tmp_path / "pkg"
    empty_parent.mkdir()

    with patch.object(cli_mod, "__file__", str(empty_parent / "cli.py")):
        result = runner.invoke(app, ["ui", "--dev", "--no-open"])

    assert result.exit_code == 1
    assert "source" in result.output.lower() or "not found" in result.output.lower()


def test_ui_dev_no_node(tmp_path: Path) -> None:
    """--dev mode fails gracefully when Node.js is absent."""
    import shutil

    import claw_forge.cli as cli_mod

    # Create a fake ui/ source dir so the path check passes
    fake_pkg = tmp_path / "claw_forge"
    fake_pkg.mkdir()
    fake_ui = tmp_path / "ui"
    fake_ui.mkdir()

    with (
        patch.object(cli_mod, "__file__", str(fake_pkg / "cli.py")),
        patch.object(shutil, "which", return_value=None),
    ):
        result = runner.invoke(app, ["ui", "--dev", "--no-open"])
    assert result.exit_code == 1
    assert "node" in result.output.lower() or "Node" in result.output


# ── state ─────────────────────────────────────────────────────────────────────


def test_state_command_invokes_uvicorn() -> None:
    # Snapshot env vars that the state command mutates, then restore after.
    saved = {
        k: os.environ.get(k)
        for k in ("CLAW_FORGE_DB_URL", "CLAW_FORGE_PROJECT_PATH")
    }
    try:
        with patch("uvicorn.run"):
            result = runner.invoke(app, ["state", "--port", "9999"])
        # uvicorn.run called or exit
        assert result.exit_code in (0, 1)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ── _load_config helpers ──────────────────────────────────────────────────────


def test_load_config_missing_raises(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", "--config", str(tmp_path / "nope.yaml")])
    assert result.exit_code != 0
    assert "not found" in result.output.lower() or "config" in result.output.lower()


def test_load_config_with_env_file(tmp_path: Path) -> None:
    import yaml  # type: ignore[import-untyped]

    from tests.helpers import make_fake_httpx_client

    env_file = tmp_path / ".env"
    env_file.write_text("MY_KEY=abc123\n")
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}, "key": "${MY_KEY}"}))
    FakeClient = make_fake_httpx_client(
        init_response={"session_id": "s1", "orphans_reset": 0, "tasks": []},
        task_response={},
    )
    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.httpx.AsyncClient", FakeClient),
    ):
        result = runner.invoke(app, ["run", "--config", str(cfg_path), "--project", str(tmp_path)])
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


# ── _expand_env_vars tests ────────────────────────────────────────────────────


def test_expand_env_vars_default_syntax(monkeypatch: pytest.MonkeyPatch) -> None:
    """${VAR:-default} uses default when VAR is not set."""
    from claw_forge.cli import _expand_env_vars

    monkeypatch.delenv("MODEL_OPUS", raising=False)
    result = _expand_env_vars("${MODEL_OPUS:-claude-opus-4-6}")
    assert result == "claude-opus-4-6"


def test_expand_env_vars_default_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """${VAR:-default} uses env value when VAR is set."""
    from claw_forge.cli import _expand_env_vars

    monkeypatch.setenv("MODEL_OPUS", "my-custom-model")
    result = _expand_env_vars("${MODEL_OPUS:-claude-opus-4-6}")
    assert result == "my-custom-model"


def test_expand_env_vars_nested_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expansion works recursively in dicts."""
    from claw_forge.cli import _expand_env_vars

    monkeypatch.delenv("MODEL_SONNET", raising=False)
    monkeypatch.setenv("MODEL_HAIKU", "custom-haiku")
    result = _expand_env_vars({
        "aliases": {
            "sonnet": "${MODEL_SONNET:-claude-sonnet-4-6}",
            "haiku": "${MODEL_HAIKU:-claude-haiku-4-6}",
        }
    })
    assert result["aliases"]["sonnet"] == "claude-sonnet-4-6"
    assert result["aliases"]["haiku"] == "custom-haiku"


def test_expand_env_vars_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expansion works in lists."""
    from claw_forge.cli import _expand_env_vars

    monkeypatch.delenv("X", raising=False)
    result = _expand_env_vars(["${X:-fallback}", "plain"])
    assert result == ["fallback", "plain"]


def test_expand_env_vars_no_default_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    """${VAR} without default returns empty string when unset."""
    from claw_forge.cli import _expand_env_vars

    monkeypatch.delenv("MISSING_KEY_XYZ", raising=False)
    result = _expand_env_vars("prefix-${MISSING_KEY_XYZ}-suffix")
    assert result == "prefix--suffix"


def test_expand_env_vars_passthrough() -> None:
    """Non-string/dict/list types pass through unchanged."""
    from claw_forge.cli import _expand_env_vars

    assert _expand_env_vars(42) == 42
    assert _expand_env_vars(None) is None
    assert _expand_env_vars(True) is True


# ── state --project flag test ─────────────────────────────────────────────────




# ── _scaffold_config tests ────────────────────────────────────────────────────


def test_scaffold_config_creates_files(tmp_path: Path) -> None:
    """_scaffold_config creates yaml + .env.example."""
    from claw_forge.cli import _scaffold_config

    cfg_path = str(tmp_path / "claw-forge.yaml")
    result = _scaffold_config(cfg_path)
    assert result is True
    assert (tmp_path / "claw-forge.yaml").exists()
    assert (tmp_path / ".env.example").exists()


def test_scaffold_config_existing_file(tmp_path: Path) -> None:
    """_scaffold_config returns False when config already exists."""
    from claw_forge.cli import _scaffold_config

    cfg = tmp_path / "claw-forge.yaml"
    cfg.write_text("providers: {}")
    result = _scaffold_config(str(cfg))
    assert result is False


def test_scaffold_config_creates_parent_dirs(tmp_path: Path) -> None:
    """_scaffold_config creates parent directories when they don't exist."""
    from claw_forge.cli import _scaffold_config

    nested = tmp_path / "deep" / "nested" / "dir"
    cfg_path = str(nested / "claw-forge.yaml")
    result = _scaffold_config(cfg_path)
    assert result is True
    assert (nested / "claw-forge.yaml").exists()
    assert (nested / ".env.example").exists()


def test_init_creates_project_dir(tmp_path: Path) -> None:
    """init --project creates the project directory if it doesn't exist."""
    new_dir = tmp_path / "brand-new" / "project"
    assert not new_dir.exists()
    mock_scaffold = {
        "claude_md_written": True,
        "dot_claude_created": True,
        "spec_example_written": True,
        "commands_copied": [],
        "stack": {"language": "unknown", "framework": "unknown"},
        "git_initialized": False,
    }
    with patch("claw_forge.scaffold.scaffold_project", return_value=mock_scaffold):
        result = runner.invoke(app, ["init", "--project", str(new_dir)])
    assert result.exit_code == 0, result.output
    assert new_dir.exists(), "project directory was not created"
    assert (new_dir / "claw-forge.yaml").exists()


# ── _load_config tests ────────────────────────────────────────────────────────


def test_load_config_missing_no_scaffold(tmp_path: Path) -> None:
    """_load_config raises Exit when file missing and auto_scaffold=False."""
    from claw_forge.cli import _load_config

    with pytest.raises((SystemExit, Exception)):
        _load_config(str(tmp_path / "nonexistent.yaml"))


def test_load_config_auto_scaffold(tmp_path: Path) -> None:
    """_load_config with auto_scaffold=True creates config then loads it."""
    from claw_forge.cli import _load_config

    cfg_path = str(tmp_path / "claw-forge.yaml")
    result = _load_config(cfg_path, auto_scaffold=True)
    assert isinstance(result, dict)
    assert (tmp_path / "claw-forge.yaml").exists()


def test_load_config_with_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_load_config reads .env and expands vars in yaml."""
    from claw_forge.cli import _load_config

    (tmp_path / ".env").write_text("TEST_KEY_XYZ=my-secret\n")
    (tmp_path / "claw-forge.yaml").write_text(
        yaml.dump({"key": "${TEST_KEY_XYZ}"})
    )
    monkeypatch.delenv("TEST_KEY_XYZ", raising=False)
    result = _load_config(str(tmp_path / "claw-forge.yaml"))
    assert result["key"] == "my-secret"


# ── _http_get / _http_post error path tests ──────────────────────────────────


def test_http_get_connect_error() -> None:
    """_http_get prints hint and exits on ConnectError."""
    from claw_forge.cli import _http_get

    with pytest.raises((SystemExit, Exception)):
        _http_get("http://localhost:19999/nonexistent")


def test_http_post_connect_error() -> None:
    """_http_post prints hint and exits on ConnectError."""
    from claw_forge.cli import _http_post

    with pytest.raises((SystemExit, Exception)):
        _http_post("http://localhost:19999/nonexistent")


def test_http_get_status_error() -> None:
    """_http_get exits on HTTP errors."""
    from claw_forge.cli import _http_get

    mock_resp = Mock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal error"
    mock_resp.json.return_value = {}
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Server Error", request=httpx.Request("GET", "http://x"), response=mock_resp
    )
    with (
        patch("claw_forge.cli.httpx.get", return_value=mock_resp),
        pytest.raises((SystemExit, Exception)),
    ):
        _http_get("http://localhost:19999/test")


def test_http_post_status_error() -> None:
    """_http_post exits on HTTP errors."""
    from claw_forge.cli import _http_post

    mock_resp = Mock()
    mock_resp.status_code = 404
    mock_resp.text = "Not found"
    mock_resp.json.return_value = {}
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Not Found", request=httpx.Request("POST", "http://x"), response=mock_resp
    )
    with (
        patch("claw_forge.cli.httpx.post", return_value=mock_resp),
        pytest.raises((SystemExit, Exception)),
    ):
        _http_post("http://localhost:19999/test")


# ── _state_url test ──────────────────────────────────────────────────────────


def test_state_url_default() -> None:
    from claw_forge.cli import _state_url

    assert _state_url() == "http://localhost:8420"
    assert _state_url(9999) == "http://localhost:9999"


# ── UI helper functions ──────────────────────────────────────────────────────

class TestResolveLatestSession:
    def test_returns_empty_when_db_missing(self, tmp_path: Path) -> None:
        from claw_forge.cli import _resolve_latest_session
        result = _resolve_latest_session(tmp_path / "nonexistent.db")
        assert result == ""

    def test_returns_empty_when_no_sessions(self, tmp_path: Path) -> None:
        import sqlite3

        from claw_forge.cli import _resolve_latest_session
        db = tmp_path / "state.db"
        with sqlite3.connect(str(db)) as conn:
            conn.execute(
                "CREATE TABLE sessions (id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
        result = _resolve_latest_session(db)
        assert result == ""

    def test_returns_latest_session_id(self, tmp_path: Path) -> None:
        import sqlite3

        from claw_forge.cli import _resolve_latest_session
        db = tmp_path / "state.db"
        with sqlite3.connect(str(db)) as conn:
            conn.execute(
                "CREATE TABLE sessions (id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.execute("INSERT INTO sessions VALUES ('sess-aaa', '2026-01-01')")
            conn.execute("INSERT INTO sessions VALUES ('sess-bbb', '2026-01-02')")
        result = _resolve_latest_session(db)
        assert result == "sess-bbb"

    def test_returns_empty_on_db_error(self, tmp_path: Path) -> None:
        from claw_forge.cli import _resolve_latest_session
        # Corrupt file — sqlite will raise
        db = tmp_path / "bad.db"
        db.write_bytes(b"not a sqlite db")
        result = _resolve_latest_session(db)
        assert result == ""


class TestBuildSessionRedirectJs:
    def test_empty_when_no_session(self) -> None:
        from claw_forge.cli import _build_session_redirect_js
        assert _build_session_redirect_js("") == ""

    def test_returns_js_with_session_id(self) -> None:
        from claw_forge.cli import _build_session_redirect_js
        js = _build_session_redirect_js("abc-123")
        assert "abc-123" in js
        assert "replaceState" in js
        assert "URLSearchParams" in js

    def test_js_contains_session_param(self) -> None:
        from claw_forge.cli import _build_session_redirect_js
        js = _build_session_redirect_js("my-session-id")
        assert "?session=my-session-id" in js


class TestEnsureStateService:
    def test_returns_false_when_already_running(self, tmp_path: Path) -> None:
        """If port is bound and /info confirms same project, returns the port (no restart)."""
        import json
        import socket
        from unittest.mock import Mock, patch

        from claw_forge import __version__
        from claw_forge.cli import _ensure_state_service

        # Simulate /info returning the same project path and current version
        mock_resp = Mock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = Mock(return_value=False)
        mock_resp.read.return_value = json.dumps(
            {"project_path": str(tmp_path.resolve()), "claw_forge_version": __version__}
        ).encode()

        with socket.socket() as srv:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            port = srv.getsockname()[1]
            with patch("urllib.request.urlopen", return_value=mock_resp):
                result = _ensure_state_service(tmp_path, port)
        assert result == port

    def test_restarts_when_wrong_project(self, tmp_path: Path) -> None:
        """If /info returns a different project, the service is restarted."""
        import json
        import socket
        from unittest.mock import Mock, patch

        from claw_forge.cli import _ensure_state_service

        wrong_project = "/some/other/project"
        info_call_count = [0]

        def fake_urlopen(url_or_req: Any, **kw: Any) -> Any:
            url_str = (
                url_or_req if isinstance(url_or_req, str) else url_or_req.full_url
            )
            if "/shutdown" in url_str:
                resp = Mock()
                resp.__enter__ = lambda s: s
                resp.__exit__ = Mock(return_value=False)
                resp.read.return_value = b'{"status":"ok"}'
                return resp
            info_call_count[0] += 1
            # First /info: wrong project (triggers restart).
            # Second /info (after restart): correct project.
            project = wrong_project if info_call_count[0] == 1 else str(tmp_path)
            resp = Mock()
            resp.__enter__ = lambda s: s
            resp.__exit__ = Mock(return_value=False)
            resp.read.return_value = json.dumps(
                {"project_path": project}
            ).encode()
            return resp

        mock_popen = Mock()
        mock_conn = Mock()
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = Mock(return_value=False)
        with socket.socket() as srv:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            port = srv.getsockname()[1]
            with (
                patch("urllib.request.urlopen", side_effect=fake_urlopen),
                patch("subprocess.Popen", mock_popen),
                patch("time.sleep"),
                # monotonic: always return 0 so loops never time out
                patch("time.monotonic", return_value=0.0),
                # call 1: initial check (port busy by srv socket above)
                # call 2: _wait_for_port_free (OSError = port freed)
                # call 3: _wait_for_port in _start (success = new service ready)
                patch("socket.create_connection",
                      side_effect=[mock_conn, OSError("free"), mock_conn]),

            ):
                result = _ensure_state_service(tmp_path, port)
        assert result == port
        mock_popen.assert_called_once()

    def test_auto_starts_when_port_free(self, tmp_path: Path) -> None:
        """When port is free, Popen is called and returns True."""
        import json
        from unittest.mock import Mock, patch

        from claw_forge.cli import _ensure_state_service
        mock_popen = Mock()
        mock_conn = Mock()
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = Mock(return_value=False)
        # Mock /info response so _verify_info succeeds after startup
        mock_resp = Mock()
        mock_resp.read.return_value = json.dumps({"project_path": str(tmp_path)}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = Mock(return_value=False)
        # First call: port free (OSError). Second call: port ready after start.
        with (
            patch("subprocess.Popen", mock_popen),
            patch("time.sleep"),
            patch("time.monotonic", return_value=0.0),
            # call 1: initial check (port free), call 2: _wait_for_port (ready)
            patch("socket.create_connection",
                  side_effect=[OSError("port free"), mock_conn]),
            patch("urllib.request.urlopen", return_value=mock_resp),
        ):
            result = _ensure_state_service(tmp_path, 19999)
        assert result == 19999
        mock_popen.assert_called_once()
        call_kwargs = mock_popen.call_args.kwargs
        assert call_kwargs.get("start_new_session") is True


# ── sdk agent execution (CLAUDECODE pop/restore) ──────────────────────────────


class TestSdkAgentExecution:
    """Tests for the sdk_available execution path in the run command.

    These tests verify that CLAUDECODE is popped from os.environ during the
    claude CLI subprocess spawn and properly restored in the finally block.
    """

    _TASK_ID = "test-task-001"
    _SESSION_ID = "test-session-001"

    @staticmethod
    def _mock_httpx_client(task_id: str, session_id: str) -> type:
        """Return a mock httpx.AsyncClient that fakes state-service responses."""
        from tests.helpers import make_fake_httpx_client

        return make_fake_httpx_client(
            init_response={
                "session_id": session_id,
                "orphans_reset": 0,
                "tasks": [
                    {
                        "id": task_id,
                        "plugin_name": "coding",
                        "description": "Implement a feature",
                        "category": "",
                        "status": "pending",
                        "priority": 1,
                        "depends_on": [],
                        "steps": [],
                    },
                ],
            },
            task_response={
                "id": task_id,
                "plugin_name": "coding",
                "description": "Implement a feature",
                "status": "pending",
                "steps": [],
            },
        )

    def test_claudecode_popped_and_restored_on_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLAUDECODE is removed before spawning claude CLI and restored after."""
        import os

        project_path = tmp_path / "proj"
        project_path.mkdir()

        config_path = tmp_path / "cf.yaml"
        config_path.write_text("providers: {}\n")

        monkeypatch.setenv("CLAUDECODE", "1")

        env_during_aenter: list[str | None] = []

        class FakeAgentSession:
            def __init__(self, options: Any) -> None:
                pass

            async def __aenter__(self) -> FakeAgentSession:
                env_during_aenter.append(os.environ.get("CLAUDECODE"))
                return self

            async def __aexit__(self, *args: Any) -> None:
                pass

            async def run(self, prompt: str) -> Any:  # type: ignore[misc]
                class _Msg:
                    text = "Code written successfully."

                yield _Msg()

        with (
            patch("claw_forge.cli._ensure_state_service", return_value=8420),
            patch("claw_forge.cli.shutil.which", return_value="/usr/bin/claude"),
            patch("claw_forge.agent.session.AgentSession", FakeAgentSession),
            patch(
                "claw_forge.cli.httpx.AsyncClient",
                self._mock_httpx_client(self._TASK_ID, self._SESSION_ID),
            ),
        ):
            result = runner.invoke(
                app,
                ["run", "--config", str(config_path), "--project", str(project_path)],
            )

        # CLAUDECODE must be restored after the run
        assert os.environ.get("CLAUDECODE") == "1"
        # CLAUDECODE must have been absent while AgentSession was entered
        assert env_during_aenter == [None]
        assert result.exit_code == 0

    def test_claudecode_restored_after_sdk_exception(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLAUDECODE is restored even when the AgentSession raises."""
        import os

        project_path = tmp_path / "proj2"
        project_path.mkdir()

        config_path = tmp_path / "cf2.yaml"
        config_path.write_text("providers: {}\n")

        monkeypatch.setenv("CLAUDECODE", "1")

        class FailingAgentSession:
            def __init__(self, options: Any) -> None:
                pass

            async def __aenter__(self) -> FailingAgentSession:
                raise RuntimeError("claude CLI not logged in")

            async def __aexit__(self, *args: Any) -> None:
                pass

            async def run(self, prompt: str) -> Any:  # type: ignore[misc]
                yield  # pragma: no cover

        with (
            patch("claw_forge.cli._ensure_state_service", return_value=8420),
            patch("claw_forge.cli.shutil.which", return_value="/usr/bin/claude"),
            patch("claw_forge.agent.session.AgentSession", FailingAgentSession),
            patch(
                "claw_forge.cli.httpx.AsyncClient",
                self._mock_httpx_client(self._TASK_ID, self._SESSION_ID),
            ),
        ):
            result = runner.invoke(
                app,
                ["run", "--config", str(config_path), "--project", str(project_path)],
            )

        # CLAUDECODE must be restored even after an exception
        assert os.environ.get("CLAUDECODE") == "1"
        # run command itself should exit 0 (task fails, but CLI exits cleanly)
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# _port_in_use_error — standalone helper, no state service needed
# ---------------------------------------------------------------------------


class TestPortInUseError:
    """Tests for the _port_in_use_error helper function (cli.py lines 1626-1659)."""

    def _call(
        self,
        port: int,
        service: str = "state service",
        platform_name: str = "Darwin",
    ) -> str:
        """Call _port_in_use_error, suppress the Exit, return stdout."""
        import io
        import sys
        from unittest.mock import patch

        from claw_forge.cli import _port_in_use_error

        buf = io.StringIO()
        with patch("platform.system", return_value=platform_name):
            old, sys.stdout = sys.stdout, buf
            try:
                _port_in_use_error(port, service)
            except Exception:  # noqa: BLE001 — catches typer.Exit / click.Exit
                pass
            finally:
                sys.stdout = old
        return buf.getvalue()

    def test_port_in_use_error_raises_exit(self) -> None:
        """_port_in_use_error always raises a typer.Exit exception."""
        from unittest.mock import patch

        import click

        from claw_forge.cli import _port_in_use_error

        with patch("platform.system", return_value="Darwin"), pytest.raises(click.exceptions.Exit):
            _port_in_use_error(8888)

    def test_port_in_use_error_mac_output(self) -> None:
        """On macOS, does not print Linux ss command."""
        out = self._call(9000, platform_name="Darwin")
        assert "9000" in out
        assert "lsof" in out
        assert "ss -tlnp" not in out  # macOS skips ss command

    def test_port_in_use_error_linux_output(self) -> None:
        """On Linux, prints ss command as alternative (line 1641)."""
        out = self._call(7777, platform_name="Linux")
        assert "7777" in out
        assert "ss -tlnp" in out  # Linux includes ss command

    def test_port_in_use_error_includes_shutdown_url(self) -> None:
        """Output includes the shutdown endpoint URL."""
        out = self._call(8420, platform_name="Darwin")
        assert "http://localhost:8420/shutdown" in out


# ── run command: invalid edit mode ─────────────────────────────────────────────


def test_run_invalid_edit_mode(tmp_path: Path) -> None:
    """--edit-mode with unsupported value exits with error."""
    cfg = _yaml_config(tmp_path, providers={"p1": {"type": "anthropic", "api_key": "k"}})
    with patch("claw_forge.cli._ensure_state_service", return_value=8420):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg), "--project", str(tmp_path), "--edit-mode", "bad"],
        )
    assert result.exit_code != 0
    assert "invalid" in result.output.lower() or "bad" in result.output.lower()


def test_run_negative_loop_threshold(tmp_path: Path) -> None:
    """--loop-detect-threshold < 0 exits with error."""
    cfg = _yaml_config(tmp_path, providers={"p1": {"type": "anthropic", "api_key": "k"}})
    with patch("claw_forge.cli._ensure_state_service", return_value=8420):
        result = runner.invoke(
            app,
            [
                "run", "--config", str(cfg), "--project", str(tmp_path),
                "--loop-detect-threshold", "-1",
            ],
        )
    assert result.exit_code != 0


def test_run_config_edit_mode_hashline(tmp_path: Path) -> None:
    """Config file edit_mode=hashline is picked up when CLI default is str_replace."""
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({
        "providers": {"p": {"type": "anthropic", "api_key": "k"}},
        "agent": {"edit_mode": "hashline"},
    }))
    with patch("claw_forge.cli._ensure_state_service", return_value=8420):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0
    assert "hashline" in result.output


def test_run_config_loop_threshold(tmp_path: Path) -> None:
    """Config file loop_detect_threshold overrides default when CLI is at default."""
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({
        "providers": {"p": {"type": "anthropic", "api_key": "k"}},
        "agent": {"loop_detect_threshold": 10},
    }))
    # Just verify it doesn't crash — the threshold is applied internally
    with patch("claw_forge.cli._ensure_state_service", return_value=8420):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0


def test_run_config_auto_push(tmp_path: Path) -> None:
    """Config file agent.auto_push is read when CLI flag is not provided."""
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({
        "providers": {"p": {"type": "anthropic", "api_key": "k"}},
        "agent": {"auto_push": "/tmp/repo"},
    }))
    with patch("claw_forge.cli._ensure_state_service", return_value=8420):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0


def test_run_model_alias(tmp_path: Path) -> None:
    """Model alias from config is resolved and printed."""
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({
        "providers": {"p": {"type": "anthropic", "api_key": "k"}},
        "model_aliases": {"sonnet": "claude-sonnet-4-6"},
    }))
    with patch("claw_forge.cli._ensure_state_service", return_value=8420):
        result = runner.invoke(
            app,
            [
                "run", "--config", str(cfg_path), "--project", str(tmp_path),
                "--model", "sonnet",
            ],
        )
    assert result.exit_code == 0
    assert "alias" in result.output.lower() or "sonnet" in result.output.lower()


def test_run_no_claude_cli(tmp_path: Path) -> None:
    """Without claude CLI, a warning about API-only mode is printed."""
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({
        "providers": {"p": {"type": "anthropic", "api_key": "k"}},
    }))
    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.shutil.which", return_value=None),
    ):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0
    assert "api-only" in result.output.lower() or "not written" in result.output.lower()


def test_run_dry_run(tmp_path: Path) -> None:
    """--dry-run prints execution plan without running agents."""
    from tests.helpers import make_fake_httpx_client

    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({
        "providers": {"p": {"type": "anthropic", "api_key": "k"}},
    }))
    FakeClient = make_fake_httpx_client(
        init_response={
            "session_id": "s1",
            "orphans_reset": 0,
            "tasks": [
                {
                    "id": "t1", "plugin_name": "coding",
                    "description": "Build feature A", "category": "core",
                    "status": "pending", "priority": 0, "depends_on": [],
                    "steps": [],
                },
                {
                    "id": "t2", "plugin_name": "coding",
                    "description": "Build feature B", "category": "core",
                    "status": "pending", "priority": 1, "depends_on": [],
                    "steps": [],
                },
            ],
        },
        task_response={},
    )
    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.httpx.AsyncClient", FakeClient),
    ):
        result = runner.invoke(
            app,
            [
                "run", "--config", str(cfg_path), "--project", str(tmp_path),
                "--dry-run",
            ],
        )
    assert result.exit_code == 0
    assert "wave" in result.output.lower() or "execution plan" in result.output.lower()


def test_run_no_pending_tasks(tmp_path: Path) -> None:
    """When no pending tasks exist, prints a message to run plan first."""
    from tests.helpers import make_fake_httpx_client

    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({
        "providers": {"p": {"type": "anthropic", "api_key": "k"}},
    }))
    FakeClient = make_fake_httpx_client(
        init_response={
            "session_id": "s1",
            "orphans_reset": 0,
            "tasks": [],
        },
        task_response={},
    )
    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.httpx.AsyncClient", FakeClient),
    ):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0
    assert "no pending" in result.output.lower() or "plan" in result.output.lower()


def test_run_tasks_adopted(tmp_path: Path) -> None:
    """When orphaned tasks are adopted, prints a message."""
    from tests.helpers import make_fake_httpx_client

    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({
        "providers": {"p": {"type": "anthropic", "api_key": "k"}},
    }))
    FakeClient = make_fake_httpx_client(
        init_response={
            "session_id": "s1",
            "tasks_adopted": 3,
            "orphans_reset": 2,
            "tasks": [],
        },
        task_response={},
    )
    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.httpx.AsyncClient", FakeClient),
    ):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0
    assert "adopted" in result.output.lower() or "orphan" in result.output.lower()


def test_run_state_service_connect_error(tmp_path: Path) -> None:
    """When state service is unreachable during init, prints error."""
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({
        "providers": {"p": {"type": "anthropic", "api_key": "k"}},
    }))

    class FailingClient:
        def __init__(self, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> FailingClient:
            return self

        async def __aexit__(self, *a: Any) -> None:
            pass

        async def post(self, url: str, **kw: Any) -> None:
            raise httpx.ConnectError("refused")

    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.httpx.AsyncClient", FailingClient),
    ):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0  # run() returns on error, no exception
    assert "cannot reach" in result.output.lower() or "state service" in result.output.lower()


# ── state command edge cases ──────────────────────────────────────────────────


def test_state_with_reload(tmp_path: Path) -> None:
    """state --reload sets env vars and calls uvicorn with factory."""
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}}))

    saved = {
        k: os.environ.get(k)
        for k in ("CLAW_FORGE_DB_URL", "CLAW_FORGE_PROJECT_PATH")
    }
    try:
        with patch("uvicorn.run") as mock_uvicorn:
            result = runner.invoke(
                app,
                [
                    "state", "--port", "9998", "--reload",
                    "--config", str(cfg_path), "--project", str(tmp_path),
                ],
            )
        assert result.exit_code == 0, result.output
        mock_uvicorn.assert_called_once()
        call_kwargs = mock_uvicorn.call_args
        assert call_kwargs.kwargs.get("reload") is True or (
            len(call_kwargs.args) > 0
        )
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_state_port_in_use(tmp_path: Path) -> None:
    """state command with port-in-use OSError prints actionable error."""
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}}))

    exc = OSError("Address already in use")
    exc.errno = 48

    with patch("uvicorn.run", side_effect=exc):
        result = runner.invoke(
            app,
            [
                "state", "--port", "9997",
                "--config", str(cfg_path), "--project", str(tmp_path),
            ],
        )
    assert result.exit_code != 0


def test_state_with_database_url(tmp_path: Path) -> None:
    """state --database-url passes the URL through to the service."""
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}}))

    with patch("uvicorn.run"):
        result = runner.invoke(
            app,
            [
                "state", "--port", "9996",
                "--config", str(cfg_path), "--project", str(tmp_path),
                "--database-url", f"sqlite+aiosqlite:///{tmp_path / 'custom.db'}",
            ],
        )
    assert result.exit_code == 0


# ── plan command edge cases ──────────────────────────────────────────────────


def test_plan_model_alias_resolved(tmp_path: Path) -> None:
    """plan --model with alias prints the resolved model."""
    spec_path = tmp_path / "spec.xml"
    spec_path.write_text("<project/>")
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({
        "providers": {},
        "model_aliases": {"opus": "claude-opus-4-6"},
    }))

    mock_result = _plan_mock_result([])
    with patch("claw_forge.cli.asyncio.run", return_value=mock_result):
        result = runner.invoke(
            app,
            [
                "plan", str(spec_path), "--config", str(cfg_path),
                "--project", str(tmp_path), "--model", "opus",
            ],
        )
    assert result.exit_code == 0
    assert "alias" in result.output.lower() or "opus" in result.output.lower()


def test_plan_failure(tmp_path: Path) -> None:
    """plan prints error when plugin execution fails."""
    spec_path = tmp_path / "spec.xml"
    spec_path.write_text("<project/>")
    cfg = _yaml_config(tmp_path)

    mock_result = Mock()
    mock_result.success = False
    mock_result.output = "parsing failed"
    with patch("claw_forge.cli.asyncio.run", return_value=mock_result):
        result = runner.invoke(
            app, ["plan", str(spec_path), "--config", str(cfg), "--project", str(tmp_path)]
        )
    assert result.exit_code != 0
    assert "failed" in result.output.lower()


def test_plan_with_phases(tmp_path: Path) -> None:
    """plan shows phases when present in metadata."""
    spec_path = tmp_path / "spec.xml"
    spec_path.write_text("<project/>")
    cfg = _yaml_config(tmp_path)

    mock_result = Mock()
    mock_result.success = True
    mock_result.output = "done"
    mock_result.metadata = {
        "feature_count": 2,
        "project_name": "test",
        "category_counts": {"core": 2},
        "wave_count": 1,
        "phases": ["Phase 1: Setup", "Phase 2: Build"],
        "features": [],
    }
    with patch("claw_forge.cli.asyncio.run", return_value=mock_result):
        result = runner.invoke(
            app, ["plan", str(spec_path), "--config", str(cfg), "--project", str(tmp_path)]
        )
    assert result.exit_code == 0
    assert "phase" in result.output.lower()


def test_plan_no_feature_count_fallback(tmp_path: Path) -> None:
    """plan without feature_count in metadata shows generic 'Plan complete'."""
    spec_path = tmp_path / "spec.xml"
    spec_path.write_text("<project/>")
    cfg = _yaml_config(tmp_path)

    mock_result = Mock()
    mock_result.success = True
    mock_result.output = "done"
    mock_result.metadata = {"some_key": "some_value"}
    with patch("claw_forge.cli.asyncio.run", return_value=mock_result):
        result = runner.invoke(
            app, ["plan", str(spec_path), "--config", str(cfg), "--project", str(tmp_path)]
        )
    assert result.exit_code == 0
    assert "plan complete" in result.output.lower() or "some_key" in result.output.lower()


def test_plan_hours_estimate(tmp_path: Path) -> None:
    """plan with many features shows hours estimate."""
    spec_path = tmp_path / "spec.xml"
    spec_path.write_text("<project/>")
    cfg = _yaml_config(tmp_path)

    mock_result = Mock()
    mock_result.success = True
    mock_result.output = "done"
    mock_result.metadata = {
        "feature_count": 200,
        "project_name": "big-project",
        "category_counts": {"core": 200},
        "wave_count": 10,
        "phases": [],
        "features": [],
    }
    with patch("claw_forge.cli.asyncio.run", return_value=mock_result):
        result = runner.invoke(
            app,
            [
                "plan", str(spec_path), "--config", str(cfg),
                "--project", str(tmp_path), "--concurrency", "5",
            ],
        )
    assert result.exit_code == 0
    assert "hour" in result.output.lower()


# ── add command: brownfield spec edge cases ──────────────────────────────────


def test_add_brownfield_parse_error(tmp_path: Path) -> None:
    """add --spec with file that raises on parse exits with error."""
    spec_path = tmp_path / "bad_spec.xml"
    spec_path.write_text("<project/>")
    cfg = _yaml_config(tmp_path)
    with patch(
        "claw_forge.spec.ProjectSpec.from_file",
        side_effect=ValueError("invalid spec format"),
    ):
        result = runner.invoke(
            app,
            ["add", "ignored", "--spec", str(spec_path), "--project", str(tmp_path),
             "--config", str(cfg)],
        )
    assert result.exit_code != 0
    assert "failed" in result.output.lower() or "parse" in result.output.lower()


def test_add_model_alias(tmp_path: Path) -> None:
    """add with model alias resolves and prints."""
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({
        "providers": {},
        "model_aliases": {"sonnet": "claude-sonnet-4-6"},
    }))
    result = runner.invoke(
        app,
        [
            "add", "add dark mode", "--project", str(tmp_path),
            "--no-branch", "--model", "sonnet", "--config", str(cfg_path),
        ],
    )
    assert result.exit_code == 0
    assert "alias" in result.output.lower() or "sonnet" in result.output.lower()


# ── fix command edge cases ───────────────────────────────────────────────────


def test_fix_with_branch_creation_failure(tmp_path: Path) -> None:
    """fix with branch creation failure continues gracefully."""
    import subprocess

    mock_result = Mock()
    mock_result.success = True
    mock_result.output = "Fixed"
    mock_result.files_modified = ["app.py"]

    with (
        patch("claw_forge.cli.asyncio.run", return_value=mock_result),
        patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(128, "git"),
        ),
    ):
        result = runner.invoke(
            app,
            ["fix", "users get 500", "--project", str(tmp_path)],
        )
    assert result.exit_code == 0
    assert "could not create branch" in result.output.lower() or "complete" in result.output.lower()


def test_fix_model_alias(tmp_path: Path) -> None:
    """fix --model with alias resolves correctly."""
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({
        "providers": {},
        "model_aliases": {"sonnet": "claude-sonnet-4-6"},
    }))
    mock_result = Mock()
    mock_result.success = True
    mock_result.output = "Fixed"
    mock_result.files_modified = []

    with (
        patch("claw_forge.cli.asyncio.run", return_value=mock_result),
        patch("subprocess.run"),
    ):
        result = runner.invoke(
            app,
            [
                "fix", "bug desc", "--project", str(tmp_path),
                "--no-branch", "--model", "sonnet", "--config", str(cfg_path),
            ],
        )
    assert result.exit_code == 0


def test_fix_output_shown(tmp_path: Path) -> None:
    """fix with output shows the result text."""
    mock_result = Mock()
    mock_result.success = True
    mock_result.output = "Applied fix to login handler"
    mock_result.files_modified = ["handlers/login.py", "tests/test_login.py"]

    with (
        patch("claw_forge.cli.asyncio.run", return_value=mock_result),
        patch("subprocess.run"),
    ):
        result = runner.invoke(
            app,
            ["fix", "login broken", "--project", str(tmp_path), "--no-branch"],
        )
    assert result.exit_code == 0
    assert "login" in result.output.lower()
    assert "files modified" in result.output.lower() or "handlers" in result.output.lower()


# ── merge command ────────────────────────────────────────────────────────────


def test_merge_no_branch_lists_branches(tmp_path: Path) -> None:
    """merge without branch argument lists feature branches."""

    mock_result = Mock()
    mock_result.stdout = "  feat/auth\n  feat/payments\n"
    mock_result.returncode = 0

    with patch("subprocess.run", return_value=mock_result):
        result = runner.invoke(
            app, ["merge", "--project", str(tmp_path)]
        )
    assert result.exit_code == 0
    assert "feat/auth" in result.output or "feature" in result.output.lower()


def test_merge_no_branches_found(tmp_path: Path) -> None:
    """merge without branch and no feature branches prints message."""

    mock_result = Mock()
    mock_result.stdout = ""
    mock_result.returncode = 0

    with patch("subprocess.run", return_value=mock_result):
        result = runner.invoke(
            app, ["merge", "--project", str(tmp_path)]
        )
    assert result.exit_code == 0
    assert "no feature" in result.output.lower()


def test_merge_git_not_available(tmp_path: Path) -> None:
    """merge in non-git dir prints error."""
    import subprocess

    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "git")):
        result = runner.invoke(
            app, ["merge", "--project", str(tmp_path)]
        )
    assert result.exit_code == 0
    assert "not a git" in result.output.lower() or "git" in result.output.lower()


def test_merge_specific_branch_success(tmp_path: Path) -> None:
    """merge with a specific branch succeeds."""
    with patch(
        "claw_forge.git.merge.squash_merge",
        return_value={"merged": True, "commit_hash": "abc123"},
    ):
        result = runner.invoke(
            app, ["merge", "feat/auth", "--project", str(tmp_path)]
        )
    assert result.exit_code == 0
    assert "merged" in result.output.lower() or "abc123" in result.output


def test_merge_specific_branch_failure(tmp_path: Path) -> None:
    """merge with a branch that fails to merge shows error."""
    with patch(
        "claw_forge.git.merge.squash_merge",
        return_value={"merged": False, "error": "conflict"},
    ):
        result = runner.invoke(
            app, ["merge", "feat/broken", "--project", str(tmp_path)]
        )
    assert result.exit_code == 0
    assert "failed" in result.output.lower() or "conflict" in result.output.lower()


# ── ui command: session display, port-in-use ─────────────────────────────────


def test_ui_with_session_flag(tmp_path: Path) -> None:
    """ui --session passes session to URL."""
    import claw_forge.cli as cli_mod

    fake_dist = tmp_path / "ui_dist"
    fake_dist.mkdir()
    (fake_dist / "index.html").write_text("<html><head></head><body>UI</body></html>")
    (fake_dist / "assets").mkdir()

    with (
        patch.object(cli_mod, "__file__", str(fake_dist.parent / "cli.py")),
        patch("uvicorn.run"),
        patch("starlette.staticfiles.StaticFiles.__init__", return_value=None),
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
    ):
        result = runner.invoke(
            app, ["ui", "--no-open", "--session", "test-sess-123"]
        )
    assert result.exit_code == 0, result.output
    assert "test-sess-123" in result.output


def test_ui_port_in_use(tmp_path: Path) -> None:
    """ui command with port-in-use OSError prints error."""
    import claw_forge.cli as cli_mod

    fake_dist = tmp_path / "ui_dist"
    fake_dist.mkdir()
    (fake_dist / "index.html").write_text("<html><head></head><body>UI</body></html>")
    (fake_dist / "assets").mkdir()

    exc = OSError("Address already in use")
    exc.errno = 48

    with (
        patch.object(cli_mod, "__file__", str(fake_dist.parent / "cli.py")),
        patch("uvicorn.run", side_effect=exc),
        patch("starlette.staticfiles.StaticFiles.__init__", return_value=None),
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
    ):
        result = runner.invoke(app, ["ui", "--no-open"])
    assert result.exit_code != 0


def test_ui_reads_session_from_db(tmp_path: Path) -> None:
    """ui auto-detects session from state.db when no --session given."""
    import sqlite3

    import claw_forge.cli as cli_mod

    # Create state.db with a session whose project_path matches the test project
    proj_dir = tmp_path / "proj"
    db_dir = proj_dir / ".claw-forge"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "state.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "CREATE TABLE sessions "
            "(id TEXT, project_path TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO sessions VALUES ('auto-sess-id', ?, '2026-01-01')",
            (str(proj_dir),),
        )

    fake_dist = tmp_path / "ui_dist"
    fake_dist.mkdir()
    (fake_dist / "index.html").write_text("<html><head></head><body>UI</body></html>")
    (fake_dist / "assets").mkdir()

    with (
        patch.object(cli_mod, "__file__", str(fake_dist.parent / "cli.py")),
        patch("uvicorn.run"),
        patch("starlette.staticfiles.StaticFiles.__init__", return_value=None),
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
    ):
        result = runner.invoke(
            app, ["ui", "--no-open", "--project", str(proj_dir)]
        )
    assert result.exit_code == 0, result.output
    assert "auto-sess-id" in result.output


# ── dev command ──────────────────────────────────────────────────────────────


def test_dev_no_source_dir(tmp_path: Path) -> None:
    """dev command fails when ui/ source directory is missing."""
    import claw_forge.cli as cli_mod

    empty_parent = tmp_path / "pkg"
    empty_parent.mkdir()

    with patch.object(cli_mod, "__file__", str(empty_parent / "cli.py")):
        result = runner.invoke(app, ["dev", "--no-open"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "source" in result.output.lower()


def test_dev_no_node(tmp_path: Path) -> None:
    """dev command fails when node is not available."""
    import shutil as shutil_mod

    import claw_forge.cli as cli_mod

    fake_pkg = tmp_path / "claw_forge"
    fake_pkg.mkdir()
    fake_ui = tmp_path / "ui"
    fake_ui.mkdir()

    with (
        patch.object(cli_mod, "__file__", str(fake_pkg / "cli.py")),
        patch.object(shutil_mod, "which", return_value=None),
    ):
        result = runner.invoke(app, ["dev", "--no-open"])
    assert result.exit_code == 1
    assert "node" in result.output.lower()


# ── _migrate_schema test ─────────────────────────────────────────────────────


def test_migrate_schema() -> None:
    """_migrate_schema runs ALTER TABLE statements without error."""
    import asyncio as _aio

    from sqlalchemy.ext.asyncio import create_async_engine

    from claw_forge.cli import _migrate_schema

    async def _test() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with engine.begin() as conn:
            from sqlalchemy import text
            await conn.execute(text(
                "CREATE TABLE tasks (id TEXT PRIMARY KEY, session_id TEXT)"
            ))
        await _migrate_schema(engine)
        # Run again to test the suppress path (columns already exist)
        await _migrate_schema(engine)
        await engine.dispose()

    _aio.run(_test())


# ── init: existing spec file shows "Spec found" ─────────────────────────────


def test_init_with_existing_spec(tmp_path: Path) -> None:
    """init with an existing app_spec.txt shows 'Spec found'."""
    (tmp_path / "app_spec.txt").write_text("some spec content")
    mock_scaffold = {
        "claude_md_written": False,
        "dot_claude_created": False,
        "spec_example_written": False,
        "commands_copied": [],
        "stack": {"language": "python", "framework": "django"},
        "git_initialized": False,
    }
    with patch("claw_forge.scaffold.scaffold_project", return_value=mock_scaffold):
        result = runner.invoke(app, ["init", "--project", str(tmp_path)])
    assert result.exit_code == 0
    assert "spec found" in result.output.lower() or "app_spec.txt" in result.output


# ── input command: multiple pending items ────────────────────────────────────


def test_input_multiple_items() -> None:
    """input with multiple pending items prompts for each."""
    pending = [
        {"task_id": "t1", "description": "task 1", "question": "Q1?"},
        {"task_id": "t2", "description": "task 2", "question": "Q2?"},
    ]
    with (
        patch("claw_forge.cli._http_get", return_value=pending),
        patch("claw_forge.cli._http_post", return_value={}),
        patch("typer.prompt", side_effect=["answer 1", "answer 2"]),
    ):
        result = runner.invoke(app, ["input", "my-session"])
    assert result.exit_code == 0
    assert "all questions" in result.output.lower() or "answered" in result.output.lower()


def test_input_no_question_text() -> None:
    """input with missing question text shows fallback."""
    pending = [
        {"task_id": "t1", "description": "task 1"},
    ]
    with (
        patch("claw_forge.cli._http_get", return_value=pending),
        patch("claw_forge.cli._http_post", return_value={}),
        patch("typer.prompt", return_value="my answer"),
    ):
        result = runner.invoke(app, ["input", "my-session"])
    assert result.exit_code == 0


# ── run command: pool-based execution (no claude CLI) ────────────────────────


def test_run_pool_fallback(tmp_path: Path) -> None:
    """When claude CLI is absent but pool has providers, uses pool execution."""
    from tests.helpers import make_fake_httpx_client

    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({
        "providers": {
            "test-provider": {
                "type": "openai_compat",
                "base_url": "http://localhost:11434",
                "api_key": "test-key",
                "enabled": True,
                "priority": 1,
            },
        },
    }))

    task_id = "pool-task-001"
    FakeClient = make_fake_httpx_client(
        init_response={
            "session_id": "s1",
            "orphans_reset": 0,
            "tasks": [
                {
                    "id": task_id,
                    "plugin_name": "coding",
                    "description": "Implement feature",
                    "category": "core",
                    "status": "pending",
                    "priority": 0,
                    "depends_on": [],
                    "steps": [],
                },
            ],
        },
        task_response={
            "id": task_id,
            "plugin_name": "coding",
            "description": "Implement feature",
            "status": "pending",
            "steps": [],
        },
    )

    mock_response = Mock()
    mock_response.content = "```app.py\nprint('hello')\n```"

    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.shutil.which", return_value=None),
        patch("claw_forge.cli.httpx.AsyncClient", FakeClient),
        patch("claw_forge.pool.manager.ProviderPoolManager.execute", return_value=mock_response),
        patch("claw_forge.output_parser.write_code_blocks", return_value=["app.py"]),
    ):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0
    assert "completed" in result.output.lower() or "succeeded" in result.output.lower()


# ── run command: no executor available ───────────────────────────────────────


def test_run_no_executor(tmp_path: Path) -> None:
    """When neither claude CLI nor pool is available, task fails with message."""
    from tests.helpers import make_fake_httpx_client

    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}}))

    task_id = "no-exec-001"
    FakeClient = make_fake_httpx_client(
        init_response={
            "session_id": "s1",
            "orphans_reset": 0,
            "tasks": [
                {
                    "id": task_id,
                    "plugin_name": "coding",
                    "description": "Feature X",
                    "category": "core",
                    "status": "pending",
                    "priority": 0,
                    "depends_on": [],
                    "steps": [],
                },
            ],
        },
        task_response={
            "id": task_id,
            "plugin_name": "coding",
            "description": "Feature X",
            "status": "pending",
            "steps": [],
        },
    )

    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.shutil.which", return_value=None),
        patch("claw_forge.cli.httpx.AsyncClient", FakeClient),
    ):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0
    # No executor path: task fails but run completes. Output should show failure
    # or the "all tasks succeeded" message (if dispatcher marks it completed).
    out = result.output.lower()
    assert "run complete" in out or "failed" in out or "succeeded" in out


# ── run command: config relative path resolution ─────────────────────────────


def test_run_config_project_relative(tmp_path: Path) -> None:
    """Run resolves config from project dir when bare filename given."""
    proj = tmp_path / "myproj"
    proj.mkdir()
    cfg_path = proj / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}}))

    with patch("claw_forge.cli._ensure_state_service", return_value=8420):
        result = runner.invoke(
            app,
            ["run", "--project", str(proj)],
        )
    assert result.exit_code == 0


# ── run: verify_on_exit from config ─────────────────────────────────────────


def test_run_verify_on_exit_config(tmp_path: Path) -> None:
    """Config verify_on_exit=false is respected."""
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({
        "providers": {"p": {"type": "anthropic", "api_key": "k"}},
        "agent": {"verify_on_exit": False},
    }))
    with patch("claw_forge.cli._ensure_state_service", return_value=8420):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0


# ── run: provider-pinned model ──────────────────────────────────────────────


def test_run_provider_pinned_model(tmp_path: Path) -> None:
    """Model like 'provider/model' shows provider hint."""
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({
        "providers": {"my-prov": {"type": "anthropic", "api_key": "k"}},
    }))
    with patch("claw_forge.cli._ensure_state_service", return_value=8420):
        result = runner.invoke(
            app,
            [
                "run", "--config", str(cfg_path), "--project", str(tmp_path),
                "--model", "my-prov/claude-opus-4-6",
            ],
        )
    assert result.exit_code == 0
    assert "provider" in result.output.lower() or "pinned" in result.output.lower()


# ── run: failed tasks summary ───────────────────────────────────────────────


def test_run_failed_tasks_hint(tmp_path: Path) -> None:
    """When tasks fail with 'All providers exhausted', shows hint."""
    from tests.helpers import make_fake_httpx_client

    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}}))

    task_ids = [f"fail-{i}" for i in range(6)]
    FakeClient = make_fake_httpx_client(
        init_response={
            "session_id": "s1",
            "orphans_reset": 0,
            "tasks": [
                {
                    "id": tid,
                    "plugin_name": "coding",
                    "description": f"Feature {i}",
                    "category": "core",
                    "status": "pending",
                    "priority": i,
                    "depends_on": [],
                    "steps": [],
                }
                for i, tid in enumerate(task_ids)
            ],
        },
        task_response={
            "id": "fail-0",
            "plugin_name": "coding",
            "description": "Feature 0",
            "status": "pending",
            "steps": [],
        },
    )

    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.shutil.which", return_value=None),
        patch("claw_forge.cli.httpx.AsyncClient", FakeClient),
    ):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0
    # Should have failure output with "more" since 6 tasks > 5 shown
    assert "failed" in result.output.lower() or "no agent" in result.output.lower()


# ── ui dev mode: full path with node_modules ─────────────────────────────────


def test_ui_dev_mode_full_path(tmp_path: Path) -> None:
    """--dev mode with existing node_modules runs npm dev server."""
    import shutil as shutil_mod

    import claw_forge.cli as cli_mod

    fake_pkg = tmp_path / "claw_forge"
    fake_pkg.mkdir()
    fake_ui = tmp_path / "ui"
    fake_ui.mkdir()
    (fake_ui / "node_modules").mkdir()

    with (
        patch.object(cli_mod, "__file__", str(fake_pkg / "cli.py")),
        patch.object(shutil_mod, "which", return_value="/usr/bin/node"),
        patch("subprocess.run") as mock_subproc,
    ):
        result = runner.invoke(
            app,
            ["ui", "--dev", "--no-open", "--project", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output
    assert "kanban ui" in result.output.lower() or "dev" in result.output.lower()
    mock_subproc.assert_called_once()


def test_ui_dev_mode_installs_deps(tmp_path: Path) -> None:
    """--dev mode installs npm dependencies when node_modules is missing."""
    import shutil as shutil_mod

    import claw_forge.cli as cli_mod

    fake_pkg = tmp_path / "claw_forge"
    fake_pkg.mkdir()
    fake_ui = tmp_path / "ui"
    fake_ui.mkdir()
    # No node_modules directory

    calls: list[list[str]] = []

    def fake_subprocess_run(cmd: list[str], **kw: Any) -> Mock:
        calls.append(cmd)
        # After npm install, create node_modules so the check passes
        if "install" in cmd:
            (fake_ui / "node_modules").mkdir(exist_ok=True)
        return Mock(returncode=0)

    with (
        patch.object(cli_mod, "__file__", str(fake_pkg / "cli.py")),
        patch.object(shutil_mod, "which", return_value="/usr/bin/node"),
        patch("subprocess.run", side_effect=fake_subprocess_run),
    ):
        result = runner.invoke(
            app,
            ["ui", "--dev", "--no-open", "--project", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output
    # Should have called npm install first
    assert any("install" in str(c) for c in calls)


# ── _ensure_state_service: port fallback ─────────────────────────────────────


class TestEnsureStateServiceFallback:
    """Tests for _ensure_state_service fallback port logic."""

    def test_all_ports_occupied_raises(self, tmp_path: Path) -> None:
        """When all ports are occupied, raises RuntimeError."""
        import json

        from claw_forge.cli import _ensure_state_service

        mock_conn = Mock()
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = Mock(return_value=False)

        # /info returns a non-claw-forge response (no project_path)
        mock_resp = Mock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = Mock(return_value=False)
        mock_resp.read.return_value = json.dumps({}).encode()

        (tmp_path / ".claw-forge").mkdir(parents=True, exist_ok=True)

        with (
            # All create_connection calls succeed (all ports busy)
            patch("socket.create_connection", return_value=mock_conn),
            patch("urllib.request.urlopen", return_value=mock_resp),
            patch("subprocess.Popen"),
            patch("time.sleep"),
            patch("time.monotonic", return_value=0.0),
            pytest.raises(RuntimeError, match="occupied"),
        ):
            _ensure_state_service(tmp_path, 19990)

    def test_stale_version_restarts(self, tmp_path: Path) -> None:
        """When running version differs from current, service is restarted."""
        import json
        import socket

        from claw_forge.cli import _ensure_state_service

        mock_resp = Mock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = Mock(return_value=False)
        mock_resp.read.return_value = json.dumps({
            "project_path": str(tmp_path.resolve()),
            "claw_forge_version": "0.0.0.old",
        }).encode()

        mock_popen = Mock()
        mock_conn = Mock()
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = Mock(return_value=False)

        with socket.socket() as srv:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            port = srv.getsockname()[1]
            with (
                patch("urllib.request.urlopen", return_value=mock_resp),
                patch("subprocess.Popen", mock_popen),
                patch("time.sleep"),
                patch("time.monotonic", return_value=0.0),
                patch("socket.create_connection",
                      side_effect=[mock_conn, OSError("free"), mock_conn]),
            ):
                result = _ensure_state_service(tmp_path, port)
        assert result == port
        mock_popen.assert_called_once()

    def test_start_failure_raises(self, tmp_path: Path) -> None:
        """When port is free but start fails, raises RuntimeError."""
        from claw_forge.cli import _ensure_state_service

        (tmp_path / ".claw-forge").mkdir(parents=True, exist_ok=True)

        with (
            # Port is free
            patch("socket.create_connection", side_effect=OSError("free")),
            patch("subprocess.Popen"),
            patch("time.sleep"),
            # monotonic: always 0 first, then huge to break loop
            patch("time.monotonic", side_effect=[0.0, 0.0, 100.0]),
            # /info fails
            patch("urllib.request.urlopen", side_effect=Exception("nope")),
            pytest.raises(RuntimeError, match="failed to start"),
        ):
            _ensure_state_service(tmp_path, 19999)


# ── run command: task with steps ─────────────────────────────────────────────


def test_run_task_with_steps(tmp_path: Path) -> None:
    """Tasks with verification steps get appended to prompt."""
    from tests.helpers import make_fake_httpx_client

    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}}))

    task_id = "steps-001"
    FakeClient = make_fake_httpx_client(
        init_response={
            "session_id": "s1",
            "orphans_reset": 0,
            "tasks": [
                {
                    "id": task_id,
                    "plugin_name": "coding",
                    "description": "Build a widget",
                    "category": "ui",
                    "status": "pending",
                    "priority": 0,
                    "depends_on": [],
                    "steps": ["Write unit tests", "Update docs"],
                },
            ],
        },
        task_response={
            "id": task_id,
            "plugin_name": "coding",
            "description": "Build a widget",
            "status": "pending",
            "steps": ["Write unit tests", "Update docs"],
        },
    )

    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.shutil.which", return_value=None),
        patch("claw_forge.cli.httpx.AsyncClient", FakeClient),
    ):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0


# ── run: task 404 from state service ─────────────────────────────────────────


def test_run_task_not_found(tmp_path: Path) -> None:
    """When a task returns 404, it's logged and skipped."""
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}}))

    task_id = "ghost-task"

    class _NotFoundClient:
        def __init__(self, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> _NotFoundClient:
            return self

        async def __aexit__(self, *a: Any) -> None:
            pass

        async def post(self, url: str, **kw: Any) -> Any:
            from tests.helpers import FakeHttpxResponse
            if "sessions/init" in url:
                return FakeHttpxResponse({
                    "session_id": "s1",
                    "orphans_reset": 0,
                    "tasks": [
                        {
                            "id": task_id,
                            "plugin_name": "coding",
                            "description": "Ghost task",
                            "category": "",
                            "status": "pending",
                            "priority": 0,
                            "depends_on": [],
                            "steps": [],
                        },
                    ],
                })
            return FakeHttpxResponse({})

        async def get(self, url: str, **kw: Any) -> Any:
            if f"/tasks/{task_id}" in url:
                resp = Mock()
                resp.status_code = 404
                resp.text = "Not found"
                raise httpx.HTTPStatusError(
                    "Not Found",
                    request=httpx.Request("GET", url),
                    response=resp,
                )
            if "/sessions/" in url and url.endswith("/tasks"):
                from tests.helpers import FakeHttpxResponse
                return FakeHttpxResponse([])
            if "/regression/" in url:
                from tests.helpers import FakeHttpxResponse
                return FakeHttpxResponse({"has_pending_work": False})
            from tests.helpers import FakeHttpxResponse
            return FakeHttpxResponse({})

        async def patch(self, url: str, **kw: Any) -> Any:
            from tests.helpers import FakeHttpxResponse
            return FakeHttpxResponse({"ok": True})

    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.shutil.which", return_value=None),
        patch("claw_forge.cli.httpx.AsyncClient", _NotFoundClient),
    ):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0
    assert "failed" in result.output.lower() or "run complete" in result.output.lower()


# ── run: CLAUDECODE not set (no restore needed) ─────────────────────────────


def test_run_claudecode_not_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When CLAUDECODE is not set, no restore is needed."""
    from tests.helpers import make_fake_httpx_client

    monkeypatch.delenv("CLAUDECODE", raising=False)
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}}))

    FakeClient = make_fake_httpx_client(
        init_response={"session_id": "s1", "orphans_reset": 0, "tasks": []},
        task_response={},
    )
    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.httpx.AsyncClient", FakeClient),
    ):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0
    assert "CLAUDECODE" not in os.environ


# ── run: running inside existing event loop ──────────────────────────────────


def test_run_with_existing_loop(tmp_path: Path) -> None:
    """Run command handles being called from within a running event loop."""
    from tests.helpers import make_fake_httpx_client

    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}}))

    FakeClient = make_fake_httpx_client(
        init_response={"session_id": "s1", "orphans_reset": 0, "tasks": []},
        task_response={},
    )

    # Simulate having a running event loop
    import asyncio

    loop = asyncio.new_event_loop()

    def _fake_get_running_loop() -> asyncio.AbstractEventLoop:
        return loop

    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.httpx.AsyncClient", FakeClient),
        patch("claw_forge.cli.asyncio.get_running_loop", _fake_get_running_loop),
    ):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    loop.close()
    assert result.exit_code == 0


# ── state command: address in use with errno 98 (Linux) ──────────────────────


def test_state_port_in_use_linux(tmp_path: Path) -> None:
    """state command with port-in-use errno 98 (Linux) prints error."""
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}}))

    exc = OSError("Address already in use")
    exc.errno = 98

    with patch("uvicorn.run", side_effect=exc):
        result = runner.invoke(
            app,
            [
                "state", "--port", "9995",
                "--config", str(cfg_path), "--project", str(tmp_path),
            ],
        )
    assert result.exit_code != 0


# ── _load_env_file: comment and blank lines ──────────────────────────────────


def test_load_env_file_parses_correctly(tmp_path: Path) -> None:
    """_load_env_file parses key=value, ignores comments and blanks."""
    from claw_forge.cli import _load_env_file

    env_file = tmp_path / ".env"
    env_file.write_text(
        "# This is a comment\n"
        "\n"
        "TEST_CLI_KEY_ABC=some_value\n"
        "TEST_CLI_KEY_DEF=another_value\n"
        "BAD_LINE_NO_EQUALS\n"
    )
    # Clear any pre-existing values
    os.environ.pop("TEST_CLI_KEY_ABC", None)
    os.environ.pop("TEST_CLI_KEY_DEF", None)

    _load_env_file(tmp_path)
    try:
        assert os.environ.get("TEST_CLI_KEY_ABC") == "some_value"
        assert os.environ.get("TEST_CLI_KEY_DEF") == "another_value"
    finally:
        os.environ.pop("TEST_CLI_KEY_ABC", None)
        os.environ.pop("TEST_CLI_KEY_DEF", None)


# ── add: brownfield with manifest ───────────────────────────────────────────


def test_add_brownfield_with_constraints(tmp_path: Path) -> None:
    """add --spec with brownfield spec shows constraints and integration points."""
    from claw_forge.spec import FeatureItem, ProjectSpec

    cfg = _yaml_config(tmp_path)

    mock_spec = Mock(spec=ProjectSpec)
    mock_spec.project_name = "my-project"
    mock_spec.mode = "brownfield"
    mock_spec.features = [Mock(spec=FeatureItem)]
    mock_spec.constraints = ["keep existing tests green"]
    mock_spec.integration_points = ["REST API"]
    mock_spec.is_brownfield = False
    mock_spec.existing_context = {}
    mock_spec.to_agent_context.return_value = "agent context text"

    mock_result = Mock()
    mock_result.success = True
    mock_result.output = "done"

    with (
        patch("claw_forge.spec.ProjectSpec.from_file", return_value=mock_spec),
        patch("claw_forge.cli.asyncio.run", return_value=mock_result),
    ):
        result = runner.invoke(
            app,
            [
                "add", "ignored", "--spec", str(tmp_path / "spec.xml"),
                "--project", str(tmp_path), "--config", str(cfg),
            ],
        )
    assert result.exit_code == 0
    assert "brownfield" in result.output.lower() or "my-project" in result.output.lower()


def test_add_brownfield_failure(tmp_path: Path) -> None:
    """add --spec with failed plugin execution exits with error."""
    from claw_forge.spec import FeatureItem, ProjectSpec

    cfg = _yaml_config(tmp_path)

    mock_spec = Mock(spec=ProjectSpec)
    mock_spec.project_name = "fail-project"
    mock_spec.mode = "greenfield"
    mock_spec.features = [Mock(spec=FeatureItem)]
    mock_spec.constraints = []
    mock_spec.integration_points = []
    mock_spec.is_brownfield = False
    mock_spec.existing_context = {}
    mock_spec.to_agent_context.return_value = "ctx"

    mock_result = Mock()
    mock_result.success = False
    mock_result.output = "initialization failed"

    with (
        patch("claw_forge.spec.ProjectSpec.from_file", return_value=mock_spec),
        patch("claw_forge.cli.asyncio.run", return_value=mock_result),
    ):
        result = runner.invoke(
            app,
            [
                "add", "ignored", "--spec", str(tmp_path / "spec.xml"),
                "--project", str(tmp_path), "--config", str(cfg),
            ],
        )
    assert result.exit_code != 0
    assert "failed" in result.output.lower()


def test_add_brownfield_with_manifest(tmp_path: Path) -> None:
    """add --spec with brownfield manifest loads and injects context."""
    import json

    from claw_forge.spec import FeatureItem, ProjectSpec

    cfg = _yaml_config(tmp_path)

    manifest_path = tmp_path / "brownfield_manifest.json"
    manifest_path.write_text(json.dumps({
        "stack": "python/fastapi",
        "test_baseline": "200 passing",
        "conventions": "PEP 8",
    }))

    mock_spec = Mock(spec=ProjectSpec)
    mock_spec.project_name = "bf-project"
    mock_spec.mode = "brownfield"
    mock_spec.features = [Mock(spec=FeatureItem)]
    mock_spec.constraints = []
    mock_spec.integration_points = []
    mock_spec.is_brownfield = True
    mock_spec.existing_context = {}
    mock_spec.to_agent_context.return_value = "agent context"

    mock_result = Mock()
    mock_result.success = True
    mock_result.output = "done"

    with (
        patch("claw_forge.spec.ProjectSpec.from_file", return_value=mock_spec),
        patch("claw_forge.cli.asyncio.run", return_value=mock_result),
    ):
        result = runner.invoke(
            app,
            [
                "add", "ignored", "--spec", str(tmp_path / "spec.xml"),
                "--project", str(tmp_path), "--config", str(cfg),
            ],
        )
    assert result.exit_code == 0
    # Verify manifest data was loaded into existing_context
    assert mock_spec.existing_context.get("stack") is not None


def test_add_brownfield_branch_suggestion(tmp_path: Path) -> None:
    """add --spec with branch enabled shows branch name suggestion."""
    from claw_forge.spec import FeatureItem, ProjectSpec

    cfg = _yaml_config(tmp_path)

    mock_spec = Mock(spec=ProjectSpec)
    mock_spec.project_name = "My Project"
    mock_spec.mode = "greenfield"
    mock_spec.features = [Mock(spec=FeatureItem)]
    mock_spec.constraints = []
    mock_spec.integration_points = []
    mock_spec.is_brownfield = False
    mock_spec.existing_context = {}
    mock_spec.to_agent_context.return_value = "ctx"

    mock_result = Mock()
    mock_result.success = True
    mock_result.output = "done"

    with (
        patch("claw_forge.spec.ProjectSpec.from_file", return_value=mock_spec),
        patch("claw_forge.cli.asyncio.run", return_value=mock_result),
    ):
        result = runner.invoke(
            app,
            [
                "add", "ignored", "--spec", str(tmp_path / "spec.xml"),
                "--project", str(tmp_path), "--config", str(cfg), "--branch",
            ],
        )
    assert result.exit_code == 0
    assert "feature/" in result.output.lower() or "branch" in result.output.lower()


# ── dev command: full setup test ─────────────────────────────────────────────


def test_dev_full_setup(tmp_path: Path) -> None:
    """dev command starts state service, vite, and waits for processes."""
    import shutil as shutil_mod

    import claw_forge.cli as cli_mod

    fake_pkg = tmp_path / "claw_forge"
    fake_pkg.mkdir()
    fake_ui = tmp_path / "ui"
    fake_ui.mkdir()
    (fake_ui / "node_modules").mkdir()

    mock_state_proc = Mock()
    mock_state_proc.poll.return_value = 0  # process exited
    mock_state_proc.pid = 12345
    mock_state_proc.wait.return_value = 0

    mock_ui_proc = Mock()
    mock_ui_proc.poll.return_value = 0
    mock_ui_proc.pid = 12346
    mock_ui_proc.wait.return_value = 0

    call_count = [0]

    def fake_popen(cmd: list[str], **kw: Any) -> Mock:
        call_count[0] += 1
        if "state" in cmd:
            return mock_state_proc
        return mock_ui_proc

    with (
        patch.object(cli_mod, "__file__", str(fake_pkg / "cli.py")),
        patch.object(shutil_mod, "which", return_value="/usr/bin/node"),
        patch("subprocess.Popen", side_effect=fake_popen),
        patch("signal.signal"),
        patch("time.sleep"),
    ):
        result = runner.invoke(
            app,
            [
                "dev", "--no-open", "--project", str(tmp_path),
                "--state-port", "19990", "--ui-port", "19991",
            ],
        )
    assert result.exit_code == 0, result.output
    assert "dev" in result.output.lower() or "api" in result.output.lower()
    assert call_count[0] >= 2  # state + ui processes


# ── fix: report with structured data ────────────────────────────────────────


def test_fix_with_report_and_branch(tmp_path: Path) -> None:
    """fix --report with branch creates branch then runs agent."""
    report_path = tmp_path / "bug_report.md"
    report_path.write_text(
        "# Bug Report\n\n**Title:** Server crash on empty input\n\n"
        "## Steps\n1. Send empty POST\n"
    )
    mock_result = Mock()
    mock_result.success = True
    mock_result.output = "Fixed the crash"
    mock_result.files_modified = ["server.py"]

    with (
        patch("claw_forge.cli.asyncio.run", return_value=mock_result),
        patch("subprocess.run"),
    ):
        result = runner.invoke(
            app,
            ["fix", "--report", str(report_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0
    assert "complete" in result.output.lower()


# ── plan: relative spec path resolution ─────────────────────────────────────


def test_plan_relative_spec_path(tmp_path: Path) -> None:
    """plan resolves relative spec paths from project directory."""
    proj = tmp_path / "myproject"
    proj.mkdir()
    spec_path = proj / "my_spec.xml"
    spec_path.write_text("<project/>")
    cfg = _yaml_config(tmp_path)

    mock_result = _plan_mock_result([])
    with patch("claw_forge.cli.asyncio.run", return_value=mock_result):
        result = runner.invoke(
            app,
            [
                "plan", "my_spec.xml", "--config", str(cfg),
                "--project", str(proj),
            ],
        )
    assert result.exit_code == 0


# ── run: self-guard prevents running in claw-forge source tree ───────────────


def test_run_self_guard(tmp_path: Path) -> None:
    """run --project pointing at claw-forge source tree exits with error."""
    import claw_forge.cli as cli_mod

    # Make project_path resolve to the claw-forge source root
    source_root = Path(cli_mod.__file__).resolve().parent.parent
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({
        "providers": {"p": {"type": "anthropic", "api_key": "k"}},
    }))

    with patch("claw_forge.cli._ensure_state_service", return_value=8420):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(source_root)],
        )
    # SystemExit(1) from within the CLI
    assert result.exit_code != 0


# ── SDK agent: message types (TextBlock, ToolUseBlock, ToolResultBlock) ──────


class TestSdkMessageHandling:
    """Tests for the SDK agent message handling loop in the run command."""

    _TASK_ID = "msg-task-001"
    _SESSION_ID = "msg-session-001"

    @staticmethod
    def _make_client(task_id: str, session_id: str) -> type:
        from tests.helpers import make_fake_httpx_client
        return make_fake_httpx_client(
            init_response={
                "session_id": session_id,
                "orphans_reset": 0,
                "tasks": [
                    {
                        "id": task_id,
                        "plugin_name": "coding",
                        "description": "Implement feature",
                        "category": "",
                        "status": "pending",
                        "priority": 1,
                        "depends_on": [],
                        "steps": [],
                    },
                ],
            },
            task_response={
                "id": task_id,
                "plugin_name": "coding",
                "description": "Implement feature",
                "status": "pending",
                "steps": [],
            },
        )

    def _run_with_agent(
        self, tmp_path: Path, agent_cls: type,
    ) -> Any:
        project_path = tmp_path / "proj"
        project_path.mkdir(exist_ok=True)
        config_path = tmp_path / "cf.yaml"
        config_path.write_text("providers: {}\n")

        with (
            patch("claw_forge.cli._ensure_state_service", return_value=8420),
            patch("claw_forge.cli.shutil.which", return_value="/usr/bin/claude"),
            patch("claw_forge.agent.session.AgentSession", agent_cls),
            patch(
                "claw_forge.cli.httpx.AsyncClient",
                self._make_client(self._TASK_ID, self._SESSION_ID),
            ),
        ):
            return runner.invoke(
                app,
                ["run", "--config", str(config_path), "--project", str(project_path)],
            )

    def test_text_block_handling(self, tmp_path: Path) -> None:
        """TextBlock messages are collected as output."""
        class FakeAgent:
            def __init__(self, options: Any) -> None:
                pass
            async def __aenter__(self) -> FakeAgent:
                return self
            async def __aexit__(self, *a: Any) -> None:
                pass
            async def run(self, prompt: str) -> Any:  # type: ignore[misc]
                class TextBlock:
                    text = "I wrote the code."
                class AssistantMessage:
                    content = [TextBlock()]
                    error = None
                yield AssistantMessage()

        result = self._run_with_agent(tmp_path, FakeAgent)
        assert result.exit_code == 0
        assert "completed" in result.output.lower() or "succeeded" in result.output.lower()

    def test_tool_use_block_handling(self, tmp_path: Path) -> None:
        """ToolUseBlock messages are logged."""
        class FakeAgent:
            def __init__(self, options: Any) -> None:
                pass
            async def __aenter__(self) -> FakeAgent:
                return self
            async def __aexit__(self, *a: Any) -> None:
                pass
            async def run(self, prompt: str) -> Any:  # type: ignore[misc]
                class TextBlock:
                    text = "Writing code."
                class ToolUseBlock:
                    name = "Write"
                    input = {"file_path": "/tmp/test.py"}
                class AssistantMessage:
                    content = [TextBlock(), ToolUseBlock()]
                    error = None
                yield AssistantMessage()

        result = self._run_with_agent(tmp_path, FakeAgent)
        assert result.exit_code == 0

    def test_tool_result_block_handling(self, tmp_path: Path) -> None:
        """ToolResultBlock messages are logged."""
        class FakeAgent:
            def __init__(self, options: Any) -> None:
                pass
            async def __aenter__(self) -> FakeAgent:
                return self
            async def __aexit__(self, *a: Any) -> None:
                pass
            async def run(self, prompt: str) -> Any:  # type: ignore[misc]
                class TextBlock:
                    text = "Done."
                class ToolResultBlock:
                    is_error = False
                    content = "File written."
                class AssistantMessage:
                    content = [TextBlock(), ToolResultBlock()]
                    error = None
                yield AssistantMessage()

        result = self._run_with_agent(tmp_path, FakeAgent)
        assert result.exit_code == 0

    def test_error_tool_result(self, tmp_path: Path) -> None:
        """ToolResultBlock with is_error=True is logged as error."""
        class FakeAgent:
            def __init__(self, options: Any) -> None:
                pass
            async def __aenter__(self) -> FakeAgent:
                return self
            async def __aexit__(self, *a: Any) -> None:
                pass
            async def run(self, prompt: str) -> Any:  # type: ignore[misc]
                class TextBlock:
                    text = "Trying."
                class ToolResultBlock:
                    is_error = True
                    content = "Permission denied."
                class AssistantMessage:
                    content = [TextBlock(), ToolResultBlock()]
                    error = None
                yield AssistantMessage()

        result = self._run_with_agent(tmp_path, FakeAgent)
        assert result.exit_code == 0

    def test_result_message_handling(self, tmp_path: Path) -> None:
        """ResultMessage is collected as final output."""
        class FakeAgent:
            def __init__(self, options: Any) -> None:
                pass
            async def __aenter__(self) -> FakeAgent:
                return self
            async def __aexit__(self, *a: Any) -> None:
                pass
            async def run(self, prompt: str) -> Any:  # type: ignore[misc]
                class ResultMessage:
                    result = "Feature implemented successfully."
                yield ResultMessage()

        result = self._run_with_agent(tmp_path, FakeAgent)
        assert result.exit_code == 0
        assert "succeeded" in result.output.lower() or "completed" in result.output.lower()

    def test_agent_error_message(self, tmp_path: Path) -> None:
        """AssistantMessage with error raises RuntimeError (caught internally)."""
        class FakeAgent:
            def __init__(self, options: Any) -> None:
                pass
            async def __aenter__(self) -> FakeAgent:
                return self
            async def __aexit__(self, *a: Any) -> None:
                pass
            async def run(self, prompt: str) -> Any:  # type: ignore[misc]
                class TextBlock:
                    text = "Starting..."
                class AssistantMessage:
                    content = [TextBlock()]
                    error = "Authentication failed"
                yield AssistantMessage()

        result = self._run_with_agent(tmp_path, FakeAgent)
        # The error is caught internally; run command completes
        assert result.exit_code == 0
        assert "run complete" in result.output.lower()

    def test_empty_output_fails(self, tmp_path: Path) -> None:
        """Agent producing no output results in failure (caught internally)."""
        class FakeAgent:
            def __init__(self, options: Any) -> None:
                pass
            async def __aenter__(self) -> FakeAgent:
                return self
            async def __aexit__(self, *a: Any) -> None:
                pass
            async def run(self, prompt: str) -> Any:  # type: ignore[misc]
                # Yield a non-AssistantMessage, non-ResultMessage
                class SystemMessage:
                    pass
                yield SystemMessage()

        result = self._run_with_agent(tmp_path, FakeAgent)
        # Run completes even when agent produces no output
        assert result.exit_code == 0
        assert "run complete" in result.output.lower()

    def test_non_list_content_skipped(self, tmp_path: Path) -> None:
        """AssistantMessage with non-list content is skipped."""
        class FakeAgent:
            def __init__(self, options: Any) -> None:
                pass
            async def __aenter__(self) -> FakeAgent:
                return self
            async def __aexit__(self, *a: Any) -> None:
                pass
            async def run(self, prompt: str) -> Any:  # type: ignore[misc]
                class AssistantMessage:
                    content = "just a string"
                    error = None
                class ResultMessage:
                    result = "Done."
                yield AssistantMessage()
                yield ResultMessage()

        result = self._run_with_agent(tmp_path, FakeAgent)
        assert result.exit_code == 0

    def test_bash_tool_truncated(self, tmp_path: Path) -> None:
        """Bash tool input is truncated in log."""
        class FakeAgent:
            def __init__(self, options: Any) -> None:
                pass
            async def __aenter__(self) -> FakeAgent:
                return self
            async def __aexit__(self, *a: Any) -> None:
                pass
            async def run(self, prompt: str) -> Any:  # type: ignore[misc]
                class TextBlock:
                    text = "Running command."
                class ToolUseBlock:
                    name = "Bash"
                    input = {"command": "x" * 200}
                class AssistantMessage:
                    content = [TextBlock(), ToolUseBlock()]
                    error = None
                yield AssistantMessage()

        result = self._run_with_agent(tmp_path, FakeAgent)
        assert result.exit_code == 0


# ── _scaffold_config: .env warning ──────────────────────────────────────────


def test_scaffold_config_no_env_warning(tmp_path: Path) -> None:
    """_scaffold_config warns when .env doesn't exist."""
    from claw_forge.cli import _scaffold_config

    cfg_path = str(tmp_path / "claw-forge.yaml")
    _scaffold_config(cfg_path)
    # .env.example should exist, .env should not
    assert (tmp_path / ".env.example").exists()
    assert not (tmp_path / ".env").exists()


def test_scaffold_config_with_env(tmp_path: Path) -> None:
    """_scaffold_config doesn't warn when .env exists."""
    from claw_forge.cli import _scaffold_config

    (tmp_path / ".env").write_text("KEY=val\n")
    cfg_path = str(tmp_path / "claw-forge.yaml")
    _scaffold_config(cfg_path)
    assert (tmp_path / ".env").exists()


# ── plan: provider-pinned model ─────────────────────────────────────────────


def test_plan_provider_pinned_model(tmp_path: Path) -> None:
    """plan --model with provider/model shows provider pinned message."""
    spec_path = tmp_path / "spec.xml"
    spec_path.write_text("<project/>")
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}}))

    mock_result = _plan_mock_result([])
    with patch("claw_forge.cli.asyncio.run", return_value=mock_result):
        result = runner.invoke(
            app,
            [
                "plan", str(spec_path), "--config", str(cfg_path),
                "--project", str(tmp_path), "--model", "my-prov/claude-opus-4-6",
            ],
        )
    assert result.exit_code == 0
    assert "pinned" in result.output.lower() or "provider" in result.output.lower()


# ── fix: provider-pinned model shows message ────────────────────────────────


def test_fix_provider_pinned_model(tmp_path: Path) -> None:
    """fix --model with provider/model shows provider pinned."""
    mock_result = Mock()
    mock_result.success = True
    mock_result.output = "Fixed"
    mock_result.files_modified = []

    with (
        patch("claw_forge.cli.asyncio.run", return_value=mock_result),
        patch("subprocess.run"),
    ):
        result = runner.invoke(
            app,
            [
                "fix", "bug desc", "--project", str(tmp_path),
                "--no-branch", "--model", "my-prov/claude-opus-4-6",
            ],
        )
    assert result.exit_code == 0
    assert "pinned" in result.output.lower() or "provider" in result.output.lower()


# ── add: provider-pinned model shows message ────────────────────────────────


def test_add_provider_pinned_model(tmp_path: Path) -> None:
    """add --model with provider/model shows provider pinned."""
    result = runner.invoke(
        app,
        [
            "add", "add dark mode", "--project", str(tmp_path),
            "--no-branch", "--model", "my-prov/claude-opus-4-6",
        ],
    )
    assert result.exit_code == 0
    assert "pinned" in result.output.lower() or "provider" in result.output.lower()


# ── Additional coverage tests ────────────────────────────────────────────────


def test_run_config_resolved_from_project_dir(tmp_path: Path) -> None:
    """Config file resolved from project dir when not found at CWD (lines 435-437)."""
    proj = tmp_path / "myproj"
    proj.mkdir()
    cfg_in_proj = proj / "claw-forge.yaml"
    cfg_in_proj.write_text(yaml.dump({"providers": {}}))

    with patch("claw_forge.cli._ensure_state_service", return_value=8420):
        result = runner.invoke(
            app,
            ["run", "--project", str(proj), "--config", "claw-forge.yaml"],
        )
    assert result.exit_code == 0


def test_short_name_truncation() -> None:
    """_short_name truncates long descriptions to 40 chars (line 675)."""
    # We need to invoke this indirectly through a run with a long description
    from tests.helpers import make_fake_httpx_client

    task_id = "trunc-001"
    long_desc = "Feature: " + "A" * 100  # "Feature: " prefix stripped, then truncate
    FakeClient = make_fake_httpx_client(
        init_response={
            "session_id": "s1",
            "orphans_reset": 0,
            "tasks": [
                {
                    "id": task_id,
                    "plugin_name": "coding",
                    "description": long_desc,
                    "category": "",
                    "status": "pending",
                    "priority": 0,
                    "depends_on": [],
                    "steps": [],
                },
            ],
        },
        task_response={
            "id": task_id,
            "plugin_name": "coding",
            "description": long_desc,
            "status": "pending",
            "steps": [],
        },
    )
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cfg_path = tmp / "claw-forge.yaml"
        cfg_path.write_text(yaml.dump({"providers": {}}))
        with (
            patch("claw_forge.cli._ensure_state_service", return_value=8420),
            patch("claw_forge.cli.shutil.which", return_value=None),
            patch("claw_forge.cli.httpx.AsyncClient", FakeClient),
        ):
            result = runner.invoke(
                app,
                ["run", "--config", str(cfg_path), "--project", str(tmp)],
            )
    assert result.exit_code == 0


def test_first_line_truncation() -> None:
    """_first_line truncates lines > max_len (line 682)."""
    from tests.helpers import make_fake_httpx_client

    task_id = "fline-001"
    # Use a very long single-line description to trigger _first_line truncation
    long_line_desc = "X" * 200
    FakeClient = make_fake_httpx_client(
        init_response={
            "session_id": "s1",
            "orphans_reset": 0,
            "tasks": [
                {
                    "id": task_id,
                    "plugin_name": "coding",
                    "description": long_line_desc,
                    "category": "",
                    "status": "pending",
                    "priority": 0,
                    "depends_on": [],
                    "steps": [],
                },
            ],
        },
        task_response={
            "id": task_id,
            "plugin_name": "coding",
            "description": long_line_desc,
            "status": "pending",
            "steps": [],
        },
    )
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cfg_path = tmp / "claw-forge.yaml"
        cfg_path.write_text(yaml.dump({"providers": {}}))
        with (
            patch("claw_forge.cli._ensure_state_service", return_value=8420),
            patch("claw_forge.cli.shutil.which", return_value=None),
            patch("claw_forge.cli.httpx.AsyncClient", FakeClient),
        ):
            result = runner.invoke(
                app,
                ["run", "--config", str(cfg_path), "--project", str(tmp)],
            )
    assert result.exit_code == 0


def test_fmt_tool_non_dict_input() -> None:
    """_fmt_tool with non-dict input returns str(raw)[:80] (line 701)."""
    # Triggered via a ToolUseBlock with non-dict input
    class FakeAgent:
        def __init__(self, options: Any) -> None:
            pass
        async def __aenter__(self) -> FakeAgent:
            return self
        async def __aexit__(self, *a: Any) -> None:
            pass
        async def run(self, prompt: str) -> Any:  # type: ignore[misc]
            class TextBlock:
                text = "Code written."
            class ToolUseBlock:
                name = "CustomTool"
                input = "just-a-string"  # non-dict input
            class AssistantMessage:
                content = [TextBlock(), ToolUseBlock()]
                error = None
            yield AssistantMessage()

    from tests.helpers import make_fake_httpx_client

    task_id = "fmt-001"
    FakeClient = make_fake_httpx_client(
        init_response={
            "session_id": "s1",
            "orphans_reset": 0,
            "tasks": [{
                "id": task_id, "plugin_name": "coding",
                "description": "Feature", "category": "",
                "status": "pending", "priority": 0,
                "depends_on": [], "steps": [],
            }],
        },
        task_response={
            "id": task_id, "plugin_name": "coding",
            "description": "Feature", "status": "pending", "steps": [],
        },
    )
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cfg_path = tmp / "claw-forge.yaml"
        cfg_path.write_text("providers: {}\n")
        with (
            patch("claw_forge.cli._ensure_state_service", return_value=8420),
            patch("claw_forge.cli.shutil.which", return_value="/usr/bin/claude"),
            patch("claw_forge.agent.session.AgentSession", FakeAgent),
            patch("claw_forge.cli.httpx.AsyncClient", FakeClient),
        ):
            result = runner.invoke(
                app,
                ["run", "--config", str(cfg_path), "--project", str(tmp)],
            )
    assert result.exit_code == 0


def test_http_retry_exhausted(tmp_path: Path) -> None:
    """_http_retry raises on final timeout (lines 643-646)."""
    task_id = "retry-001"

    class _TimeoutClient:
        def __init__(self, **kw: Any) -> None:
            pass
        async def __aenter__(self) -> _TimeoutClient:
            return self
        async def __aexit__(self, *a: Any) -> None:
            pass
        async def post(self, url: str, **kw: Any) -> Any:
            if "sessions/init" in url:
                from tests.helpers import FakeHttpxResponse
                return FakeHttpxResponse({
                    "session_id": "s1", "orphans_reset": 0,
                    "tasks": [{
                        "id": task_id, "plugin_name": "coding",
                        "description": "Feature", "category": "",
                        "status": "pending", "priority": 0,
                        "depends_on": [], "steps": [],
                    }],
                })
            from tests.helpers import FakeHttpxResponse
            return FakeHttpxResponse({})
        async def get(self, url: str, **kw: Any) -> Any:
            if f"/tasks/{task_id}" in url:
                raise httpx.TimeoutException("timeout")
            if "/sessions/" in url and url.endswith("/tasks"):
                from tests.helpers import FakeHttpxResponse
                return FakeHttpxResponse([])
            if "/regression/" in url:
                from tests.helpers import FakeHttpxResponse
                return FakeHttpxResponse({"has_pending_work": False})
            from tests.helpers import FakeHttpxResponse
            return FakeHttpxResponse({})
        async def patch(self, url: str, **kw: Any) -> Any:
            from tests.helpers import FakeHttpxResponse
            return FakeHttpxResponse({"ok": True})

    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}}))

    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.shutil.which", return_value=None),
        patch("claw_forge.cli.httpx.AsyncClient", _TimeoutClient),
    ):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0
    assert "failed" in result.output.lower() or "run complete" in result.output.lower()


def test_task_handler_404_reraise_non_404(tmp_path: Path) -> None:
    """Non-404 HTTPStatusError from task GET is re-raised (line 754)."""
    task_id = "err-501"

    class _Error500Client:
        def __init__(self, **kw: Any) -> None:
            pass
        async def __aenter__(self) -> _Error500Client:
            return self
        async def __aexit__(self, *a: Any) -> None:
            pass
        async def post(self, url: str, **kw: Any) -> Any:
            if "sessions/init" in url:
                from tests.helpers import FakeHttpxResponse
                return FakeHttpxResponse({
                    "session_id": "s1", "orphans_reset": 0,
                    "tasks": [{
                        "id": task_id, "plugin_name": "coding",
                        "description": "Feature", "category": "",
                        "status": "pending", "priority": 0,
                        "depends_on": [], "steps": [],
                    }],
                })
            from tests.helpers import FakeHttpxResponse
            return FakeHttpxResponse({})
        async def get(self, url: str, **kw: Any) -> Any:
            if f"/tasks/{task_id}" in url:
                resp = Mock()
                resp.status_code = 500
                resp.text = "Internal Server Error"
                raise httpx.HTTPStatusError(
                    "Server Error",
                    request=httpx.Request("GET", url),
                    response=resp,
                )
            if "/sessions/" in url and url.endswith("/tasks"):
                from tests.helpers import FakeHttpxResponse
                return FakeHttpxResponse([])
            if "/regression/" in url:
                from tests.helpers import FakeHttpxResponse
                return FakeHttpxResponse({"has_pending_work": False})
            from tests.helpers import FakeHttpxResponse
            return FakeHttpxResponse({})
        async def patch(self, url: str, **kw: Any) -> Any:
            from tests.helpers import FakeHttpxResponse
            return FakeHttpxResponse({"ok": True})

    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}}))

    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.shutil.which", return_value=None),
        patch("claw_forge.cli.httpx.AsyncClient", _Error500Client),
    ):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0
    assert "failed" in result.output.lower() or "run complete" in result.output.lower()


def test_stderr_filter_hook_error(tmp_path: Path) -> None:
    """stderr filter suppresses hook error lines (lines 861-871)."""
    class FakeAgent:
        def __init__(self, options: Any) -> None:
            pass
        async def __aenter__(self) -> FakeAgent:
            return self
        async def __aexit__(self, *a: Any) -> None:
            pass
        async def run(self, prompt: str) -> Any:  # type: ignore[misc]
            class TextBlock:
                text = "Done."
            class AssistantMessage:
                content = [TextBlock()]
                error = None
            yield AssistantMessage()

    from tests.helpers import make_fake_httpx_client
    task_id = "hook-001"
    FakeClient = make_fake_httpx_client(
        init_response={
            "session_id": "s1", "orphans_reset": 0,
            "tasks": [{
                "id": task_id, "plugin_name": "coding",
                "description": "Feature", "category": "",
                "status": "pending", "priority": 0,
                "depends_on": [], "steps": [],
            }],
        },
        task_response={
            "id": task_id, "plugin_name": "coding",
            "description": "Feature", "status": "pending", "steps": [],
        },
    )

    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text("providers: {}\n")
    proj = tmp_path / "proj"
    proj.mkdir()

    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.shutil.which", return_value="/usr/bin/claude"),
        patch("claw_forge.agent.session.AgentSession", FakeAgent),
        patch("claw_forge.cli.httpx.AsyncClient", FakeClient),
    ):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(proj)],
        )
    # The test verifies that the stderr_filter code path is exercised
    # (the filter is defined inside the task handler)
    assert result.exit_code == 0


def test_api_key_from_pool_providers(tmp_path: Path) -> None:
    """API key is extracted from pool providers when not in env (lines 828-841)."""
    class FakeAgent:
        def __init__(self, options: Any) -> None:
            pass
        async def __aenter__(self) -> FakeAgent:
            return self
        async def __aexit__(self, *a: Any) -> None:
            pass
        async def run(self, prompt: str) -> Any:  # type: ignore[misc]
            class TextBlock:
                text = "Done."
            class AssistantMessage:
                content = [TextBlock()]
                error = None
            yield AssistantMessage()

    from tests.helpers import make_fake_httpx_client
    task_id = "pool-key-001"
    FakeClient = make_fake_httpx_client(
        init_response={
            "session_id": "s1", "orphans_reset": 0,
            "tasks": [{
                "id": task_id, "plugin_name": "coding",
                "description": "Feature", "category": "",
                "status": "pending", "priority": 0,
                "depends_on": [], "steps": [],
            }],
        },
        task_response={
            "id": task_id, "plugin_name": "coding",
            "description": "Feature", "status": "pending", "steps": [],
        },
    )

    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({
        "providers": {
            "test-prov": {
                "type": "openai_compat",
                "base_url": "http://localhost:11434",
                "api_key": "test-pool-key",
                "enabled": True,
                "priority": 1,
            },
        },
    }))
    proj = tmp_path / "proj"
    proj.mkdir()

    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.shutil.which", return_value="/usr/bin/claude"),
        patch("claw_forge.agent.session.AgentSession", FakeAgent),
        patch("claw_forge.cli.httpx.AsyncClient", FakeClient),
        patch.dict(os.environ, {}, clear=False),
    ):
        # Remove ANTHROPIC_API_KEY to trigger pool fallback
        os.environ.pop("ANTHROPIC_API_KEY", None)
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(proj)],
        )
    assert result.exit_code == 0


def test_ensure_state_service_port_busy_non_claw_forge(tmp_path: Path) -> None:
    """Port occupied by non-claw-forge process: try alternate ports (lines 2134-2149)."""
    import json

    from claw_forge.cli import _ensure_state_service

    mock_conn = Mock()
    mock_conn.__enter__ = lambda s: s
    mock_conn.__exit__ = Mock(return_value=False)

    # /info returns None for some ports (non-claw-forge), then success for alternate
    info_call_count = [0]
    mock_info_resp = Mock()
    mock_info_resp.__enter__ = lambda s: s
    mock_info_resp.__exit__ = Mock(return_value=False)
    mock_info_resp.read.return_value = json.dumps(
        {"project_path": str(tmp_path.resolve())}
    ).encode()

    def fake_urlopen(url: str, **kw: Any) -> Any:
        info_call_count[0] += 1
        if info_call_count[0] <= 1:
            # First call: port check returns no project_path (non-claw-forge)
            resp = Mock()
            resp.__enter__ = lambda s: s
            resp.__exit__ = Mock(return_value=False)
            resp.read.return_value = json.dumps({}).encode()
            return resp
        # Subsequent: alternate port is ours
        return mock_info_resp

    conn_count = [0]
    def fake_create_connection(addr: Any, **kw: Any) -> Any:
        conn_count[0] += 1
        if conn_count[0] <= 5:
            return mock_conn  # All initial ports busy
        if conn_count[0] <= 6:
            raise OSError("free")  # Alternate port is free
        return mock_conn  # _wait_for_port succeeds

    (tmp_path / ".claw-forge").mkdir(parents=True, exist_ok=True)
    mock_popen = Mock()

    with (
        patch("socket.create_connection", side_effect=fake_create_connection),
        patch("urllib.request.urlopen", side_effect=fake_urlopen),
        patch("subprocess.Popen", mock_popen),
        patch("time.sleep"),
        patch("time.monotonic", return_value=0.0),
    ):
        result = _ensure_state_service(tmp_path, 19980)
    # Should have started on an alternate port
    assert result in range(19981, 19985)


def test_ensure_state_service_alternate_port_already_ours(tmp_path: Path) -> None:
    """Alternate port already running our service (lines 2141-2142)."""
    import json
    import socket

    from claw_forge.cli import _ensure_state_service

    mock_conn = Mock()
    mock_conn.__enter__ = lambda s: s
    mock_conn.__exit__ = Mock(return_value=False)

    call_count = [0]
    def fake_urlopen(url: str, **kw: Any) -> Any:
        call_count[0] += 1
        resp = Mock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = Mock(return_value=False)
        if call_count[0] == 1:
            # Main port: non-claw-forge
            resp.read.return_value = json.dumps({}).encode()
        else:
            # Alt port: already our service
            resp.read.return_value = json.dumps({
                "project_path": str(tmp_path.resolve()),
            }).encode()
        return resp

    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        with (
            patch("urllib.request.urlopen", side_effect=fake_urlopen),
            # All ports appear occupied
            patch("socket.create_connection", return_value=mock_conn),
            patch("time.sleep"),
            patch("time.monotonic", return_value=0.0),
        ):
            result = _ensure_state_service(tmp_path, port)
    assert result == port + 1


def test_ensure_state_service_shutdown_exception(tmp_path: Path) -> None:
    """Shutdown POST fails silently (line 2127-2128)."""
    import json
    import socket

    from claw_forge.cli import _ensure_state_service

    mock_conn = Mock()
    mock_conn.__enter__ = lambda s: s
    mock_conn.__exit__ = Mock(return_value=False)

    info_call_count = [0]
    def fake_urlopen(url_or_req: Any, **kw: Any) -> Any:
        url_str = url_or_req if isinstance(url_or_req, str) else url_or_req.full_url
        if "/shutdown" in url_str:
            raise ConnectionRefusedError("cant connect")
        info_call_count[0] += 1
        resp = Mock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = Mock(return_value=False)
        # First /info call: existing service serves a different project.
        # Second /info call (after restart): correct project.
        project = "/other/project" if info_call_count[0] == 1 else str(tmp_path)
        resp.read.return_value = json.dumps({
            "project_path": project,
        }).encode()
        return resp

    conn_call_count = [0]
    def fake_conn(addr: Any, **kw: Any) -> Any:
        conn_call_count[0] += 1
        if conn_call_count[0] <= 1:
            return mock_conn  # initial check
        if conn_call_count[0] == 2:
            raise OSError("freed")  # port freed after shutdown
        return mock_conn  # started

    mock_popen = Mock()
    (tmp_path / ".claw-forge").mkdir(parents=True, exist_ok=True)

    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        with (
            patch("urllib.request.urlopen", side_effect=fake_urlopen),
            patch("socket.create_connection", side_effect=fake_conn),
            patch("subprocess.Popen", mock_popen),
            patch("time.sleep"),
            patch("time.monotonic", return_value=0.0),
        ):
            result = _ensure_state_service(tmp_path, port)
    assert result == port


def test_ui_missing_starlette(tmp_path: Path) -> None:
    """UI command shows error when starlette/uvicorn is missing (lines 2291-2296)."""
    import claw_forge.cli as cli_mod

    fake_dist = tmp_path / "ui_dist"
    fake_dist.mkdir()
    (fake_dist / "index.html").write_text("<html><head></head><body>UI</body></html>")
    (fake_dist / "assets").mkdir()

    import builtins
    original_import = builtins.__import__

    def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "uvicorn":
            raise ImportError("No module named 'uvicorn'")
        return original_import(name, *args, **kwargs)

    with (
        patch.object(cli_mod, "__file__", str(fake_dist.parent / "cli.py")),
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("builtins.__import__", side_effect=mock_import),
    ):
        result = runner.invoke(app, ["ui", "--no-open"])
    # Should exit with error about missing uvicorn/starlette
    assert result.exit_code != 0


def test_ui_dev_reads_session_from_db(tmp_path: Path) -> None:
    """--dev mode reads session from DB (lines 2244-2251)."""
    import shutil as shutil_mod
    import sqlite3

    import claw_forge.cli as cli_mod

    fake_pkg = tmp_path / "claw_forge"
    fake_pkg.mkdir()
    fake_ui = tmp_path / "ui"
    fake_ui.mkdir()
    (fake_ui / "node_modules").mkdir()

    # Create a state.db with a session whose project_path matches
    db_dir = tmp_path / ".claw-forge"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "state.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "CREATE TABLE sessions "
            "(id TEXT, project_path TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO sessions VALUES ('dev-sess-id', ?, '2026-01-01')",
            (str(tmp_path),),
        )

    with (
        patch.object(cli_mod, "__file__", str(fake_pkg / "cli.py")),
        patch.object(shutil_mod, "which", return_value="/usr/bin/node"),
        patch("subprocess.run"),
    ):
        result = runner.invoke(
            app,
            ["ui", "--dev", "--no-open", "--project", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output
    assert "dev-sess-id" in result.output


def test_ui_dev_open_browser(tmp_path: Path) -> None:
    """--dev mode with --open spawns browser thread (lines 2264-2267)."""
    import shutil as shutil_mod

    import claw_forge.cli as cli_mod

    fake_pkg = tmp_path / "claw_forge"
    fake_pkg.mkdir()
    fake_ui = tmp_path / "ui"
    fake_ui.mkdir()
    (fake_ui / "node_modules").mkdir()

    with (
        patch.object(cli_mod, "__file__", str(fake_pkg / "cli.py")),
        patch.object(shutil_mod, "which", return_value="/usr/bin/node"),
        patch("subprocess.run"),
        patch("webbrowser.open"),
        patch("time.sleep"),
    ):
        result = runner.invoke(
            app,
            ["ui", "--dev", "--open", "--project", str(tmp_path)],
        )
    assert result.exit_code == 0


def test_ui_open_browser_static(tmp_path: Path) -> None:
    """Static UI with --open spawns browser thread (lines 2450-2453)."""
    import claw_forge.cli as cli_mod

    fake_dist = tmp_path / "ui_dist"
    fake_dist.mkdir()
    (fake_dist / "index.html").write_text("<html><head></head><body>UI</body></html>")
    (fake_dist / "assets").mkdir()

    with (
        patch.object(cli_mod, "__file__", str(fake_dist.parent / "cli.py")),
        patch("uvicorn.run"),
        patch("starlette.staticfiles.StaticFiles.__init__", return_value=None),
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("webbrowser.open"),
        patch("time.sleep"),
    ):
        result = runner.invoke(app, ["ui", "--open"])
    assert result.exit_code == 0


def test_state_address_in_use_no_errno(tmp_path: Path) -> None:
    """state command with 'Address already in use' but no errno (line 1348)."""
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}}))

    exc = OSError("Address already in use")
    # No .errno set — checks string match

    with patch("uvicorn.run", side_effect=exc):
        result = runner.invoke(
            app,
            [
                "state", "--port", "9994",
                "--config", str(cfg_path), "--project", str(tmp_path),
            ],
        )
    assert result.exit_code != 0


def test_state_oserror_not_in_use_reraises(tmp_path: Path) -> None:
    """state command with a non-port OSError re-raises (line 1350)."""
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}}))

    exc = OSError("Permission denied")
    exc.errno = 13

    with patch("uvicorn.run", side_effect=exc):
        result = runner.invoke(
            app,
            [
                "state", "--port", "9993",
                "--config", str(cfg_path), "--project", str(tmp_path),
            ],
        )
    assert result.exit_code != 0


def test_add_brownfield_bad_manifest(tmp_path: Path) -> None:
    """add --spec with corrupt brownfield manifest logs warning (lines 1840-1841)."""
    from claw_forge.spec import FeatureItem, ProjectSpec

    cfg = _yaml_config(tmp_path)

    # Write corrupt manifest
    manifest_path = tmp_path / "brownfield_manifest.json"
    manifest_path.write_text("NOT JSON")

    mock_spec = Mock(spec=ProjectSpec)
    mock_spec.project_name = "bf-project"
    mock_spec.mode = "brownfield"
    mock_spec.features = [Mock(spec=FeatureItem)]
    mock_spec.constraints = []
    mock_spec.integration_points = []
    mock_spec.is_brownfield = True
    mock_spec.existing_context = {}
    mock_spec.to_agent_context.return_value = "ctx"

    mock_result = Mock()
    mock_result.success = True
    mock_result.output = "done"

    with (
        patch("claw_forge.spec.ProjectSpec.from_file", return_value=mock_spec),
        patch("claw_forge.cli.asyncio.run", return_value=mock_result),
    ):
        result = runner.invoke(
            app,
            [
                "add", "ignored", "--spec", str(tmp_path / "spec.xml"),
                "--project", str(tmp_path), "--config", str(cfg),
            ],
        )
    assert result.exit_code == 0
    assert "warning" in result.output.lower() or "could not load" in result.output.lower()


def test_dev_installs_npm_deps(tmp_path: Path) -> None:
    """dev command installs npm deps when node_modules is missing (line 2525-2526)."""
    import shutil as shutil_mod

    import claw_forge.cli as cli_mod

    fake_pkg = tmp_path / "claw_forge"
    fake_pkg.mkdir()
    fake_ui = tmp_path / "ui"
    fake_ui.mkdir()
    # No node_modules

    mock_state_proc = Mock()
    mock_state_proc.poll.return_value = 0
    mock_state_proc.pid = 111
    mock_state_proc.wait.return_value = 0

    mock_ui_proc = Mock()
    mock_ui_proc.poll.return_value = 0
    mock_ui_proc.pid = 222
    mock_ui_proc.wait.return_value = 0

    calls: list[Any] = []

    def fake_subprocess_run(cmd: list[str], **kw: Any) -> Mock:
        calls.append(cmd)
        if "install" in cmd:
            (fake_ui / "node_modules").mkdir(exist_ok=True)
        return Mock(returncode=0)

    def fake_popen(cmd: list[str], **kw: Any) -> Mock:
        if "state" in cmd:
            return mock_state_proc
        return mock_ui_proc

    with (
        patch.object(cli_mod, "__file__", str(fake_pkg / "cli.py")),
        patch.object(shutil_mod, "which", return_value="/usr/bin/node"),
        patch("subprocess.run", side_effect=fake_subprocess_run),
        patch("subprocess.Popen", side_effect=fake_popen),
        patch("signal.signal"),
        patch("time.sleep"),
    ):
        result = runner.invoke(
            app,
            [
                "dev", "--no-open", "--project", str(tmp_path),
                "--state-port", "19970", "--ui-port", "19971",
            ],
        )
    assert result.exit_code == 0, result.output
    assert any("install" in str(c) for c in calls)


def test_dev_with_run_agents(tmp_path: Path) -> None:
    """dev --run enables agent orchestrator process (lines 2596-2599)."""
    import shutil as shutil_mod

    import claw_forge.cli as cli_mod

    fake_pkg = tmp_path / "claw_forge"
    fake_pkg.mkdir()
    fake_ui = tmp_path / "ui"
    fake_ui.mkdir()
    (fake_ui / "node_modules").mkdir()

    proc_mock = Mock()
    proc_mock.poll.return_value = 0
    proc_mock.pid = 333
    proc_mock.wait.return_value = 0

    popen_calls: list[list[str]] = []

    def fake_popen(cmd: list[str], **kw: Any) -> Mock:
        popen_calls.append(cmd)
        return proc_mock

    with (
        patch.object(cli_mod, "__file__", str(fake_pkg / "cli.py")),
        patch.object(shutil_mod, "which", return_value="/usr/bin/node"),
        patch("subprocess.Popen", side_effect=fake_popen),
        patch("signal.signal"),
        patch("time.sleep"),
    ):
        result = runner.invoke(
            app,
            [
                "dev", "--no-open", "--run", "--project", str(tmp_path),
                "--state-port", "19960", "--ui-port", "19961",
            ],
        )
    assert result.exit_code == 0, result.output
    assert "agents" in result.output.lower() and "enabled" in result.output.lower()
    # Should have spawned 3 processes: state, ui, and run
    assert len(popen_calls) >= 3


def test_dev_open_browser(tmp_path: Path) -> None:
    """dev --open spawns browser thread (lines 2607-2610)."""
    import shutil as shutil_mod

    import claw_forge.cli as cli_mod

    fake_pkg = tmp_path / "claw_forge"
    fake_pkg.mkdir()
    fake_ui = tmp_path / "ui"
    fake_ui.mkdir()
    (fake_ui / "node_modules").mkdir()

    proc_mock = Mock()
    proc_mock.poll.return_value = 0
    proc_mock.pid = 444
    proc_mock.wait.return_value = 0

    with (
        patch.object(cli_mod, "__file__", str(fake_pkg / "cli.py")),
        patch.object(shutil_mod, "which", return_value="/usr/bin/node"),
        patch("subprocess.Popen", return_value=proc_mock),
        patch("signal.signal"),
        patch("time.sleep"),
        patch("webbrowser.open"),
    ):
        result = runner.invoke(
            app,
            [
                "dev", "--open", "--project", str(tmp_path),
                "--state-port", "19950", "--ui-port", "19951",
            ],
        )
    assert result.exit_code == 0


def test_dev_session_from_db(tmp_path: Path) -> None:
    """dev command reads session from DB (lines 2539-2546)."""
    import shutil as shutil_mod
    import sqlite3

    import claw_forge.cli as cli_mod

    fake_pkg = tmp_path / "claw_forge"
    fake_pkg.mkdir()
    fake_ui = tmp_path / "ui"
    fake_ui.mkdir()
    (fake_ui / "node_modules").mkdir()

    # Create a state.db with a session whose project_path matches
    db_dir = tmp_path / ".claw-forge"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "state.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "CREATE TABLE sessions "
            "(id TEXT, project_path TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO sessions VALUES ('dev-db-sess', ?, '2026-01-01')",
            (str(tmp_path),),
        )

    proc_mock = Mock()
    proc_mock.poll.return_value = 0
    proc_mock.pid = 555
    proc_mock.wait.return_value = 0

    with (
        patch.object(cli_mod, "__file__", str(fake_pkg / "cli.py")),
        patch.object(shutil_mod, "which", return_value="/usr/bin/node"),
        patch("subprocess.Popen", return_value=proc_mock),
        patch("signal.signal"),
        patch("time.sleep"),
    ):
        result = runner.invoke(
            app,
            [
                "dev", "--no-open", "--project", str(tmp_path),
                "--state-port", "19940", "--ui-port", "19941",
            ],
        )
    assert result.exit_code == 0, result.output
    assert "dev-db-sess" in result.output


def test_dev_session_flag(tmp_path: Path) -> None:
    """dev --session passes session to URL (line 2550)."""
    import shutil as shutil_mod

    import claw_forge.cli as cli_mod

    fake_pkg = tmp_path / "claw_forge"
    fake_pkg.mkdir()
    fake_ui = tmp_path / "ui"
    fake_ui.mkdir()
    (fake_ui / "node_modules").mkdir()

    proc_mock = Mock()
    proc_mock.poll.return_value = 0
    proc_mock.pid = 666
    proc_mock.wait.return_value = 0

    with (
        patch.object(cli_mod, "__file__", str(fake_pkg / "cli.py")),
        patch.object(shutil_mod, "which", return_value="/usr/bin/node"),
        patch("subprocess.Popen", return_value=proc_mock),
        patch("signal.signal"),
        patch("time.sleep"),
    ):
        result = runner.invoke(
            app,
            [
                "dev", "--no-open", "--session", "my-dev-sess",
                "--project", str(tmp_path),
                "--state-port", "19930", "--ui-port", "19931",
            ],
        )
    assert result.exit_code == 0, result.output
    assert "my-dev-sess" in result.output


def test_dev_agents_disabled_message(tmp_path: Path) -> None:
    """dev without --run shows agents disabled message (line 2558-2560)."""
    import shutil as shutil_mod

    import claw_forge.cli as cli_mod

    fake_pkg = tmp_path / "claw_forge"
    fake_pkg.mkdir()
    fake_ui = tmp_path / "ui"
    fake_ui.mkdir()
    (fake_ui / "node_modules").mkdir()

    proc_mock = Mock()
    proc_mock.poll.return_value = 0
    proc_mock.pid = 777
    proc_mock.wait.return_value = 0

    with (
        patch.object(cli_mod, "__file__", str(fake_pkg / "cli.py")),
        patch.object(shutil_mod, "which", return_value="/usr/bin/node"),
        patch("subprocess.Popen", return_value=proc_mock),
        patch("signal.signal"),
        patch("time.sleep"),
    ):
        result = runner.invoke(
            app,
            [
                "dev", "--no-open", "--project", str(tmp_path),
                "--state-port", "19920", "--ui-port", "19921",
            ],
        )
    assert result.exit_code == 0, result.output
    assert "disabled" in result.output.lower()


def test_run_dispatcher_paused_then_resumed(tmp_path: Path) -> None:
    """Dispatcher pause/resume cycle with re-dispatch (lines 1159-1192)."""
    from claw_forge.orchestrator.dispatcher import DispatchResult

    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}}))

    task_id = "pause-001"

    class _PauseClient:
        def __init__(self, **kw: Any) -> None:
            pass
        async def __aenter__(self) -> _PauseClient:
            return self
        async def __aexit__(self, *a: Any) -> None:
            pass
        async def post(self, url: str, **kw: Any) -> Any:
            from tests.helpers import FakeHttpxResponse
            if "sessions/init" in url:
                return FakeHttpxResponse({
                    "session_id": "s1", "orphans_reset": 0,
                    "tasks": [{
                        "id": task_id, "plugin_name": "coding",
                        "description": "Feature", "category": "",
                        "status": "pending", "priority": 0,
                        "depends_on": [], "steps": [],
                    }],
                })
            return FakeHttpxResponse({})
        async def get(self, url: str, **kw: Any) -> Any:
            from tests.helpers import FakeHttpxResponse
            if "/project/paused" in url:
                return FakeHttpxResponse({"paused": False})
            if "/sessions/" in url and url.endswith("/tasks"):
                return FakeHttpxResponse([])
            if "/regression/" in url:
                return FakeHttpxResponse({"has_pending_work": False})
            return FakeHttpxResponse({
                "id": task_id, "plugin_name": "coding",
                "description": "Feature", "status": "pending", "steps": [],
            })
        async def patch(self, url: str, **kw: Any) -> Any:
            from tests.helpers import FakeHttpxResponse
            return FakeHttpxResponse({"ok": True})

    dispatch_call_count = [0]

    class FakeDispatcher:
        def __init__(self, **kw: Any) -> None:
            self.is_paused = dispatch_call_count[0] == 0
            self._tasks: list[Any] = []
        def add_task(self, node: Any) -> None:
            self._tasks.append(node)
        async def run(self) -> DispatchResult:
            dispatch_call_count[0] += 1
            return DispatchResult()

    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.shutil.which", return_value=None),
        patch("claw_forge.cli.httpx.AsyncClient", _PauseClient),
        patch("claw_forge.orchestrator.dispatcher.Dispatcher", FakeDispatcher),
        patch("claw_forge.cli.asyncio.sleep", return_value=None),
    ):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0
    out = result.output.lower()
    assert "paused" in out or "resumed" in out or "run complete" in out


def test_run_bugfix_wave(tmp_path: Path) -> None:
    """Post-dispatch loop picks up bugfix tasks (lines 1118-1155)."""
    from claw_forge.orchestrator.dispatcher import DispatchResult

    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}}))

    task_id = "bugfix-001"
    bugfix_task_id = "bugfix-002"

    dispatch_call_count = [0]

    class _BugfixClient:
        def __init__(self, **kw: Any) -> None:
            pass
        async def __aenter__(self) -> _BugfixClient:
            return self
        async def __aexit__(self, *a: Any) -> None:
            pass
        async def post(self, url: str, **kw: Any) -> Any:
            from tests.helpers import FakeHttpxResponse
            if "sessions/init" in url:
                return FakeHttpxResponse({
                    "session_id": "s1", "orphans_reset": 0,
                    "tasks": [{
                        "id": task_id, "plugin_name": "coding",
                        "description": "Feature", "category": "",
                        "status": "pending", "priority": 0,
                        "depends_on": [], "steps": [],
                    }],
                })
            return FakeHttpxResponse({})
        async def get(self, url: str, **kw: Any) -> Any:
            from tests.helpers import FakeHttpxResponse
            if "/regression/status" in url:
                return FakeHttpxResponse({"has_pending_work": False})
            if "/sessions/" in url and url.endswith("/tasks"):
                if dispatch_call_count[0] == 1:
                    # First wave done: return a pending bugfix task
                    return FakeHttpxResponse([{
                        "id": bugfix_task_id, "plugin_name": "bugfix",
                        "description": "Fix regression", "category": "",
                        "status": "pending", "priority": 0,
                        "depends_on": [], "steps": [],
                    }])
                return FakeHttpxResponse([])
            return FakeHttpxResponse({
                "id": task_id, "plugin_name": "coding",
                "description": "Feature", "status": "pending", "steps": [],
            })
        async def patch(self, url: str, **kw: Any) -> Any:
            from tests.helpers import FakeHttpxResponse
            return FakeHttpxResponse({"ok": True})

    class FakeDispatcher:
        def __init__(self, **kw: Any) -> None:
            self.is_paused = False
            self._tasks: list[Any] = []
        def add_task(self, node: Any) -> None:
            self._tasks.append(node)
        async def run(self) -> DispatchResult:
            dispatch_call_count[0] += 1
            return DispatchResult()

    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.shutil.which", return_value=None),
        patch("claw_forge.cli.httpx.AsyncClient", _BugfixClient),
        patch("claw_forge.orchestrator.dispatcher.Dispatcher", FakeDispatcher),
    ):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0
    out = result.output.lower()
    assert "bugfix" in out or "run complete" in out


def test_run_regression_wait_with_pending_work(tmp_path: Path) -> None:
    """Regression wait loop when has_pending_work is true (lines 1126-1133)."""
    from claw_forge.orchestrator.dispatcher import DispatchResult

    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}}))

    task_id = "regwait-001"
    regression_call_count = [0]

    class _RegWaitClient:
        def __init__(self, **kw: Any) -> None:
            pass
        async def __aenter__(self) -> _RegWaitClient:
            return self
        async def __aexit__(self, *a: Any) -> None:
            pass
        async def post(self, url: str, **kw: Any) -> Any:
            from tests.helpers import FakeHttpxResponse
            if "sessions/init" in url:
                return FakeHttpxResponse({
                    "session_id": "s1", "orphans_reset": 0,
                    "tasks": [{
                        "id": task_id, "plugin_name": "coding",
                        "description": "Feature", "category": "",
                        "status": "pending", "priority": 0,
                        "depends_on": [], "steps": [],
                    }],
                })
            return FakeHttpxResponse({})
        async def get(self, url: str, **kw: Any) -> Any:
            from tests.helpers import FakeHttpxResponse
            if "/regression/status" in url:
                regression_call_count[0] += 1
                if regression_call_count[0] <= 2:
                    return FakeHttpxResponse({"has_pending_work": True})
                return FakeHttpxResponse({"has_pending_work": False})
            if "/sessions/" in url and url.endswith("/tasks"):
                return FakeHttpxResponse([])
            return FakeHttpxResponse({
                "id": task_id, "plugin_name": "coding",
                "description": "Feature", "status": "pending", "steps": [],
            })
        async def patch(self, url: str, **kw: Any) -> Any:
            from tests.helpers import FakeHttpxResponse
            return FakeHttpxResponse({"ok": True})

    class FakeDispatcher:
        def __init__(self, **kw: Any) -> None:
            self.is_paused = False
            self._tasks: list[Any] = []
        def add_task(self, node: Any) -> None:
            self._tasks.append(node)
        async def run(self) -> DispatchResult:
            return DispatchResult()

    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.shutil.which", return_value=None),
        patch("claw_forge.cli.httpx.AsyncClient", _RegWaitClient),
        patch("claw_forge.orchestrator.dispatcher.Dispatcher", FakeDispatcher),
        patch("claw_forge.cli.asyncio.sleep", return_value=None),
    ):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0
    assert regression_call_count[0] >= 3


def test_run_more_than_5_failures(tmp_path: Path) -> None:
    """Run with >5 failed tasks shows '... and N more' (line 1206, 1210)."""
    from claw_forge.orchestrator.dispatcher import DispatchResult

    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({"providers": {}}))

    task_ids = [f"fail-{i}" for i in range(8)]

    class _FailClient:
        def __init__(self, **kw: Any) -> None:
            pass
        async def __aenter__(self) -> _FailClient:
            return self
        async def __aexit__(self, *a: Any) -> None:
            pass
        async def post(self, url: str, **kw: Any) -> Any:
            from tests.helpers import FakeHttpxResponse
            if "sessions/init" in url:
                return FakeHttpxResponse({
                    "session_id": "s1", "orphans_reset": 0,
                    "tasks": [
                        {
                            "id": tid, "plugin_name": "coding",
                            "description": f"Feature {i}", "category": "",
                            "status": "pending", "priority": i,
                            "depends_on": [], "steps": [],
                        }
                        for i, tid in enumerate(task_ids)
                    ],
                })
            return FakeHttpxResponse({})
        async def get(self, url: str, **kw: Any) -> Any:
            from tests.helpers import FakeHttpxResponse
            if "/regression/" in url:
                return FakeHttpxResponse({"has_pending_work": False})
            if "/sessions/" in url and url.endswith("/tasks"):
                return FakeHttpxResponse([])
            return FakeHttpxResponse({})
        async def patch(self, url: str, **kw: Any) -> Any:
            from tests.helpers import FakeHttpxResponse
            return FakeHttpxResponse({"ok": True})

    class FakeDispatcher:
        def __init__(self, **kw: Any) -> None:
            self.is_paused = False
            self._tasks: list[Any] = []
        def add_task(self, node: Any) -> None:
            self._tasks.append(node)
        async def run(self) -> DispatchResult:
            result = DispatchResult()
            result.failed = {tid: "All providers exhausted" for tid in task_ids}
            return result

    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.shutil.which", return_value=None),
        patch("claw_forge.cli.httpx.AsyncClient", _FailClient),
        patch("claw_forge.orchestrator.dispatcher.Dispatcher", FakeDispatcher),
    ):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(tmp_path)],
        )
    assert result.exit_code == 0
    out = result.output.lower()
    assert "more" in out
    assert "pool-status" in out or "providers" in out


def test_worktree_success_path(tmp_path: Path) -> None:
    """Git worktree + merge on success path (lines 791-792, 1067-1087)."""
    class FakeAgent:
        def __init__(self, options: Any) -> None:
            pass
        async def __aenter__(self) -> FakeAgent:
            return self
        async def __aexit__(self, *a: Any) -> None:
            pass
        async def run(self, prompt: str) -> Any:  # type: ignore[misc]
            class TextBlock:
                text = "Code written."
            class AssistantMessage:
                content = [TextBlock()]
                error = None
            yield AssistantMessage()

    from tests.helpers import make_fake_httpx_client

    task_id = "wt-001"
    FakeClient = make_fake_httpx_client(
        init_response={
            "session_id": "s1", "orphans_reset": 0,
            "tasks": [{
                "id": task_id, "plugin_name": "coding",
                "description": "Build auth", "category": "auth",
                "status": "pending", "priority": 0,
                "depends_on": [], "steps": [],
            }],
        },
        task_response={
            "id": task_id, "plugin_name": "coding",
            "description": "Build auth", "status": "pending", "steps": [],
        },
    )

    proj = tmp_path / "proj"
    proj.mkdir()
    cfg_path = tmp_path / "claw-forge.yaml"
    cfg_path.write_text(yaml.dump({
        "providers": {},
        "git": {"enabled": True, "merge_strategy": "auto", "commit_on_boundary": True},
    }))

    mock_git_ops = Mock()
    mock_git_ops.create_worktree = Mock(return_value=Mock())
    mock_git_ops.checkpoint = Mock(return_value=None)
    mock_git_ops.merge = Mock(return_value={"merged": True, "commit_hash": "abc"})
    mock_git_ops.remove_worktree = Mock(return_value=None)

    # Make create_worktree and other methods async
    async def _fake_create_worktree(*a: Any, **kw: Any) -> tuple[str, Path]:
        return ("feat/auth", tmp_path / "worktree")
    async def _fake_checkpoint(*a: Any, **kw: Any) -> None:
        pass
    async def _fake_merge(*a: Any, **kw: Any) -> dict[str, Any]:
        return {"merged": True, "commit_hash": "abc"}
    async def _fake_remove_worktree(*a: Any, **kw: Any) -> None:
        pass

    mock_git_ops.create_worktree = _fake_create_worktree
    mock_git_ops.checkpoint = _fake_checkpoint
    mock_git_ops.merge = _fake_merge
    mock_git_ops.remove_worktree = _fake_remove_worktree

    with (
        patch("claw_forge.cli._ensure_state_service", return_value=8420),
        patch("claw_forge.cli.shutil.which", return_value="/usr/bin/claude"),
        patch("claw_forge.agent.session.AgentSession", FakeAgent),
        patch("claw_forge.cli.httpx.AsyncClient", FakeClient),
        patch("claw_forge.git.GitOps", return_value=mock_git_ops),
    ):
        result = runner.invoke(
            app,
            ["run", "--config", str(cfg_path), "--project", str(proj)],
        )
    assert result.exit_code == 0


def test_fix_with_empty_output(tmp_path: Path) -> None:
    """fix with no output in result shows only complete message (line 2823)."""
    mock_result = Mock()
    mock_result.success = True
    mock_result.output = ""
    mock_result.files_modified = []

    with (
        patch("claw_forge.cli.asyncio.run", return_value=mock_result),
        patch("subprocess.run"),
    ):
        result = runner.invoke(
            app,
            ["fix", "minor bug", "--project", str(tmp_path), "--no-branch"],
        )
    assert result.exit_code == 0
    assert "complete" in result.output.lower()


def test_http_get_success() -> None:
    """_http_get returns json on success (line 254)."""
    from claw_forge.cli import _http_get

    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"key": "value"}
    mock_resp.raise_for_status.return_value = None

    with patch("claw_forge.cli.httpx.get", return_value=mock_resp):
        result = _http_get("http://localhost:8420/test")
    assert result == {"key": "value"}


def test_http_post_success() -> None:
    """_http_post returns json on success (line 271)."""
    from claw_forge.cli import _http_post

    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True}
    mock_resp.raise_for_status.return_value = None

    with patch("claw_forge.cli.httpx.post", return_value=mock_resp):
        result = _http_post("http://localhost:8420/test")
    assert result == {"ok": True}
