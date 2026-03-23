"""Tests for ParallelReviewer regression testing system."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from claw_forge.orchestrator.reviewer import (
    ParallelReviewer,
    RegressionResult,
    detect_test_command,
)
from claw_forge.state.service import AgentStateService

# ── detect_test_command tests ────────────────────────────────────────────


class TestDetectTestCommand:
    """Tests for stack-specific test command detection."""

    def test_detect_npm(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{}")
        assert detect_test_command(tmp_path) == "npm test"

    def test_detect_pyproject(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        assert detect_test_command(tmp_path) == "uv run pytest"

    def test_detect_setup_py(self, tmp_path: Path) -> None:
        (tmp_path / "setup.py").write_text("setup()")
        assert detect_test_command(tmp_path) == "pytest"

    def test_detect_cargo(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text("[package]")
        assert detect_test_command(tmp_path) == "cargo test"

    def test_detect_go_mod(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module example")
        assert detect_test_command(tmp_path) == "go test ./..."

    def test_detect_makefile_with_test_target(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "Makefile").write_text(
            "all:\n\techo all\n\ntest:\n\tpytest\n"
        )
        assert detect_test_command(tmp_path) == "make test"

    def test_detect_makefile_without_test_target(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "Makefile").write_text(
            "all:\n\techo all\nbuild:\n\tcc main.c\n"
        )
        assert detect_test_command(tmp_path) is None

    def test_detect_makefile_oserror(self, tmp_path: Path) -> None:
        """OSError reading Makefile → except branch taken (lines 66-67)."""
        makefile = tmp_path / "Makefile"
        # Create a directory named "Makefile" so read_text raises an error
        makefile.mkdir()
        assert detect_test_command(tmp_path) is None

    def test_detect_unknown(self, tmp_path: Path) -> None:
        assert detect_test_command(tmp_path) is None

    def test_detect_priority_npm_over_makefile(
        self, tmp_path: Path
    ) -> None:
        """package.json wins over Makefile."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "Makefile").write_text("test:\n\tpytest\n")
        assert detect_test_command(tmp_path) == "npm test"

    def test_detect_pyproject_over_cargo(
        self, tmp_path: Path
    ) -> None:
        """pyproject.toml wins over Cargo.toml (first match)."""
        (tmp_path / "pyproject.toml").write_text("[project]")
        (tmp_path / "Cargo.toml").write_text("[package]")
        assert detect_test_command(tmp_path) == "uv run pytest"

    def test_detect_string_path(self, tmp_path: Path) -> None:
        """Accepts string paths as well as Path objects."""
        (tmp_path / "go.mod").write_text("module x")
        assert detect_test_command(str(tmp_path)) == "go test ./..."


# ── RegressionResult dataclass tests ────────────────────────────────────


class TestRegressionResult:
    """Tests for the RegressionResult dataclass."""

    def test_default_values(self) -> None:
        r = RegressionResult(passed=True, total=10, failed=0)
        assert r.passed is True
        assert r.total == 10
        assert r.failed == 0
        assert r.failed_tests == []
        assert r.duration_ms == 0
        assert r.run_number == 0
        assert r.implicated_feature_ids == []
        assert r.output == ""

    def test_to_dict(self) -> None:
        r = RegressionResult(
            passed=False,
            total=5,
            failed=2,
            failed_tests=["test_a", "test_b"],
            duration_ms=123,
            run_number=3,
            implicated_feature_ids=["1", "2"],
            output="FAILED test_a",
        )
        d = r.to_dict()
        assert d["passed"] is False
        assert d["total"] == 5
        assert d["failed"] == 2
        assert d["failed_tests"] == ["test_a", "test_b"]
        assert d["duration_ms"] == 123
        assert d["run_number"] == 3
        assert d["implicated_feature_ids"] == ["1", "2"]
        assert d["output"] == "FAILED test_a"

    def test_asdict_compatibility(self) -> None:
        r = RegressionResult(passed=True, total=1, failed=0)
        d = asdict(r)
        assert isinstance(d, dict)
        assert d["passed"] is True

    def test_failed_result(self) -> None:
        r = RegressionResult(
            passed=False,
            total=10,
            failed=3,
            failed_tests=["x::test_1", "x::test_2", "y::test_3"],
        )
        assert not r.passed
        assert len(r.failed_tests) == 3


# ── ParallelReviewer class tests ────────────────────────────────────────


class TestParallelReviewer:
    """Tests for the ParallelReviewer lifecycle."""

    def _make_service(self) -> AgentStateService:
        svc = AgentStateService(
            database_url="sqlite+aiosqlite://"
        )
        return svc

    @pytest.mark.asyncio
    async def test_start_stop(self) -> None:
        svc = self._make_service()
        try:
            reviewer = ParallelReviewer(
                project_dir="/tmp",
                state_service=svc,
                interval_features=1,
            )
            await reviewer.start()
            assert reviewer._task is not None
            assert not reviewer._task.done()
            await reviewer.stop()
            assert reviewer._task is None
        finally:
            await svc.dispose()

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self) -> None:
        svc = self._make_service()
        reviewer = ParallelReviewer(
            project_dir="/tmp",
            state_service=svc,
        )
        await reviewer.start()
        task1 = reviewer._task
        await reviewer.start()  # should not create new task
        assert reviewer._task is task1
        await reviewer.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start(self) -> None:
        svc = self._make_service()
        reviewer = ParallelReviewer(
            project_dir="/tmp",
            state_service=svc,
        )
        await reviewer.stop()  # should be safe

    def test_properties_initial(self) -> None:
        svc = self._make_service()
        reviewer = ParallelReviewer(
            project_dir="/tmp",
            state_service=svc,
        )
        assert reviewer.last_result is None
        assert reviewer.run_count == 0

    def test_interval_clamped(self) -> None:
        svc = self._make_service()
        reviewer = ParallelReviewer(
            project_dir="/tmp",
            state_service=svc,
            interval_features=0,
        )
        assert reviewer._interval == 1

    @pytest.mark.asyncio
    async def test_notify_triggers_run(self, tmp_path: Path) -> None:
        """Completing enough features triggers a test run."""
        (tmp_path / "pyproject.toml").write_text("[project]")
        svc = self._make_service()
        svc.ws_manager = Mock()
        svc.ws_manager.broadcast = AsyncMock()

        reviewer = ParallelReviewer(
            project_dir=tmp_path,
            state_service=svc,
            interval_features=1,
        )

        # Mock _run_tests to return a passing result
        mock_result = RegressionResult(
            passed=True, total=5, failed=0, run_number=1
        )
        with patch.object(
            reviewer, "_run_tests", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = mock_result
            await reviewer.start()

            reviewer.notify_feature_completed()
            # Give the loop time to process
            await asyncio.sleep(0.1)

            await reviewer.stop()

        assert mock_run.call_count >= 1
        assert reviewer.run_count >= 1


# ── _run_tests tests ────────────────────────────────────────────────────


class TestRunTests:
    """Tests for subprocess execution."""

    @pytest.mark.asyncio
    async def test_run_tests_success(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        reviewer = ParallelReviewer(
            project_dir=tmp_path,
            state_service=svc,
        )
        # Override test command to echo success
        reviewer._test_command = "echo '5 passed'"

        result = await reviewer._run_tests(1)
        assert result.passed is True
        assert result.run_number == 1
        assert result.duration_ms >= 0
        assert "5 passed" in result.output

    @pytest.mark.asyncio
    async def test_run_tests_failure(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        reviewer = ParallelReviewer(
            project_dir=tmp_path,
            state_service=svc,
        )
        reviewer._test_command = "false"

        result = await reviewer._run_tests(2)
        assert result.passed is False
        assert result.run_number == 2

    @pytest.mark.asyncio
    async def test_run_tests_timeout(self, tmp_path: Path) -> None:
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        reviewer = ParallelReviewer(
            project_dir=tmp_path,
            state_service=svc,
        )
        reviewer._test_command = "sleep 999"

        # Patch timeout to 0.1s for test speed
        with patch(
            "claw_forge.orchestrator.reviewer.asyncio.wait_for",
            side_effect=asyncio.TimeoutError,
        ):
            result = await reviewer._run_tests(3)

        assert result.passed is False
        assert "TIMEOUT" in result.failed_tests

    @pytest.mark.asyncio
    async def test_run_tests_command_not_found(
        self, tmp_path: Path
    ) -> None:
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        reviewer = ParallelReviewer(
            project_dir=tmp_path,
            state_service=svc,
        )
        reviewer._test_command = (
            "__nonexistent_command_xyz_12345__"
        )

        result = await reviewer._run_tests(4)
        assert result.passed is False
        assert "COMMAND_NOT_FOUND" in result.failed_tests


# ── _implicate_features tests ───────────────────────────────────────────


class TestImplicateFeatures:
    """Tests for heuristic feature implication."""

    def test_implicate_by_name(self) -> None:
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        reviewer = ParallelReviewer(
            project_dir="/tmp", state_service=svc
        )
        features: list[dict[str, Any]] = [
            {"id": 1, "name": "User Authentication"},
            {"id": 2, "name": "Payment Gateway"},
            {"id": 3, "name": "Email Notifications"},
        ]
        output = (
            "FAILED test_user_authentication.py::test_login\n"
            "FAILED test_payment_gateway.py::test_charge"
        )
        result = reviewer._implicate_features(output, features)
        assert "1" in result
        assert "2" in result
        assert "3" not in result

    def test_implicate_by_slug(self) -> None:
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        reviewer = ParallelReviewer(
            project_dir="/tmp", state_service=svc
        )
        features: list[dict[str, Any]] = [
            {"id": 10, "name": "API Rate Limiting"},
        ]
        output = "tests/test_api_rate_limiting.py FAILED"
        result = reviewer._implicate_features(output, features)
        assert "10" in result

    def test_implicate_empty_features(self) -> None:
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        reviewer = ParallelReviewer(
            project_dir="/tmp", state_service=svc
        )
        result = reviewer._implicate_features("FAILED xyz", [])
        assert result == []

    def test_implicate_no_match(self) -> None:
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        reviewer = ParallelReviewer(
            project_dir="/tmp", state_service=svc
        )
        features: list[dict[str, Any]] = [
            {"id": 1, "name": "Foo"},
        ]
        result = reviewer._implicate_features("bar baz", features)
        assert result == []

    def test_implicate_missing_name(self) -> None:
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        reviewer = ParallelReviewer(
            project_dir="/tmp", state_service=svc
        )
        features: list[dict[str, Any]] = [
            {"id": 1},
        ]
        result = reviewer._implicate_features("anything", features)
        assert result == []


# ── Broadcast tests ─────────────────────────────────────────────────────


class TestBroadcast:
    """Tests for regression event broadcasting."""

    @pytest.mark.asyncio
    async def test_regression_result_broadcast(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        svc.ws_manager = Mock()
        svc.ws_manager.broadcast = AsyncMock()

        reviewer = ParallelReviewer(
            project_dir=tmp_path,
            state_service=svc,
            interval_features=1,
        )
        reviewer._test_command = "echo '3 passed'"

        mock_result = RegressionResult(
            passed=True,
            total=3,
            failed=0,
            run_number=1,
            duration_ms=50,
        )

        with patch.object(
            reviewer, "_run_tests", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = mock_result
            await reviewer.start()
            reviewer.notify_feature_completed()
            await asyncio.sleep(0.15)
            await reviewer.stop()

        # Should have broadcast regression_started + regression_result
        calls = svc.ws_manager.broadcast.call_args_list
        types = [c.args[0]["type"] for c in calls]
        assert "regression_started" in types
        assert "regression_result" in types


# ── REST endpoint tests ─────────────────────────────────────────────────


class TestRegressionStatusEndpoint:
    """Tests for GET /regression/status."""

    @pytest.mark.asyncio
    async def test_no_reviewer(self) -> None:
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        app = svc.create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/regression/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_count"] == 0
        assert data["last_result"] is None

    @pytest.mark.asyncio
    async def test_with_result(self) -> None:
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        # Simulate a reviewer with a result
        mock_reviewer = Mock()
        mock_reviewer.run_count = 2
        mock_reviewer.has_pending_work = False
        mock_reviewer.last_result = RegressionResult(
            passed=True,
            total=10,
            failed=0,
            run_number=2,
            duration_ms=500,
        )
        svc._reviewer = mock_reviewer

        app = svc.create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/regression/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_count"] == 2
        assert data["last_result"]["passed"] is True
        assert data["last_result"]["total"] == 10
        assert data["has_pending_work"] is False

    @pytest.mark.asyncio
    async def test_with_failed_result(self, tmp_path: Path) -> None:
        from claw_forge.state.models import Session, Task

        db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        svc = AgentStateService(database_url=db_url)
        await svc.init_db()

        # Create tasks so the endpoint can look up implicated feature names
        async with svc._session_factory() as db:
            session = Session(project_path=str(tmp_path))
            db.add(session)
            await db.commit()
            await db.refresh(session)
            t1 = Task(
                id="task-1", session_id=session.id,
                plugin_name="coding", description="Auth",
            )
            t2 = Task(
                id="task-4", session_id=session.id,
                plugin_name="coding", description="Payments",
            )
            db.add_all([t1, t2])
            await db.commit()

        mock_reviewer = Mock()
        mock_reviewer.run_count = 5
        mock_reviewer.last_result = RegressionResult(
            passed=False,
            total=20,
            failed=3,
            failed_tests=["test_a", "test_b", "test_c"],
            run_number=5,
            duration_ms=2000,
            implicated_feature_ids=["task-1", "task-4"],
        )
        svc._reviewer = mock_reviewer

        app = svc.create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/regression/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["last_result"]["passed"] is False
        assert data["last_result"]["failed"] == 3
        assert data["last_result"]["implicated_feature_ids"] == ["task-1", "task-4"]
        assert len(data["last_result"]["implicated_features"]) == 2
        names = [f["name"] for f in data["last_result"]["implicated_features"]]
        assert "Auth" in names
        assert "Payments" in names
        await svc.dispose()


# ── _parse_output tests ─────────────────────────────────────────────────


class TestParseOutput:
    """Tests for test output parsing."""

    def test_parse_pytest_pass(self) -> None:
        output = "===== 15 passed in 2.34s ====="
        total, failed, names = ParallelReviewer._parse_output(
            output
        )
        assert total == 15
        assert failed == 0
        assert names == []

    def test_parse_pytest_mixed(self) -> None:
        output = (
            "FAILED tests/test_a.py::test_x\n"
            "FAILED tests/test_b.py::test_y\n"
            "===== 8 passed, 2 failed in 1.5s ====="
        )
        total, failed, names = ParallelReviewer._parse_output(
            output
        )
        assert total == 10
        assert failed == 2
        assert "tests/test_a.py::test_x" in names
        assert "tests/test_b.py::test_y" in names

    def test_parse_cargo_test(self) -> None:
        output = (
            "test my_mod::test_one ... ok\n"
            "test my_mod::test_two ... FAILED\n"
            "test result: FAILED. 1 passed; 1 failed; 0 ignored\n"
        )
        total, failed, names = ParallelReviewer._parse_output(
            output
        )
        assert total == 2
        assert failed == 1
        assert "my_mod::test_two" in names

    def test_parse_go_test(self) -> None:
        output = (
            "ok  \tgithub.com/x/pkg1\t0.3s\n"
            "FAIL\tgithub.com/x/pkg2\t0.1s\n"
            "ok  \tgithub.com/x/pkg3\t0.2s\n"
        )
        total, failed, names = ParallelReviewer._parse_output(
            output
        )
        assert total == 3
        assert failed == 1

    def test_parse_empty(self) -> None:
        total, failed, names = ParallelReviewer._parse_output("")
        assert total == 0
        assert failed == 0
        assert names == []

    def test_parse_pytest_collection_errors(self) -> None:
        output = (
            "ERROR tests/test_data_generator.py\n"
            "ERROR tests/test_scorer.py\n"
            "259 tests collected, 9 errors in 1.41s\n"
        )
        total, failed, names = ParallelReviewer._parse_output(output)
        assert total == 9
        assert failed == 9
        assert "tests/test_data_generator.py" in names
        assert "tests/test_scorer.py" in names

    def test_parse_pytest_passed_with_errors(self) -> None:
        output = (
            "ERROR tests/test_broken.py\n"
            "FAILED tests/test_foo.py::test_bar\n"
            "5 passed, 1 failed, 2 errors in 3.5s\n"
        )
        total, failed, names = ParallelReviewer._parse_output(output)
        assert total == 5 + 1 + 2  # passed + failed + errors
        assert failed == 1 + 2
        assert "tests/test_broken.py" in names
        assert "tests/test_foo.py::test_bar" in names

    def test_parse_pytest_error_collecting_not_captured(self) -> None:
        """'ERROR collecting ...' should capture the file path, not 'collecting'."""
        output = (
            "ERROR collecting tests/test_foo.py\n"
            "ERROR collecting tests/test_bar.py\n"
            "2 errors in 0.5s\n"
        )
        total, failed, names = ParallelReviewer._parse_output(output)
        assert total == 2
        assert failed == 2
        assert "collecting" not in names
        assert "tests/test_foo.py" in names
        assert "tests/test_bar.py" in names


# ── test_command property ───────────────────────────────────────────────


class TestTestCommandProperty:
    """Tests for the test_command property."""

    def test_detected_command(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text("[package]")
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc
        )
        assert reviewer.test_command == "cargo test"

    def test_no_command(self, tmp_path: Path) -> None:
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc
        )
        assert reviewer.test_command is None


# ── has_pending_work property ──────────────────────────────────────────


class TestHasPendingWork:
    """Tests for the has_pending_work property."""

    def test_false_when_idle(self, tmp_path: Path) -> None:
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc
        )
        assert reviewer.has_pending_work is False

    def test_true_when_running(self, tmp_path: Path) -> None:
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc
        )
        reviewer._running = True
        assert reviewer.has_pending_work is True

    def test_true_when_event_set(self, tmp_path: Path) -> None:
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc
        )
        reviewer._feature_event.set()
        assert reviewer.has_pending_work is True

    def test_false_after_running_cleared(self, tmp_path: Path) -> None:
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc
        )
        reviewer._running = True
        assert reviewer.has_pending_work is True
        reviewer._running = False
        assert reviewer.has_pending_work is False


class TestNotifyFeatureCompleted:
    """Tests for notify_feature_completed."""

    def test_appends_trigger_with_task_id(self, tmp_path: Path) -> None:
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc
        )
        reviewer.notify_feature_completed(task_id="t-1", task_name="Task 1")
        assert len(reviewer._pending_triggers) == 1
        assert reviewer._pending_triggers[0] == {"id": "t-1", "name": "Task 1"}

    def test_skips_trigger_without_task_id(self, tmp_path: Path) -> None:
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc
        )
        reviewer.notify_feature_completed()
        assert len(reviewer._pending_triggers) == 0

    def test_triggers_event_at_interval(self, tmp_path: Path) -> None:
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc,
            interval_features=2,
        )
        reviewer.notify_feature_completed(task_id="t-1", task_name="A")
        assert not reviewer._feature_event.is_set()
        reviewer.notify_feature_completed(task_id="t-2", task_name="B")
        assert reviewer._feature_event.is_set()


# ── Bugfix dispatch tests ──────────────────────────────────────────────


class TestBugfixDispatch:
    """Tests for auto-dispatching bugfix tasks on regression failure."""

    @pytest.mark.asyncio
    async def test_dispatch_creates_bugfix_task(self, tmp_path: Path) -> None:
        """Bugfix task is created when a completed feature is implicated."""
        from claw_forge.state.models import Session, Task

        db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        svc = AgentStateService(database_url=db_url)
        await svc.init_db()

        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc, max_bugfix_retries=2,
        )

        # Create a session and a completed task
        async with svc._session_factory() as db:
            session = Session(project_path=str(tmp_path))
            db.add(session)
            await db.commit()
            await db.refresh(session)

            task = Task(
                session_id=session.id,
                plugin_name="coding",
                description="User Authentication",
                status="completed",
            )
            db.add(task)
            await db.commit()
            await db.refresh(task)
            task_id = task.id
            session_id = session.id

        reviewer.session_id = session_id

        result = RegressionResult(
            passed=False, total=5, failed=1,
            failed_tests=["test_user_authentication.py::test_login"],
            run_number=1, duration_ms=100,
            output="FAILED test_user_authentication.py::test_login",
        )

        created_ids = await reviewer._dispatch_bugfix_tasks(result)
        assert len(created_ids) == 1

        # Verify bugfix task in DB
        async with svc._session_factory() as db:
            bugfix = await db.get(Task, created_ids[0])
            assert bugfix is not None
            assert bugfix.plugin_name == "bugfix"
            assert bugfix.parent_task_id == task_id
            assert bugfix.bugfix_retry_count == 1
            assert task_id in bugfix.depends_on
            assert "test_user_authentication" in bugfix.steps[0]

        await svc.dispose()

    @pytest.mark.asyncio
    async def test_no_dispatch_on_pass(self, tmp_path: Path) -> None:
        """No bugfix tasks when tests pass."""
        svc = AgentStateService(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        )
        await svc.init_db()

        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc,
        )
        reviewer.session_id = "nonexistent"

        result = RegressionResult(
            passed=True, total=5, failed=0,
            run_number=1, duration_ms=50,
        )
        # _dispatch_bugfix_tasks is only called when not passed
        # (see _loop), but verify it returns empty if called anyway
        created = await reviewer._dispatch_bugfix_tasks(result)
        assert created == []
        await svc.dispose()

    @pytest.mark.asyncio
    async def test_retry_limit_respected(self, tmp_path: Path) -> None:
        """Bugfix tasks are not created past max_bugfix_retries."""
        from claw_forge.state.models import Session, Task

        db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        svc = AgentStateService(database_url=db_url)
        await svc.init_db()

        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc, max_bugfix_retries=1,
        )

        async with svc._session_factory() as db:
            session = Session(project_path=str(tmp_path))
            db.add(session)
            await db.commit()
            await db.refresh(session)

            original = Task(
                session_id=session.id,
                plugin_name="coding",
                description="Payment Gateway",
                status="completed",
            )
            db.add(original)
            await db.commit()
            await db.refresh(original)

            # Existing bugfix already at retry count 1
            existing_bugfix = Task(
                session_id=session.id,
                plugin_name="bugfix",
                description="Fix regression: Payment Gateway",
                status="failed",
                parent_task_id=original.id,
                bugfix_retry_count=1,
            )
            db.add(existing_bugfix)
            await db.commit()
            session_id = session.id

        reviewer.session_id = session_id

        result = RegressionResult(
            passed=False, total=3, failed=1,
            failed_tests=["test_payment_gateway.py::test_charge"],
            run_number=2, duration_ms=80,
            output="FAILED test_payment_gateway.py::test_charge",
        )

        created = await reviewer._dispatch_bugfix_tasks(result)
        assert created == []  # retry limit reached
        await svc.dispose()

    @pytest.mark.asyncio
    async def test_no_session_graceful(self, tmp_path: Path) -> None:
        """No crash when session_id is not set and no active session exists."""
        svc = AgentStateService(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        )
        await svc.init_db()

        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc,
        )
        # session_id is None and DB has no sessions

        result = RegressionResult(
            passed=False, total=1, failed=1,
            failed_tests=["test_x"], run_number=1,
            output="FAILED test_x",
        )

        created = await reviewer._dispatch_bugfix_tasks(result)
        assert created == []
        await svc.dispose()

    @pytest.mark.asyncio
    async def test_no_implicated_features(self, tmp_path: Path) -> None:
        """No bugfix tasks when no features match test output."""
        from claw_forge.state.models import Session, Task

        db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        svc = AgentStateService(database_url=db_url)
        await svc.init_db()

        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc,
        )

        async with svc._session_factory() as db:
            session = Session(project_path=str(tmp_path))
            db.add(session)
            await db.commit()
            await db.refresh(session)

            task = Task(
                session_id=session.id,
                plugin_name="coding",
                description="Unrelated Feature",
                status="completed",
            )
            db.add(task)
            await db.commit()
            session_id = session.id

        reviewer.session_id = session_id

        result = RegressionResult(
            passed=False, total=2, failed=1,
            failed_tests=["test_something_else.py::test_xyz"],
            run_number=1, duration_ms=60,
            output="FAILED test_something_else.py::test_xyz",
        )

        created = await reviewer._dispatch_bugfix_tasks(result)
        assert created == []
        await svc.dispose()

    @pytest.mark.asyncio
    async def test_dispatch_auto_discovers_session(self, tmp_path: Path) -> None:
        """When session_id is not set, reviewer finds the active session from DB."""
        from claw_forge.state.models import Session, Task

        db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        svc = AgentStateService(database_url=db_url)
        await svc.init_db()

        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc, max_bugfix_retries=2,
        )
        # session_id is NOT set — reviewer must discover it

        async with svc._session_factory() as db:
            session = Session(project_path=str(tmp_path), status="running")
            db.add(session)
            await db.commit()
            await db.refresh(session)

            task = Task(
                session_id=session.id,
                plugin_name="coding",
                description="Email Service",
                status="completed",
            )
            db.add(task)
            await db.commit()

        result = RegressionResult(
            passed=False, total=3, failed=1,
            failed_tests=["test_email_service.py::test_send"],
            run_number=1, duration_ms=80,
            output="FAILED test_email_service.py::test_send",
        )

        created = await reviewer._dispatch_bugfix_tasks(result)
        assert len(created) == 1
        await svc.dispose()

    @pytest.mark.asyncio
    async def test_dispatch_db_error_returns_empty(self, tmp_path: Path) -> None:
        """DB exceptions in main dispatch block return [] gracefully."""
        from claw_forge.state.models import Session, Task

        db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        svc = AgentStateService(database_url=db_url)
        await svc.init_db()

        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc,
        )

        # Create session and task so implication works
        async with svc._session_factory() as db:
            session = Session(project_path=str(tmp_path))
            db.add(session)
            await db.commit()
            await db.refresh(session)

            task = Task(
                session_id=session.id,
                plugin_name="coding",
                description="Some Feature",
                status="completed",
            )
            db.add(task)
            await db.commit()
            session_id = session.id

        reviewer.session_id = session_id

        result = RegressionResult(
            passed=False, total=1, failed=1,
            failed_tests=["test_some_feature.py::test_x"],
            run_number=1,
            output="FAILED test_some_feature.py::test_x",
        )

        # Force the outer except by making _implicate_features raise
        # after the DB query succeeds (hits lines 343-345)
        with patch.object(
            reviewer, "_implicate_features",
            side_effect=RuntimeError("boom"),
        ):
            created = await reviewer._dispatch_bugfix_tasks(result)
            assert created == []
        await svc.dispose()


class TestLoopBranches:
    """Cover _loop branches not hit by the broadcast tests."""

    @pytest.mark.asyncio
    async def test_loop_no_test_command(self, tmp_path: Path) -> None:
        """When no test command is detected, loop logs warning and continues."""
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        svc.ws_manager = Mock()
        svc.ws_manager.broadcast = AsyncMock()

        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc, interval_features=1,
        )
        reviewer._test_command = None  # simulate no test framework detected

        await reviewer.start()
        reviewer.notify_feature_completed()
        await asyncio.sleep(0.1)
        await reviewer.stop()

        # No broadcast should have been made (no test command → skip)
        svc.ws_manager.broadcast.assert_not_called()

    @pytest.mark.asyncio
    async def test_loop_stop_before_run(self, tmp_path: Path) -> None:
        """Loop exits cleanly when stop_event is set before feature triggers."""
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        svc.ws_manager = Mock()
        svc.ws_manager.broadcast = AsyncMock()

        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc, interval_features=1,
        )
        reviewer._test_command = "echo ok"

        await reviewer.start()
        # Stop immediately, then trigger feature to unblock wait
        await reviewer.stop()
        assert reviewer._task is None

    @pytest.mark.asyncio
    async def test_loop_broadcasts_bugfix_dispatched(self, tmp_path: Path) -> None:
        """When tests fail and bugfix tasks are created, bugfix_dispatched is broadcast."""
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        svc.ws_manager = Mock()
        svc.ws_manager.broadcast = AsyncMock()

        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc, interval_features=1,
        )
        reviewer._test_command = "echo fail"

        fail_result = RegressionResult(
            passed=False, total=3, failed=1,
            failed_tests=["test_foo.py::test_bar"],
            run_number=1, duration_ms=100,
            output="FAILED test_foo",
        )

        with (
            patch.object(reviewer, "_run_tests", new_callable=AsyncMock, return_value=fail_result),
            patch.object(
                reviewer, "_dispatch_bugfix_tasks",
                new_callable=AsyncMock, return_value=["bugfix-task-id-1"],
            ),
        ):
            await reviewer.start()
            reviewer.notify_feature_completed()
            await asyncio.sleep(0.15)
            await reviewer.stop()

        calls = svc.ws_manager.broadcast.call_args_list
        types = [c.args[0]["type"] for c in calls]
        assert "bugfix_dispatched" in types
        bugfix_event = next(c.args[0] for c in calls if c.args[0]["type"] == "bugfix_dispatched")
        assert bugfix_event["task_ids"] == ["bugfix-task-id-1"]


class TestDispatchEdgeCases:
    """Cover remaining edge-case branches in _dispatch_bugfix_tasks."""

    @pytest.mark.asyncio
    async def test_session_lookup_exception(self, tmp_path: Path) -> None:
        """Exception during session lookup returns [] gracefully."""
        svc = AgentStateService(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        )
        await svc.init_db()

        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc,
        )
        # session_id is None, so it will try to look up — but we break the factory
        original_factory = svc._session_factory

        def _broken_factory() -> Any:
            raise RuntimeError("DB gone")

        svc._session_factory = _broken_factory  # type: ignore[assignment]

        result = RegressionResult(
            passed=False, total=1, failed=1,
            failed_tests=["test_x"], run_number=1,
            output="FAILED test_x",
        )

        created = await reviewer._dispatch_bugfix_tasks(result)
        assert created == []
        svc._session_factory = original_factory  # restore
        await svc.dispose()

    @pytest.mark.asyncio
    async def test_implicated_id_not_found_in_tasks(self, tmp_path: Path) -> None:
        """Implicated feature ID that doesn't exist in tasks is skipped."""
        from claw_forge.state.models import Session, Task

        db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        svc = AgentStateService(database_url=db_url)
        await svc.init_db()

        reviewer = ParallelReviewer(
            project_dir=tmp_path, state_service=svc,
        )

        async with svc._session_factory() as db:
            session = Session(project_path=str(tmp_path))
            db.add(session)
            await db.commit()
            await db.refresh(session)

            task = Task(
                session_id=session.id,
                plugin_name="coding",
                description="My Feature",
                status="completed",
            )
            db.add(task)
            await db.commit()
            session_id = session.id

        reviewer.session_id = session_id

        # Mock _implicate_features to return an ID that doesn't exist
        with patch.object(
            reviewer, "_implicate_features", return_value=["nonexistent-id"],
        ):
            result = RegressionResult(
                passed=False, total=1, failed=1,
                failed_tests=["test_x"], run_number=1,
                output="FAILED test_x",
            )
            created = await reviewer._dispatch_bugfix_tasks(result)
            assert created == []
        await svc.dispose()


class TestNotifyThreshold:
    """Cover notify_feature_completed when count < interval (152->exit)."""

    def test_notify_below_threshold(self) -> None:
        """notify_feature_completed does not trigger when below interval."""
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        reviewer = ParallelReviewer(
            project_dir="/tmp", state_service=svc, interval_features=3,
        )
        reviewer.notify_feature_completed()  # 1 < 3 → no trigger
        assert not reviewer._feature_event.is_set()
        reviewer.notify_feature_completed()  # 2 < 3 → no trigger
        assert not reviewer._feature_event.is_set()
        reviewer.notify_feature_completed()  # 3 >= 3 → trigger
        assert reviewer._feature_event.is_set()
