"""Tests for the --github-mode flag in claw_forge.cli.run."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from claw_forge.cli import app

runner = CliRunner()


def test_github_mode_invalid_format() -> None:
    """--github-mode with bad format exits with code 1."""
    result = runner.invoke(app, ["run", "--github-mode", "badformat"])
    assert result.exit_code == 1
    assert "Invalid --github-mode" in result.output or result.exit_code != 0


def test_github_mode_no_slash_exits() -> None:
    """Format without / exits with error."""
    result = runner.invoke(app, ["run", "--github-mode", "noslash#15"])
    assert result.exit_code == 1


def test_github_mode_no_hash_exits() -> None:
    """Format without # exits with error."""
    result = runner.invoke(app, ["run", "--github-mode", "owner/repo"])
    assert result.exit_code == 1


def test_github_mode_non_integer_issue_exits() -> None:
    """Issue number must be an integer."""
    result = runner.invoke(app, ["run", "--github-mode", "owner/repo#abc"])
    assert result.exit_code == 1


def test_github_mode_missing_token(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Missing GITHUB_TOKEN exits with code 1."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    # Write a minimal config file to pass _load_config
    cfg = tmp_path / "claw-forge.yaml"
    cfg.write_text("providers: {}\nagent: {}\n")

    result = runner.invoke(
        app,
        [
            "run",
            "--config", str(cfg),
            "--project", str(tmp_path),
            "--github-mode", "owner/repo#5",
        ],
    )
    assert result.exit_code == 1
    assert "GITHUB_TOKEN" in result.output


def test_github_mode_help_text() -> None:
    """--github-mode flag is visible in --help output."""
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "github-mode" in result.output
