"""Tests for the bug-fix workflow: BugReport parser, BugFixPlugin, and CLI fix command."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from claw_forge.bugfix.report import BugReport
from claw_forge.cli import app
from claw_forge.plugins.base import PluginContext
from claw_forge.plugins.bugfix import BugFixPlugin

runner = CliRunner()

# ── Fixtures ──────────────────────────────────────────────────────────────────

FULL_REPORT_MD = textwrap.dedent(
    """\
    # Bug: Users get 500 on large file upload

    ## Symptoms
    - POST /upload returns 500 with no error message
    - Only happens for files > 5MB

    ## Reproduction steps
    1. Create a user account
    2. POST /upload with a 6MB file
    3. Observe 500 response

    ## Expected behaviour
    File uploads successfully, returns 200 with file URL

    ## Actual behaviour
    Server returns 500 Internal Server Error

    ## Affected scope
    - routers/upload.py
    - services/storage.py

    ## Constraints
    - Must not change the upload API contract
    - All existing tests must stay green

    ## Regression test required
    Yes

    ## Environment
    Python: 3.12
    OS: Linux
    """
)

VARIANT_REPRO_MD = textwrap.dedent(
    """\
    # Bug: Login fails

    ## Steps to reproduce
    1. Open login page
    2. Enter valid credentials
    3. Click submit

    ## Expected behavior
    User is redirected to dashboard

    ## Actual behavior
    Error page shown

    ## Regression test required
    Yes
    """
)

MISSING_SECTIONS_MD = textwrap.dedent(
    """\
    # Bug: Widget crashes

    ## Symptoms
    - App crashes on startup
    """
)

REGRESSION_NO_MD = textwrap.dedent(
    """\
    # Bug: Minor display glitch

    ## Regression test required
    No
    """
)

ENV_KV_MD = textwrap.dedent(
    """\
    # Bug: Encoding error

    ## Environment
    - Python: 3.11
    - OS: macOS 14
    - DB: PostgreSQL 15
    """
)

STAR_BULLETS_MD = textwrap.dedent(
    """\
    # Bug: Star bullet test

    ## Symptoms
    * First symptom
    * Second symptom

    ## Regression test required
    Yes
    """
)

NUMBERED_REPRO_MD = textwrap.dedent(
    """\
    # Bug: Numbered list

    ## Repro
    1. Step one
    2. Step two
    3. Step three

    ## Regression test required
    True
    """
)


# ── BugReport.from_file() ─────────────────────────────────────────────────────


def test_from_file_full_template(tmp_path: Path) -> None:
    f = tmp_path / "bug_report.md"
    f.write_text(FULL_REPORT_MD)
    report = BugReport.from_file(f)

    assert report.title == "Users get 500 on large file upload"
    assert "POST /upload returns 500 with no error message" in report.symptoms
    assert len(report.symptoms) == 2
    assert len(report.reproduction_steps) == 3
    assert "200 with file URL" in report.expected_behaviour
    assert "500 Internal Server Error" in report.actual_behaviour
    assert "routers/upload.py" in report.affected_scope
    assert "services/storage.py" in report.affected_scope
    assert "Must not change the upload API contract" in report.constraints
    assert report.regression_test_required is True
    assert report.environment["Python"] == "3.12"
    assert report.environment["OS"] == "Linux"
    assert "Users get 500" in report.raw_text


def test_from_file_steps_to_reproduce_variant(tmp_path: Path) -> None:
    f = tmp_path / "bug.md"
    f.write_text(VARIANT_REPRO_MD)
    report = BugReport.from_file(f)
    assert len(report.reproduction_steps) == 3
    assert report.reproduction_steps[0] == "Open login page"


def test_from_file_expected_behavior_american_spelling(tmp_path: Path) -> None:
    f = tmp_path / "bug.md"
    f.write_text(VARIANT_REPRO_MD)
    report = BugReport.from_file(f)
    assert "dashboard" in report.expected_behaviour


def test_from_file_missing_sections_graceful(tmp_path: Path) -> None:
    f = tmp_path / "bug.md"
    f.write_text(MISSING_SECTIONS_MD)
    report = BugReport.from_file(f)
    assert report.title == "Widget crashes"
    assert report.reproduction_steps == []
    assert report.expected_behaviour == ""
    assert report.actual_behaviour == ""
    assert report.affected_scope == []
    assert report.constraints == []
    assert report.regression_test_required is True  # default


def test_from_file_regression_yes(tmp_path: Path) -> None:
    f = tmp_path / "bug.md"
    f.write_text(FULL_REPORT_MD)
    report = BugReport.from_file(f)
    assert report.regression_test_required is True


def test_from_file_regression_no(tmp_path: Path) -> None:
    f = tmp_path / "bug.md"
    f.write_text(REGRESSION_NO_MD)
    report = BugReport.from_file(f)
    assert report.regression_test_required is False


def test_from_file_environment_kv(tmp_path: Path) -> None:
    f = tmp_path / "bug.md"
    f.write_text(ENV_KV_MD)
    report = BugReport.from_file(f)
    assert report.environment["Python"] == "3.11"
    assert report.environment["OS"] == "macOS 14"
    assert report.environment["DB"] == "PostgreSQL 15"


def test_from_description_title(tmp_path: Path) -> None:
    report = BugReport.from_description("simple bug description")
    assert report.title == "simple bug description"
    assert report.regression_test_required is True


def test_from_description_empty_lists() -> None:
    report = BugReport.from_description("another bug")
    assert report.symptoms == []
    assert report.reproduction_steps == []
    assert report.affected_scope == []
    assert report.constraints == []
    assert report.environment == {}
    assert report.expected_behaviour == ""
    assert report.actual_behaviour == ""


def test_from_file_star_bullets(tmp_path: Path) -> None:
    f = tmp_path / "bug.md"
    f.write_text(STAR_BULLETS_MD)
    report = BugReport.from_file(f)
    assert "First symptom" in report.symptoms
    assert "Second symptom" in report.symptoms


def test_from_file_numbered_list_repro(tmp_path: Path) -> None:
    f = tmp_path / "bug.md"
    f.write_text(NUMBERED_REPRO_MD)
    report = BugReport.from_file(f)
    assert report.reproduction_steps == ["Step one", "Step two", "Step three"]


def test_from_file_regression_true_keyword(tmp_path: Path) -> None:
    f = tmp_path / "bug.md"
    f.write_text(NUMBERED_REPRO_MD)
    report = BugReport.from_file(f)
    assert report.regression_test_required is True


# ── BugReport.to_agent_prompt() ───────────────────────────────────────────────


def test_to_agent_prompt_header() -> None:
    report = BugReport.from_description("Test bug")
    prompt = report.to_agent_prompt()
    assert "## Bug Report: Test bug" in prompt


def test_to_agent_prompt_contains_protocol() -> None:
    report = BugReport.from_description("Test bug")
    prompt = report.to_agent_prompt()
    assert "Reproduce → Isolate" in prompt


def test_to_agent_prompt_includes_constraints() -> None:
    report = BugReport(
        title="Test",
        constraints=["Must not change the API", "Keep tests green"],
    )
    prompt = report.to_agent_prompt()
    assert "### Constraints" in prompt
    assert "Must not change the API" in prompt


def test_to_agent_prompt_includes_affected_scope() -> None:
    report = BugReport(
        title="Test",
        affected_scope=["src/router.py", "src/service.py"],
    )
    prompt = report.to_agent_prompt()
    assert "### Affected Scope" in prompt
    assert "src/router.py" in prompt


def test_to_agent_prompt_omits_empty_symptoms() -> None:
    report = BugReport(title="Empty symptoms", symptoms=[])
    prompt = report.to_agent_prompt()
    assert "### Symptoms" not in prompt


def test_to_agent_prompt_omits_empty_reproduction_steps() -> None:
    report = BugReport(title="No repro", reproduction_steps=[])
    prompt = report.to_agent_prompt()
    assert "### Reproduction Steps" not in prompt


def test_to_agent_prompt_full_report(tmp_path: Path) -> None:
    f = tmp_path / "bug.md"
    f.write_text(FULL_REPORT_MD)
    report = BugReport.from_file(f)
    prompt = report.to_agent_prompt()
    assert "## Bug Report: Users get 500 on large file upload" in prompt
    assert "### Symptoms" in prompt
    assert "### Reproduction Steps" in prompt
    assert "### Expected Behaviour" in prompt
    assert "### Constraints" in prompt


# ── BugFixPlugin ──────────────────────────────────────────────────────────────


def test_bugfix_plugin_name() -> None:
    plugin = BugFixPlugin()
    assert plugin.name == "bugfix"


def test_bugfix_plugin_description() -> None:
    plugin = BugFixPlugin()
    assert "reproduce" in plugin.description.lower() or "fix" in plugin.description.lower()


def test_get_system_prompt_contains_reproduce() -> None:
    plugin = BugFixPlugin()
    ctx = PluginContext(project_path=".", session_id="test", task_id="test")
    prompt = plugin.get_system_prompt(ctx)
    assert "REPRODUCE" in prompt


def test_get_system_prompt_contains_isolate() -> None:
    plugin = BugFixPlugin()
    ctx = PluginContext(project_path=".", session_id="test", task_id="test")
    prompt = plugin.get_system_prompt(ctx)
    assert "ISOLATE" in prompt


def test_get_system_prompt_with_bug_report_title() -> None:
    plugin = BugFixPlugin()
    bug = BugReport.from_description("NullPointerException in payment handler")
    ctx = PluginContext(
        project_path=".",
        session_id="test",
        task_id="test",
        metadata={"bug_report": bug},
    )
    prompt = plugin.get_system_prompt(ctx)
    assert "NullPointerException in payment handler" in prompt


@pytest.mark.asyncio
async def test_execute_calls_run_agent(tmp_path: Path) -> None:
    """execute() should call run_agent with the correct parameters."""
    plugin = BugFixPlugin()
    bug = BugReport.from_description("Test bug")
    ctx = PluginContext(
        project_path=str(tmp_path),
        session_id="test",
        task_id="test",
        metadata={"bug_report": bug},
    )

    mock_message = MagicMock()
    mock_message.__class__.__name__ = "ResultMessage"

    async def _fake_run_agent(prompt: str, **kwargs: object):  # type: ignore[misc]
        yield mock_message

    with patch("claw_forge.plugins.bugfix.run_agent", side_effect=_fake_run_agent):
        result = await plugin.execute(ctx)

    assert result.success is True


@pytest.mark.asyncio
async def test_execute_missing_project_path() -> None:
    plugin = BugFixPlugin()
    ctx = PluginContext(
        project_path="/nonexistent/path/xyz",
        session_id="test",
        task_id="test",
    )
    result = await plugin.execute(ctx)
    assert result.success is False
    assert "not found" in result.output.lower() or "nonexistent" in result.output


# ── CLI: fix command ──────────────────────────────────────────────────────────


def test_fix_help() -> None:
    result = runner.invoke(app, ["fix", "--help"])
    assert result.exit_code == 0
    assert "fix" in result.output.lower()


def test_fix_no_args_shows_error() -> None:
    result = runner.invoke(app, ["fix"])
    assert result.exit_code != 0 or "provide" in result.output.lower() or "error" in result.output.lower()  # noqa: E501
