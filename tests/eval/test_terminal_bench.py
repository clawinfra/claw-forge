"""Unit tests for AblationRunner and CLI main()."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.eval.harbor_adapter import TaskResult
from scripts.eval.terminal_bench import AblationRunner, main, parse_args


def _make_result(
    config_id: str = "A",
    task_id: str = "task-001",
    rep: int = 1,
    score: float = 80.0,
    passed: bool = True,
    error: str | None = None,
) -> TaskResult:
    return TaskResult(
        config_id=config_id,
        task_id=task_id,
        rep=rep,
        score=score,
        passed=passed,
        duration_s=1.0,
        error=error,
    )


class TestParseArgs:
    def test_default_reps(self) -> None:
        ns = parse_args(["--config", "A"])
        assert ns.reps == 3

    def test_dry_run_flag(self) -> None:
        ns = parse_args(["--config", "A", "--dry-run"])
        assert ns.dry_run is True

    def test_model_default(self) -> None:
        ns = parse_args(["--config", "A"])
        assert ns.model == "claude-sonnet-4-6"

    def test_config_all_accepted(self) -> None:
        ns = parse_args(["--config", "all"])
        assert ns.config == "all"

    def test_invalid_config_rejected(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["--config", "Z"])

    def test_reps_must_be_positive(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["--config", "A", "--reps", "0"])

    def test_custom_model(self) -> None:
        ns = parse_args(["--config", "A", "--model", "sonnet"])
        assert ns.model == "sonnet"

    def test_output_dir(self) -> None:
        ns = parse_args(["--config", "A", "--output-dir", "/tmp/bench"])
        assert ns.output_dir == Path("/tmp/bench")

    def test_verbose_flag(self) -> None:
        ns = parse_args(["--config", "A", "--verbose"])
        assert ns.verbose is True

    def test_concurrency(self) -> None:
        ns = parse_args(["--config", "A", "--concurrency", "4"])
        assert ns.concurrency == 4

    def test_tasks_filter(self) -> None:
        ns = parse_args(["--config", "A", "--tasks", "task-001", "task-002"])
        assert ns.tasks == ["task-001", "task-002"]


class TestAblationRunnerStateFile:
    def test_load_state_empty_on_missing_file(self, tmp_path: Path) -> None:
        adapter = MagicMock()
        runner = AblationRunner(adapter, output_dir=tmp_path)
        state = runner._load_state()
        assert len(state.completed_keys) == 0
        assert len(state.completed_results) == 0

    def test_load_state_reads_completed_keys(self, tmp_path: Path) -> None:
        state_file = tmp_path / "run_state.jsonl"
        result_data = {
            "config_id": "A",
            "task_id": "task-001",
            "rep": 1,
            "score": 85.0,
            "passed": True,
            "duration_s": 10.0,
            "error": None,
            "raw_scoring": {},
        }
        state_file.write_text(json.dumps(result_data) + "\n")

        adapter = MagicMock()
        runner = AblationRunner(adapter, output_dir=tmp_path)
        state = runner._load_state()
        assert "A:task-001:1" in state.completed_keys
        assert len(state.completed_results) == 1
        assert state.completed_results[0].score == 85.0

    def test_append_result_creates_file(self, tmp_path: Path) -> None:
        adapter = MagicMock()
        runner = AblationRunner(adapter, output_dir=tmp_path)
        result = _make_result()
        runner._append_result(result)

        state_file = tmp_path / "run_state.jsonl"
        assert state_file.exists()
        data = json.loads(state_file.read_text().strip())
        assert data["config_id"] == "A"
        assert data["score"] == 80.0

    def test_append_result_idempotent_on_reopen(self, tmp_path: Path) -> None:
        adapter = MagicMock()
        runner = AblationRunner(adapter, output_dir=tmp_path)
        runner._append_result(_make_result(config_id="A", task_id="task-001", rep=1))
        runner._append_result(_make_result(config_id="A", task_id="task-002", rep=1))

        state_file = tmp_path / "run_state.jsonl"
        lines = state_file.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["task_id"] == "task-001"
        assert json.loads(lines[1])["task_id"] == "task-002"

    def test_make_key_format(self, tmp_path: Path) -> None:
        adapter = MagicMock()
        runner = AblationRunner(adapter, output_dir=tmp_path)
        assert runner._make_key("A", "task-042", 2) == "A:task-042:2"


class TestAblationRunnerRun:
    @pytest.mark.asyncio
    async def test_run_skips_completed_tasks(self, tmp_path: Path) -> None:
        state_file = tmp_path / "run_state.jsonl"
        result_data = {
            "config_id": "A",
            "task_id": "task-001",
            "rep": 1,
            "score": 85.0,
            "passed": True,
            "duration_s": 10.0,
            "error": None,
            "raw_scoring": {},
        }
        state_file.write_text(json.dumps(result_data) + "\n")

        adapter = MagicMock()
        adapter.run_task = AsyncMock(return_value=_make_result(config_id="A", task_id="task-002"))
        runner = AblationRunner(adapter, output_dir=tmp_path)

        results = await runner.run(
            ["A"], reps=1, task_ids=["task-001", "task-002"]
        )
        # task-001 was in state file, only task-002 should have been run
        assert adapter.run_task.call_count == 1
        assert len(results) == 2  # existing + new

    @pytest.mark.asyncio
    async def test_run_collects_all_results(self, tmp_path: Path) -> None:
        adapter = MagicMock()
        adapter.run_task = AsyncMock(return_value=_make_result())
        runner = AblationRunner(adapter, output_dir=tmp_path)

        results = await runner.run(
            ["A", "B"], reps=2, task_ids=["task-001", "task-002"]
        )
        # 2 configs × 2 reps × 2 tasks = 8
        assert len(results) == 8
        assert adapter.run_task.call_count == 8

    @pytest.mark.asyncio
    async def test_run_dry_run_passes_flag_to_adapter(self, tmp_path: Path) -> None:
        adapter = MagicMock()
        adapter.run_task = AsyncMock(
            return_value=_make_result(error="dry-run", score=0.0)
        )
        runner = AblationRunner(adapter, output_dir=tmp_path)

        await runner.run(["A"], reps=1, task_ids=["task-001"], dry_run=True)
        call_kwargs = adapter.run_task.call_args[1]
        assert call_kwargs["dry_run"] is True

    @pytest.mark.asyncio
    async def test_run_returns_existing_plus_new_results(self, tmp_path: Path) -> None:
        state_file = tmp_path / "run_state.jsonl"
        for tid in ["task-001", "task-002"]:
            data = {
                "config_id": "A",
                "task_id": tid,
                "rep": 1,
                "score": 80.0,
                "passed": True,
                "duration_s": 5.0,
                "error": None,
                "raw_scoring": {},
            }
            with open(state_file, "a") as f:
                f.write(json.dumps(data) + "\n")

        adapter = MagicMock()
        adapter.run_task = AsyncMock(return_value=_make_result())
        runner = AblationRunner(adapter, output_dir=tmp_path)

        results = await runner.run(
            ["A"], reps=1, task_ids=["task-001", "task-002", "task-003", "task-004"]
        )
        # 2 from state + 2 new = 4
        assert len(results) == 4
        assert adapter.run_task.call_count == 2

    @pytest.mark.asyncio
    async def test_run_fetches_tasks_from_adapter_when_none_provided(
        self, tmp_path: Path
    ) -> None:
        adapter = MagicMock()
        adapter.list_tasks.return_value = ["task-001"]
        adapter.run_task = AsyncMock(return_value=_make_result())
        runner = AblationRunner(adapter, output_dir=tmp_path)

        results = await runner.run(["A"], reps=1)
        adapter.list_tasks.assert_called_once()
        assert len(results) == 1


class TestMainCLI:
    def test_main_exits_0_on_success(self, tmp_path: Path) -> None:
        mock_adapter = MagicMock()
        mock_adapter.list_tasks.return_value = ["task-001"]
        mock_adapter.run_task = AsyncMock(
            return_value=_make_result(score=90.0, passed=True)
        )

        with (
            patch("scripts.eval.terminal_bench.HarborAdapter", return_value=mock_adapter),
            patch.dict("os.environ", {"HARBOR_API_KEY": "test-key"}),
        ):
            exit_code = main([
                "--config", "A",
                "--reps", "1",
                "--output-dir", str(tmp_path),
                "--harbor-key", "test-key",
            ])
        assert exit_code == 0

    def test_main_exits_2_on_missing_harbor_key(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {}, clear=True):
            exit_code = main([
                "--config", "A",
                "--output-dir", str(tmp_path),
            ])
        assert exit_code == 2

    def test_main_exits_1_on_partial_errors(self, tmp_path: Path) -> None:
        mock_adapter = MagicMock()
        mock_adapter.list_tasks.return_value = ["task-001", "task-002"]

        results = [
            _make_result(task_id="task-001", score=90.0, error=None),
            _make_result(task_id="task-002", score=0.0, error="something failed"),
        ]
        call_count = 0

        async def mock_run_task(*args: object, **kwargs: object) -> TaskResult:
            nonlocal call_count
            r = results[call_count % len(results)]
            call_count += 1
            return r

        mock_adapter.run_task = mock_run_task

        with patch("scripts.eval.terminal_bench.HarborAdapter", return_value=mock_adapter):
            exit_code = main([
                "--config", "A",
                "--reps", "1",
                "--output-dir", str(tmp_path),
                "--harbor-key", "test-key",
            ])
        assert exit_code == 1
