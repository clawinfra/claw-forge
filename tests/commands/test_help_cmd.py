"""Tests for the status (help_cmd) command."""

from __future__ import annotations

import asyncio
import tempfile
import uuid
from pathlib import Path

import pytest

from claw_forge.commands.help_cmd import (
    _progress_bar,
    run_help,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_config(tmp: str, *, model: str = "claude-sonnet-4-6") -> str:
    cfg = Path(tmp) / "claw-forge.yaml"
    cfg.write_text(f"model: {model}\n")
    return str(cfg)


async def _populate_db(project: Path, tasks: list[dict]) -> None:
    """Write a session + tasks directly to .claw-forge/state.db."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from claw_forge.state.models import Base, Task
    from claw_forge.state.models import Session as DbSession

    db_dir = project / ".claw-forge"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "state.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as sess:
        session_id = str(uuid.uuid4())
        db_sess = DbSession(
            id=session_id,
            project_path=str(project.resolve()),
            status="pending",
        )
        sess.add(db_sess)
        await sess.flush()
        for t in tasks:
            sess.add(Task(
                id=str(uuid.uuid4()),
                session_id=session_id,
                plugin_name=t.get("plugin_name", "coding"),
                description=t.get("description", ""),
                status=t.get("status", "pending"),
                priority=0,
                depends_on=[],
                cost_usd=t.get("cost_usd", 0.0),
                error_message=t.get("error_message"),
            ))
        await sess.commit()
    await engine.dispose()


# ── Progress bar ──────────────────────────────────────────────────────────────

class TestProgressBar:
    def test_empty(self) -> None:
        bar = _progress_bar(0, 10)
        assert "░" in bar

    def test_full(self) -> None:
        bar = _progress_bar(10, 10)
        assert bar == "█" * 20

    def test_half(self) -> None:
        bar = _progress_bar(5, 10)
        assert bar.count("█") == 10

    def test_zero_total(self) -> None:
        bar = _progress_bar(0, 0)
        assert "░" in bar

    def test_custom_width(self) -> None:
        bar = _progress_bar(3, 10, width=10)
        assert len(bar) == 10


# ── No DB (no plan yet) ───────────────────────────────────────────────────────

class TestNoPlan:
    def test_no_db_prints_guidance(self, capsys: pytest.CaptureFixture[str]) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _write_config(tmp)
            run_help(config_path=cfg, project_path=tmp)
            out = capsys.readouterr().out
            assert "plan" in out.lower()

    def test_no_config_still_works(self, capsys: pytest.CaptureFixture[str]) -> None:
        """status should not crash even if claw-forge.yaml is missing."""
        with tempfile.TemporaryDirectory() as tmp:
            run_help(config_path=str(Path(tmp) / "claw-forge.yaml"), project_path=tmp)
            out = capsys.readouterr().out
            assert "plan" in out.lower()


# ── Happy path — tasks in DB ──────────────────────────────────────────────────

class TestWithTasks:
    def _run(self, tasks: list[dict], tmp: str) -> str:
        asyncio.run(_populate_db(Path(tmp), tasks))
        cfg = _write_config(tmp)
        import sys
        from io import StringIO
        buf = StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            run_help(config_path=cfg, project_path=tmp)
        finally:
            sys.stdout = old
        return buf.getvalue()

    def test_all_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tasks = [{"status": "completed"} for _ in range(5)]
            out = self._run(tasks, tmp)
            assert "5" in out
            assert "🎉" in out or "completed" in out.lower()

    def test_mixed_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tasks = (
                [{"status": "completed"}] * 3
                + [{"status": "pending"}] * 2
                + [{"status": "failed", "error_message": "timeout"}] * 1
            )
            out = self._run(tasks, tmp)
            assert "3" in out   # completed
            assert "1" in out   # failed
            assert "Failed" in out or "failed" in out.lower()

    def test_failed_tasks_shown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tasks = [
                {"status": "failed", "description": "implement payment", "error_message": "err"}
            ]
            out = self._run(tasks, tmp)
            assert "implement payment" in out or "failed" in out.lower()

    def test_next_action_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tasks = [{"status": "pending"}] * 3
            out = self._run(tasks, tmp)
            assert "claw-forge run" in out

    def test_next_action_all_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tasks = [{"status": "completed"}] * 3
            out = self._run(tasks, tmp)
            assert "🎉" in out

    def test_cost_shown_when_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tasks = [{"status": "completed", "cost_usd": 0.05}] * 4
            out = self._run(tasks, tmp)
            assert "$" in out

    def test_progress_bar_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tasks = [{"status": "completed"}] * 2 + [{"status": "pending"}] * 2
            out = self._run(tasks, tmp)
            assert "█" in out or "░" in out

    def test_project_name_shown(self) -> None:
        with tempfile.TemporaryDirectory(prefix="myproject-") as tmp:
            tasks = [{"status": "pending"}]
            out = self._run(tasks, tmp)
            # Project dir name should appear
            assert Path(tmp).name in out

    def test_model_shown_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(_populate_db(Path(tmp), [{"status": "pending"}]))
            cfg = _write_config(tmp, model="claude-opus-4-6")
            import sys
            from io import StringIO
            buf = StringIO()
            sys.stdout, old = buf, sys.stdout
            try:
                run_help(config_path=cfg, project_path=tmp)
            finally:
                sys.stdout = old
            assert "claude-opus-4-6" in buf.getvalue()

    def test_retry_message_when_all_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tasks = [{"status": "failed", "error_message": "api error"}] * 3
            out = self._run(tasks, tmp)
            assert "run" in out.lower()

    def test_total_zero_shows_plan_message(self) -> None:
        """DB exists with 0 tasks → claw-forge plan suggested (line 149)."""
        with tempfile.TemporaryDirectory() as tmp:
            out = self._run([], tmp)
            assert "plan" in out.lower()

    def test_running_tasks_shows_running_message(self) -> None:
        """Running tasks → shows running message (lines 155-156)."""
        with tempfile.TemporaryDirectory() as tmp:
            tasks = [{"status": "running"}] * 2 + [{"status": "pending"}]
            out = self._run(tasks, tmp)
            assert "running" in out.lower() or "Agents" in out

    def test_failed_without_error_message(self) -> None:
        """Failed task with no error_message → no error line printed (141->137)."""
        with tempfile.TemporaryDirectory() as tmp:
            tasks = [{"status": "failed"}]  # no error_message
            out = self._run(tasks, tmp)
            assert "failed" in out.lower() or "Failed" in out

    def test_many_failed_tasks_truncated(self) -> None:
        """More than 5 failed tasks → shows truncation message (line 144)."""
        with tempfile.TemporaryDirectory() as tmp:
            tasks = [
                {"status": "failed", "description": f"task-{i}", "error_message": "err"}
                for i in range(7)
            ]
            out = self._run(tasks, tmp)
            assert "more" in out or "7" in out


class TestReadDbEdgeCases:
    def test_db_exists_no_session_for_project(self) -> None:
        """DB exists but no session for project → returns [] (lines 60-61)."""
        import uuid

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from claw_forge.commands.help_cmd import _read_db
        from claw_forge.state.models import Base
        from claw_forge.state.models import Session as DbSession

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            db_dir = project / ".claw-forge"
            db_dir.mkdir(parents=True)

            async def setup() -> None:
                engine = create_async_engine(
                    f"sqlite+aiosqlite:///{db_dir / 'state.db'}", echo=False
                )
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
                async with maker() as sess:
                    sess.add(DbSession(
                        id=str(uuid.uuid4()),
                        project_path="/different/project/path",
                        status="pending",
                    ))
                    await sess.commit()
                await engine.dispose()

            asyncio.run(setup())
            result = _read_db(project)
            assert result == []

    def test_db_exception_returns_none(self) -> None:
        """Exception during asyncio.run → returns None (lines 80-81)."""
        from unittest.mock import patch

        from claw_forge.commands.help_cmd import _read_db

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            db_dir = project / ".claw-forge"
            db_dir.mkdir()
            (db_dir / "state.db").touch()  # DB file exists

            with patch("asyncio.run", side_effect=RuntimeError("db error")):
                result = _read_db(project)
            assert result is None


# ── CLI integration via typer runner ─────────────────────────────────────────

class TestStatusCLI:
    def test_status_exits_zero_no_db(self) -> None:
        from typer.testing import CliRunner

        from claw_forge.cli import app
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "claw-forge.yaml").write_text("model: claude-sonnet-4-6\n")
            result = runner.invoke(app, ["status", "--project", tmp])
            assert result.exit_code == 0
            assert "plan" in result.output.lower()

    def test_status_exits_zero_with_tasks(self) -> None:
        from typer.testing import CliRunner

        from claw_forge.cli import app
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(_populate_db(
                Path(tmp),
                [{"status": "completed"}] * 2 + [{"status": "pending"}],
            ))
            (Path(tmp) / "claw-forge.yaml").write_text("model: claude-sonnet-4-6\n")
            result = runner.invoke(app, ["status", "--project", tmp])
            assert result.exit_code == 0
            assert "3" in result.output  # total tasks

    def test_status_no_serve_reference(self) -> None:
        """status must never tell users to run 'claw-forge serve' (command doesn't exist)."""
        from typer.testing import CliRunner

        from claw_forge.cli import app
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "claw-forge.yaml").write_text("")
            result = runner.invoke(app, ["status", "--project", tmp])
            assert "claw-forge serve" not in result.output
