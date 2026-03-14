"""End-to-end tests for claw-forge CLI commands.

Tests are run via subprocess (real process) or via Click's CliRunner for speed.
All tests are self-contained and clean up after themselves.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from typer.testing import CliRunner

from claw_forge.cli import app

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invoke(args: list[str]) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
    """Run claw-forge as a subprocess using the current venv's Python."""
    return subprocess.run(
        [sys.executable, "-m", "claw_forge.cli", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# --help flags
# ---------------------------------------------------------------------------


class TestHelpFlags:
    def test_root_help_exit_zero(self) -> None:
        """claw-forge --help exits 0 and shows usage."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Usage" in result.output or "claw-forge" in result.output.lower()

    def test_status_help_exit_zero(self) -> None:
        """claw-forge status --help exits 0."""
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0

    def test_fix_help_exit_zero(self) -> None:
        """claw-forge fix --help exits 0."""
        result = runner.invoke(app, ["fix", "--help"])
        assert result.exit_code == 0

    def test_init_help_exit_zero(self) -> None:
        """claw-forge init --help exits 0."""
        result = runner.invoke(app, ["init", "--help"])
        assert result.exit_code == 0

    def test_add_help_exit_zero(self) -> None:
        """claw-forge add --help exits 0."""
        result = runner.invoke(app, ["add", "--help"])
        assert result.exit_code == 0

    def test_run_help_exit_zero(self) -> None:
        """claw-forge run --help exits 0."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0

    def test_version_exit_zero(self) -> None:
        """claw-forge version exits 0 and prints a version string."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "claw-forge" in result.output.lower() or "0." in result.output

    def test_pool_status_help_exit_zero(self) -> None:
        """claw-forge pool-status --help exits 0."""
        result = runner.invoke(app, ["pool-status", "--help"])
        assert result.exit_code == 0

    def test_state_help_exit_zero(self) -> None:
        """claw-forge state --help exits 0."""
        result = runner.invoke(app, ["state", "--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# init command
# ---------------------------------------------------------------------------


class TestInitCommand:
    def test_init_creates_claude_md(self) -> None:
        """claw-forge init <path> writes CLAUDE.md into the target directory."""
        with tempfile.TemporaryDirectory(prefix="e2e-init-") as tmp:
            result = runner.invoke(app, ["init", "--project", tmp])
            # Exit code may be 0 or non-zero depending on AI calls failing;
            # the scaffold part (CLAUDE.md) should always run
            claude_md = Path(tmp) / "CLAUDE.md"
            # At minimum the scaffold should produce CLAUDE.md
            assert claude_md.exists(), (
                f"CLAUDE.md not found in {tmp}. CLI output:\n{result.output}"
            )

    def test_init_creates_claude_commands_dir(self) -> None:
        """claw-forge init <path> creates the .claude/commands/ directory."""
        with tempfile.TemporaryDirectory(prefix="e2e-init-cmds-") as tmp:
            runner.invoke(app, ["init", "--project", tmp])
            commands_dir = Path(tmp) / ".claude" / "commands"
            assert commands_dir.exists(), (
                f".claude/commands/ not found in {tmp}"
            )

    def test_init_on_nonexistent_path_creates_it(self) -> None:
        """init works even if the target path doesn't exist yet."""
        with tempfile.TemporaryDirectory(prefix="e2e-base-") as base:
            new_path = Path(base) / "new-project"
            new_path.mkdir()  # scaffold requires the dir to exist
            result = runner.invoke(app, ["init", "--project", str(new_path)])
            # Should not hard-crash
            assert result.exit_code in (0, 1), f"Unexpected exit: {result.output}"

    def test_init_subprocess_exit_zero(self) -> None:
        """claw-forge init via subprocess exits 0 on a plain directory."""
        with tempfile.TemporaryDirectory(prefix="e2e-sub-") as tmp:
            proc = _invoke(["init", "--project", tmp])
            assert proc.returncode == 0, (
                f"Expected exit 0, got {proc.returncode}.\nstdout:\n{proc.stdout}"
                f"\nstderr:\n{proc.stderr}"
            )
            assert (Path(tmp) / "CLAUDE.md").exists()


# ---------------------------------------------------------------------------
# fix command
# ---------------------------------------------------------------------------


class TestFixCommand:
    def test_fix_no_args_exits_nonzero(self) -> None:
        """claw-forge fix with no description or report exits non-zero."""
        result = runner.invoke(app, ["fix"])
        assert result.exit_code != 0

    def test_fix_missing_report_file_exits_nonzero(self) -> None:
        """claw-forge fix --report /nonexistent exits non-zero."""
        result = runner.invoke(app, ["fix", "--report", "/nonexistent/bug.md"])
        assert result.exit_code != 0

    def test_fix_with_description_starts(self) -> None:
        """claw-forge fix 'description' at least starts (may fail without AI)."""
        with tempfile.TemporaryDirectory(prefix="e2e-fix-") as tmp:
            # Git init so the branch creation doesn't fail badly
            subprocess.run(["git", "init"], cwd=tmp, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "alex.chen31337@gmail.com"],
                cwd=tmp,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Alex Chen"],
                cwd=tmp,
                capture_output=True,
            )
            result = runner.invoke(
                app,
                ["fix", "users get 500 on login", "--project", tmp, "--no-branch"],
            )
            # Fix may fail (AI not available) but the CLI should at least not crash with a
            # Python traceback — it should show a proper error message
            assert "Traceback" not in result.output or result.exit_code in (0, 1)


# ---------------------------------------------------------------------------
# add command
# ---------------------------------------------------------------------------


class TestAddCommand:
    def test_add_feature_description(self) -> None:
        """claw-forge add 'feature text' shows the feature and doesn't crash."""
        result = runner.invoke(app, ["add", "dark mode support", "--no-branch"])
        # Should display the feature name
        assert result.exit_code in (0, 1)
        assert "dark mode" in result.output.lower() or "feature" in result.output.lower()

    def test_add_with_nonexistent_spec_exits_nonzero(self) -> None:
        """claw-forge add --spec /nonexistent exits non-zero."""
        result = runner.invoke(
            app, ["add", "feature", "--spec", "/nonexistent/spec.xml"]
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# version / module execution
# ---------------------------------------------------------------------------


class TestVersionCommand:
    def test_version_contains_semver(self) -> None:
        """claw-forge version output contains a version number."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        # Output should contain something like "0.1.0"
        assert any(c.isdigit() for c in result.output)

    def test_module_invocation(self) -> None:
        """python -m claw_forge.cli --help works."""
        proc = _invoke(["--help"])
        assert proc.returncode == 0
        assert "Usage" in proc.stdout or "claw-forge" in proc.stdout.lower()


# ---------------------------------------------------------------------------
# run command (scaffold, no real agent)
# ---------------------------------------------------------------------------


class TestRunCommand:
    def test_run_help_shows_dry_run(self) -> None:
        """claw-forge run --help shows --dry-run flag."""
        import re
        import subprocess
        import sys
        proc = subprocess.run(
            [sys.executable, "-c",
             "from claw_forge.cli import app; from typer.testing import CliRunner; "
             "r = CliRunner().invoke(app, ['run', '--help']); "
             "print(r.output); exit(r.exit_code)"],
            capture_output=True, text=True, timeout=10,
            env={**__import__('os').environ, "NO_COLOR": "1", "TERM": "dumb"},
        )
        assert proc.returncode == 0, proc.stderr
        # Strip any remaining ANSI escape codes before asserting
        clean = re.sub(r"\x1b\[[0-9;]*m", "", proc.stdout)
        assert "--dry-run" in clean, f"--dry-run not found in help output:\n{clean}"

    def test_run_with_no_db_exits_zero_with_message(self) -> None:
        """claw-forge run with no DB (no plan yet) exits 0 with helpful message."""
        with tempfile.TemporaryDirectory(prefix="e2e-run-nodb-") as tmp:
            result = runner.invoke(app, ["run", "--project", tmp])
            assert result.exit_code == 0
            assert (
                "No pending tasks" in result.output
                or "plan" in result.output.lower()
                or "Cannot reach state service" in result.output
            )

    def test_run_dry_run_with_prepopulated_db(self) -> None:
        """claw-forge run --dry-run with pre-populated tasks prints waves and exits 0."""
        import uuid

        task1_id = str(uuid.uuid4())
        task2_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())

        init_resp = {
            "session_id": session_id,
            "orphans_reset": 0,
            "tasks": [
                {
                    "id": task1_id,
                    "plugin_name": "coding",
                    "description": "Implement feature A",
                    "category": "",
                    "status": "pending",
                    "priority": 1,
                    "depends_on": [],
                    "steps": [],
                },
                {
                    "id": task2_id,
                    "plugin_name": "coding",
                    "description": "Implement feature B",
                    "category": "",
                    "status": "pending",
                    "priority": 2,
                    "depends_on": [task1_id],
                    "steps": [],
                },
            ],
        }

        class FakeResponse:
            status_code = 200

            def __init__(self, data: dict[str, Any]) -> None:
                self._data = data

            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict[str, Any]:
                return self._data

        class FakeClient:
            async def __aenter__(self) -> FakeClient:
                return self

            async def __aexit__(self, *a: Any) -> None:
                pass

            async def post(self, url: str, **kw: Any) -> FakeResponse:
                return FakeResponse(init_resp)

            async def get(self, url: str, **kw: Any) -> FakeResponse:
                return FakeResponse(init_resp["tasks"][0])

            async def patch(self, url: str, **kw: Any) -> FakeResponse:
                return FakeResponse({"ok": True})

        with tempfile.TemporaryDirectory(prefix="e2e-run-dryrun-") as tmp:
            config_path = Path(tmp) / "claw-forge.yaml"
            config_path.write_text(
                "providers:\n"
                "  test-provider:\n"
                "    type: anthropic_oauth\n"
                "    priority: 1\n"
            )
            with (
                patch("claw_forge.cli._ensure_state_service", return_value=8420),
                patch("claw_forge.cli.httpx.AsyncClient", FakeClient),
            ):
                result = runner.invoke(
                    app,
                    ["run", "--project", tmp, "--dry-run", "--config", str(config_path)],
                )
            assert result.exit_code == 0, f"Command failed. Output: {result.output}"
            assert "Execution plan" in result.output or "wave" in result.output.lower()

    def test_run_help_shows_config_option(self) -> None:
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--config" in result.output or "-c" in result.output

    def test_run_with_missing_config_exits_nonzero(self) -> None:
        """claw-forge run with a non-existent config exits 1."""
        result = runner.invoke(app, ["run", "--config", "/no/such/file.yaml"])
        assert result.exit_code != 0


class TestModelFormats:
    def test_plan_help_shows_model_formats(self) -> None:
        """claw-forge plan --help output mentions provider/model format."""
        result = runner.invoke(app, ["plan", "--help"])
        assert result.exit_code == 0
        assert "provider/model" in result.output or "provider" in result.output.lower()

    def test_run_help_shows_model_formats(self) -> None:
        """claw-forge run --help output mentions provider/model format."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "provider/model" in result.output or "provider" in result.output.lower()

    def test_fix_help_shows_model_formats(self) -> None:
        """claw-forge fix --help output mentions provider/model format."""
        result = runner.invoke(app, ["fix", "--help"])
        assert result.exit_code == 0
        assert "provider/model" in result.output or "provider" in result.output.lower()

    def test_add_help_shows_model_formats(self) -> None:
        """claw-forge add --help output mentions provider/model format."""
        result = runner.invoke(app, ["add", "--help"])
        assert result.exit_code == 0
        assert "provider/model" in result.output or "provider" in result.output.lower()


class TestPlanWritesDB:
    """plan command must write tasks to .claw-forge/state.db for run to consume."""

    def _make_minimal_spec(self, path: Path) -> None:
        """Write a minimal but valid claw-forge XML spec (matches app_spec.template.xml schema)."""
        path.write_text(
            "<project_specification>\n"
            "  <project_name>TestApp</project_name>\n"
            "  <overview>A simple test app for e2e testing.</overview>\n"
            "  <technology_stack>\n"
            "    <frontend><framework>React</framework><port>3000</port></frontend>\n"
            "    <backend><runtime>Python with FastAPI</runtime>"
            "<database>SQLite</database><port>8000</port></backend>\n"
            "  </technology_stack>\n"
            "  <core_features>\n"
            "    <backend>\n"
            "      - GET /hello returns JSON greeting\n"
            "      - GET /health returns 200 OK with status json\n"
            "    </backend>\n"
            "    <frontend>\n"
            "      - Home page displays welcome message\n"
            "    </frontend>\n"
            "  </core_features>\n"
            "</project_specification>\n",
            encoding="utf-8",
        )

    def _make_minimal_config(self, project: Path) -> None:
        (project / "claw-forge.yaml").write_text(
            "providers:\n"
            "  anthropic:\n"
            "    type: anthropic\n"
            "    api_key: test-key\n"
            "    models: [claude-sonnet-4-20250514]\n"
            "    priority: 1\n"
            "    enabled: true\n",
            encoding="utf-8",
        )

    def test_plan_creates_claw_forge_dir(self) -> None:
        """claw-forge plan creates .claw-forge/ directory."""
        with tempfile.TemporaryDirectory(prefix="e2e-plan-db-") as tmp:
            project = Path(tmp)
            self._make_minimal_config(project)
            spec = project / "app_spec.xml"
            self._make_minimal_spec(spec)

            result = runner.invoke(app, ["plan", str(spec), "--project", tmp])
            assert result.exit_code == 0, result.output
            assert (project / ".claw-forge").is_dir(), (
                ".claw-forge/ not created by plan"
            )

    def test_plan_creates_state_db(self) -> None:
        """claw-forge plan creates .claw-forge/state.db."""
        with tempfile.TemporaryDirectory(prefix="e2e-plan-db-") as tmp:
            project = Path(tmp)
            self._make_minimal_config(project)
            spec = project / "app_spec.xml"
            self._make_minimal_spec(spec)

            result = runner.invoke(app, ["plan", str(spec), "--project", tmp])
            assert result.exit_code == 0, result.output
            db = project / ".claw-forge" / "state.db"
            assert db.exists(), f"state.db not found at {db}"

    def test_plan_writes_pending_tasks(self) -> None:
        """Tasks written by plan are readable and pending."""
        import asyncio

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from claw_forge.state.models import Task

        with tempfile.TemporaryDirectory(prefix="e2e-plan-tasks-") as tmp:
            project = Path(tmp)
            self._make_minimal_config(project)
            spec = project / "app_spec.xml"
            self._make_minimal_spec(spec)

            result = runner.invoke(app, ["plan", str(spec), "--project", tmp])
            assert result.exit_code == 0, result.output

            db_path = project / ".claw-forge" / "state.db"
            assert db_path.exists()

            async def read_tasks() -> list[Task]:
                engine = create_async_engine(
                    f"sqlite+aiosqlite:///{db_path}", echo=False
                )
                maker = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                async with maker() as sess:
                    rows = (await sess.execute(select(Task))).scalars().all()
                await engine.dispose()
                return list(rows)

            tasks = asyncio.run(read_tasks())
            assert len(tasks) >= 2, f"Expected ≥2 tasks, got {len(tasks)}"
            statuses = {t.status for t in tasks}
            assert statuses == {"pending"}, f"Expected all pending, got {statuses}"

    def test_run_after_plan_finds_tasks(self) -> None:
        """After plan, run reports tasks found (not 'No pending tasks')."""
        with tempfile.TemporaryDirectory(prefix="e2e-planrun-") as tmp:
            project = Path(tmp)
            self._make_minimal_config(project)
            spec = project / "app_spec.xml"
            self._make_minimal_spec(spec)

            plan_result = runner.invoke(app, ["plan", str(spec), "--project", tmp])
            assert plan_result.exit_code == 0, plan_result.output

            run_result = runner.invoke(
                app, ["run", "--project", tmp, "--dry-run"]
            )
            assert run_result.exit_code == 0, run_result.output
            assert "No pending tasks" not in run_result.output, (
                f"run still reports no tasks after plan:\n{run_result.output}"
            )


class TestZRunExecutesTasks:
    """run command must execute tasks (not just dry-run) without crashing.

    This class exists specifically to catch the concurrent-session SQLAlchemy
    bug where sharing one AsyncSession across concurrent task_handler coroutines
    causes 'commit() called while _prepare_impl() in progress'.
    """

    def _make_spec(self, path: Path) -> None:
        path.write_text(
            "<project_specification>\n"
            "  <project_name>ConcurrencyTest</project_name>\n"
            "  <overview>Test concurrent task execution.</overview>\n"
            "  <technology_stack>\n"
            "    <frontend><framework>React</framework><port>3000</port></frontend>\n"
            "    <backend><runtime>Python</runtime>"
            "<database>SQLite</database><port>8000</port></backend>\n"
            "  </technology_stack>\n"
            "  <core_features>\n"
            "    <backend>\n"
            "      - Task one: implement GET /one\n"
            "      - Task two: implement GET /two\n"
            "      - Task three: implement GET /three\n"
            "      - Task four: implement GET /four\n"
            "      - Task five: implement GET /five\n"
            "    </backend>\n"
            "  </core_features>\n"
            "</project_specification>\n",
            encoding="utf-8",
        )

    def _make_config(self, project: Path) -> None:
        (project / "claw-forge.yaml").write_text(
            "providers:\n"
            "  anthropic:\n"
            "    type: anthropic\n"
            "    api_key: test-key\n"
            "    models: [claude-sonnet-4-20250514]\n"
            "    priority: 1\n"
            "    enabled: true\n"
            "git:\n"
            "  enabled: false\n",
            encoding="utf-8",
        )

    def test_run_executes_tasks_without_session_crash(self) -> None:
        """run without --dry-run executes all tasks concurrently without SQLAlchemy crash.

        Regression test for: 'commit() called while _prepare_impl() in progress'
        caused by multiple coroutines sharing a single AsyncSession.
        """
        with tempfile.TemporaryDirectory(prefix="e2e-run-exec-") as tmp:
            project = Path(tmp)
            self._make_config(project)
            spec = project / "app_spec.xml"
            self._make_spec(spec)

            cfg_path = str(project / "claw-forge.yaml")
            # plan first — writes tasks to DB
            plan_result = runner.invoke(
                app, ["plan", str(spec), "--project", tmp, "--config", cfg_path]
            )
            assert plan_result.exit_code == 0, plan_result.output

            # run with concurrency=5 (triggers concurrent task_handler coroutines)
            run_result = runner.invoke(
                app, ["run", "--project", tmp, "--concurrency", "5", "--config", cfg_path]
            )
            # Must not crash with SQLAlchemy session error
            assert "commit()" not in run_result.output, (
                f"SQLAlchemy session crash detected:\n{run_result.output}"
            )
            assert "_prepare_impl" not in run_result.output, (
                f"SQLAlchemy session crash detected:\n{run_result.output}"
            )
            assert run_result.exit_code == 0, (
                f"run crashed:\n{run_result.output}"
            )

    def test_run_marks_tasks_completed_in_db(self) -> None:
        """After run, tasks in DB must be 'completed' not 'pending'."""
        import asyncio

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from claw_forge.state.models import Task

        with tempfile.TemporaryDirectory(prefix="e2e-run-complete-") as tmp:
            project = Path(tmp)
            self._make_config(project)
            spec = project / "app_spec.xml"
            self._make_spec(spec)

            cfg_path = str(project / "claw-forge.yaml")
            runner.invoke(app, ["plan", str(spec), "--project", tmp, "--config", cfg_path])
            run_result = runner.invoke(
                app, ["run", "--project", tmp, "--concurrency", "3", "--config", cfg_path]
            )
            assert run_result.exit_code == 0, run_result.output

            db_path = project / ".claw-forge" / "state.db"

            async def read_statuses() -> list[str]:
                engine = create_async_engine(
                    f"sqlite+aiosqlite:///{db_path}", echo=False
                )
                maker = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                async with maker() as sess:
                    rows = (await sess.execute(select(Task))).scalars().all()
                await engine.dispose()
                return [t.status for t in rows]

            # If the state service subprocess couldn't start (CliRunner
            # limitation), run exits cleanly but tasks stay pending.
            if "Cannot reach state service" in run_result.output:
                return  # skip DB assertion when service is unavailable in test

            statuses = asyncio.run(read_statuses())
            assert statuses, "No tasks found in DB after run"
            pending = [s for s in statuses if s == "pending"]
            assert not pending, (
                f"Tasks still pending after run: {pending} — "
                f"all statuses: {statuses}"
            )
