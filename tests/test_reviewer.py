"""Tests for ParallelReviewer regression testing system."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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
            implicated_feature_ids=[1, 2],
            output="FAILED test_a",
        )
        d = r.to_dict()
        assert d["passed"] is False
        assert d["total"] == 5
        assert d["failed"] == 2
        assert d["failed_tests"] == ["test_a", "test_b"]
        assert d["duration_ms"] == 123
        assert d["run_number"] == 3
        assert d["implicated_feature_ids"] == [1, 2]
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
        svc.ws_manager = MagicMock()
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
        assert 1 in result
        assert 2 in result
        assert 3 not in result

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
        assert 10 in result

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
        svc.ws_manager = MagicMock()
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
        mock_reviewer = MagicMock()
        mock_reviewer.run_count = 2
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

    @pytest.mark.asyncio
    async def test_with_failed_result(self) -> None:
        svc = AgentStateService(database_url="sqlite+aiosqlite://")
        mock_reviewer = MagicMock()
        mock_reviewer.run_count = 5
        mock_reviewer.last_result = RegressionResult(
            passed=False,
            total=20,
            failed=3,
            failed_tests=["test_a", "test_b", "test_c"],
            run_number=5,
            duration_ms=2000,
            implicated_feature_ids=[1, 4],
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
        assert data["last_result"]["implicated_feature_ids"] == [
            1, 4
        ]


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
