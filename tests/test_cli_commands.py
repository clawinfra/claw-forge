"""Tests for claw_forge CLI commands."""

from __future__ import annotations

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
        mock_resp = Mock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = Mock(return_value=False)
        mock_resp.read.return_value = json.dumps(
            {"project_path": wrong_project}
        ).encode()

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
