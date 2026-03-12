"""Unit tests for HarborAdapter.

All Harbor HTTP calls are mocked using unittest.mock.patch on httpx.Client.
No real HTTP connections made.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from scripts.eval.harbor_adapter import (
    ABLATION_CONFIGS,
    HarborAdapter,
    HarborAPIError,
    HarborScoringError,
    HarborTask,
    HarborTaskNotFoundError,
    TaskResult,
)


def _make_response(
    status_code: int = 200,
    json_data: object = None,
    text: str = "",
) -> httpx.Response:
    """Build a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = text
    return resp


def _make_adapter(
    request_timeout_s: float = 30.0,
    task_timeout_s: int = 300,
) -> HarborAdapter:
    """Create a HarborAdapter with a mocked httpx.Client."""
    adapter = HarborAdapter(
        "https://api.harbor.test",
        "test-api-key",
        request_timeout_s=request_timeout_s,
        task_timeout_s=task_timeout_s,
    )
    adapter._client = MagicMock(spec=httpx.Client)
    return adapter


SAMPLE_START_RESPONSE = {
    "task_id": "task-001",
    "description": "Write a Python function that reverses a string.",
    "sandbox_url": "https://sandbox-mock.daytona.io",
    "working_dir": "/workspace/task-001",
    "scoring_url": "https://api.harbor.test/api/v1/tasks/task-001/score",
    "timeout_s": 300,
    "metadata": {},
}

SAMPLE_SCORE_RESPONSE = {"score": 85.0, "passed": True, "details": {}}


class TestHarborAdapterInit:
    def test_init_sets_base_url(self) -> None:
        adapter = HarborAdapter("https://api.harbor.test/", "key")
        assert adapter.harbor_base_url == "https://api.harbor.test"

    def test_init_sets_api_key(self) -> None:
        adapter = HarborAdapter("https://api.harbor.test", "my-key")
        assert adapter.harbor_api_key == "my-key"

    def test_init_default_timeouts(self) -> None:
        adapter = HarborAdapter("https://api.harbor.test", "key")
        assert adapter.request_timeout_s == 30.0
        assert adapter.task_timeout_s == 300

    def test_init_custom_timeouts(self) -> None:
        adapter = HarborAdapter(
            "https://api.harbor.test",
            "key",
            request_timeout_s=10.0,
            task_timeout_s=60,
        )
        assert adapter.request_timeout_s == 10.0
        assert adapter.task_timeout_s == 60


class TestListTasks:
    def test_list_tasks_returns_ids(self) -> None:
        adapter = _make_adapter()
        adapter._client.request.return_value = _make_response(
            200, ["task-001", "task-002", "task-003"]
        )
        result = adapter.list_tasks()
        assert result == ["task-001", "task-002", "task-003"]
        adapter._client.request.assert_called_once()

    def test_list_tasks_raises_api_error_on_500(self) -> None:
        adapter = _make_adapter()
        adapter._client.request.return_value = _make_response(500, text="server error")
        with pytest.raises(HarborAPIError) as exc_info:
            adapter.list_tasks()
        assert exc_info.value.status_code == 500

    def test_list_tasks_raises_api_error_on_401(self) -> None:
        adapter = _make_adapter()
        adapter._client.request.return_value = _make_response(401, text="unauthorized")
        with pytest.raises(HarborAPIError) as exc_info:
            adapter.list_tasks()
        assert exc_info.value.status_code == 401

    def test_list_tasks_raises_api_error_on_network_error(self) -> None:
        adapter = _make_adapter()
        adapter._client.request.side_effect = httpx.ConnectError("connection refused")
        with pytest.raises(HarborAPIError):
            adapter.list_tasks()


class TestStartTask:
    def test_start_task_returns_harbor_task(self) -> None:
        adapter = _make_adapter()
        adapter._client.request.return_value = _make_response(200, SAMPLE_START_RESPONSE)
        task = adapter.start_task("task-001")
        assert isinstance(task, HarborTask)
        assert task.task_id == "task-001"
        assert task.description == "Write a Python function that reverses a string."
        assert task.sandbox_url == "https://sandbox-mock.daytona.io"
        assert task.working_dir == "/workspace/task-001"
        assert task.timeout_s == 300

    def test_start_task_raises_not_found_on_404(self) -> None:
        adapter = _make_adapter()
        adapter._client.request.return_value = _make_response(404, text="not found")
        with pytest.raises(HarborTaskNotFoundError):
            adapter.start_task("task-999")

    def test_start_task_raises_api_error_on_500(self) -> None:
        adapter = _make_adapter()
        adapter._client.request.return_value = _make_response(500, text="server error")
        with pytest.raises(HarborAPIError):
            adapter.start_task("task-001")

    def test_start_task_retries_on_503(self) -> None:
        adapter = _make_adapter()
        resp_503 = _make_response(503, text="service unavailable")
        resp_ok = _make_response(200, SAMPLE_START_RESPONSE)
        adapter._client.request.side_effect = [resp_503, resp_ok]

        with patch("scripts.eval.harbor_adapter.time.sleep"):
            task = adapter.start_task("task-001")
        assert task.task_id == "task-001"
        assert adapter._client.request.call_count == 2


class TestSubmitResult:
    def test_submit_result_returns_scoring_dict(self) -> None:
        adapter = _make_adapter()
        adapter._client.request.return_value = _make_response(200, SAMPLE_SCORE_RESPONSE)
        task = HarborTask(
            task_id="task-001",
            description="test",
            sandbox_url="https://sandbox.test",
            working_dir="/workspace",
            scoring_url="https://api.harbor.test/score",
            timeout_s=300,
            metadata={},
        )
        result = adapter.submit_result(task, "output text")
        assert result["score"] == 85.0
        assert result["passed"] is True

    def test_submit_result_raises_scoring_error_on_missing_score(self) -> None:
        adapter = _make_adapter()
        adapter._client.request.return_value = _make_response(200, {"details": {}})
        task = HarborTask(
            task_id="task-001",
            description="test",
            sandbox_url="https://sandbox.test",
            working_dir="/workspace",
            scoring_url="https://api.harbor.test/score",
            timeout_s=300,
            metadata={},
        )
        with pytest.raises(HarborScoringError):
            adapter.submit_result(task, "output")

    def test_submit_result_raises_api_error_on_500(self) -> None:
        adapter = _make_adapter()
        adapter._client.request.return_value = _make_response(500, text="fail")
        task = HarborTask(
            task_id="task-001",
            description="test",
            sandbox_url="https://sandbox.test",
            working_dir="/workspace",
            scoring_url="https://api.harbor.test/score",
            timeout_s=300,
            metadata={},
        )
        with pytest.raises(HarborAPIError):
            adapter.submit_result(task, "output")


class TestBuildPrompt:
    def test_prompt_contains_task_description(self) -> None:
        adapter = _make_adapter()
        task = HarborTask(
            task_id="task-001",
            description="Reverse a string",
            sandbox_url="https://sandbox.test",
            working_dir="/workspace/task-001",
            scoring_url="https://api.harbor.test/score",
            timeout_s=300,
            metadata={},
        )
        prompt = adapter._build_prompt(task)
        assert "Reverse a string" in prompt

    def test_prompt_contains_working_dir(self) -> None:
        adapter = _make_adapter()
        task = HarborTask(
            task_id="task-001",
            description="test task",
            sandbox_url="https://sandbox.test",
            working_dir="/workspace/task-001",
            scoring_url="https://api.harbor.test/score",
            timeout_s=300,
            metadata={},
        )
        prompt = adapter._build_prompt(task)
        assert "/workspace/task-001" in prompt

    def test_prompt_includes_build_verify_instruction(self) -> None:
        adapter = _make_adapter()
        task = HarborTask(
            task_id="task-001",
            description="test",
            sandbox_url="https://sandbox.test",
            working_dir="/workspace",
            scoring_url="https://api.harbor.test/score",
            timeout_s=300,
            metadata={},
        )
        prompt = adapter._build_prompt(task)
        assert "verify" in prompt.lower()


class TestBuildHooks:
    def test_baseline_config_a_uses_default_hooks(self) -> None:
        adapter = _make_adapter()
        hooks = adapter._build_hooks(ABLATION_CONFIGS["A"])
        assert hooks["edit_mode"] == "str_replace"
        assert "pre_completion_checklist" not in hooks
        assert "loop_detection" not in hooks

    def test_config_c_includes_pre_completion_hook(self) -> None:
        adapter = _make_adapter()
        hooks = adapter._build_hooks(ABLATION_CONFIGS["C"])
        assert hooks["pre_completion_checklist"] is True
        assert "loop_detection" not in hooks

    def test_config_d_includes_loop_detection_hook(self) -> None:
        adapter = _make_adapter()
        hooks = adapter._build_hooks(ABLATION_CONFIGS["D"])
        assert hooks["loop_detection"] is True
        assert "pre_completion_checklist" not in hooks

    def test_config_e_includes_both_hooks(self) -> None:
        adapter = _make_adapter()
        hooks = adapter._build_hooks(ABLATION_CONFIGS["E"])
        assert hooks["pre_completion_checklist"] is True
        assert hooks["loop_detection"] is True

    def test_config_b_uses_hashline_edit_mode(self) -> None:
        adapter = _make_adapter()
        hooks = adapter._build_hooks(ABLATION_CONFIGS["B"])
        assert hooks["edit_mode"] == "hashline"


class TestRunTask:
    @pytest.mark.asyncio
    async def test_run_task_success_returns_task_result(self) -> None:
        adapter = _make_adapter()
        adapter._client.request.side_effect = [
            _make_response(200, SAMPLE_START_RESPONSE),
            _make_response(200, SAMPLE_SCORE_RESPONSE),
        ]

        mock_run_agent = AsyncMock(return_value="agent output text")
        with (
            patch("scripts.eval.harbor_adapter.run_agent", mock_run_agent, create=True),
            patch.dict("sys.modules", {"claw_forge.sdk": MagicMock(run_agent=mock_run_agent)}),
        ):
            result = await adapter.run_task(
                    "task-001",
                    config=ABLATION_CONFIGS["A"],
                    rep=1,
                )
        assert isinstance(result, TaskResult)
        assert result.score == 85.0
        assert result.passed is True
        assert result.error is None

    @pytest.mark.asyncio
    async def test_run_task_dry_run_skips_agent(self) -> None:
        adapter = _make_adapter()
        adapter._client.request.return_value = _make_response(200, SAMPLE_START_RESPONSE)

        result = await adapter.run_task(
            "task-001",
            config=ABLATION_CONFIGS["A"],
            dry_run=True,
        )
        assert result.error == "dry-run"
        assert result.score == 0.0
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_run_task_harbor_api_error_returns_error_result(self) -> None:
        adapter = _make_adapter()
        adapter._client.request.return_value = _make_response(500, text="fail")

        result = await adapter.run_task(
            "task-001",
            config=ABLATION_CONFIGS["A"],
        )
        assert result.error is not None
        assert "500" in result.error
        assert result.score == 0.0

    @pytest.mark.asyncio
    async def test_run_task_run_agent_exception_returns_error_result(self) -> None:
        adapter = _make_adapter()
        adapter._client.request.return_value = _make_response(200, SAMPLE_START_RESPONSE)

        mock_run_agent = AsyncMock(side_effect=RuntimeError("agent crashed"))
        with patch.dict("sys.modules", {"claw_forge.sdk": MagicMock(run_agent=mock_run_agent)}):
            result = await adapter.run_task(
                "task-001",
                config=ABLATION_CONFIGS["A"],
            )
        assert result.error is not None
        assert result.score == 0.0

    @pytest.mark.asyncio
    async def test_run_task_stores_score_and_passed(self) -> None:
        adapter = _make_adapter()
        score_resp = {"score": 92.5, "passed": True, "details": {"x": 1}}
        adapter._client.request.side_effect = [
            _make_response(200, SAMPLE_START_RESPONSE),
            _make_response(200, score_resp),
        ]
        mock_run_agent = AsyncMock(return_value="output")
        with patch.dict("sys.modules", {"claw_forge.sdk": MagicMock(run_agent=mock_run_agent)}):
            result = await adapter.run_task(
                "task-001",
                config=ABLATION_CONFIGS["E"],
                rep=2,
            )
        assert result.score == 92.5
        assert result.passed is True
        assert result.config_id == "E"
        assert result.rep == 2

    @pytest.mark.asyncio
    async def test_run_task_duration_measured(self) -> None:
        adapter = _make_adapter()
        adapter._client.request.return_value = _make_response(200, SAMPLE_START_RESPONSE)

        result = await adapter.run_task(
            "task-001",
            config=ABLATION_CONFIGS["A"],
            dry_run=True,
        )
        assert result.duration_s >= 0.0


class TestAblationConfigs:
    def test_all_five_configs_present(self) -> None:
        assert set(ABLATION_CONFIGS.keys()) == {"A", "B", "C", "D", "E"}

    def test_config_a_is_baseline(self) -> None:
        c = ABLATION_CONFIGS["A"]
        assert c.edit_mode == "str_replace"
        assert not c.pre_completion_hook
        assert not c.loop_detection_hook
        assert c.description == "baseline"

    def test_config_b_hashline(self) -> None:
        c = ABLATION_CONFIGS["B"]
        assert c.edit_mode == "hashline"
        assert not c.pre_completion_hook
        assert not c.loop_detection_hook

    def test_config_c_pre_complete(self) -> None:
        c = ABLATION_CONFIGS["C"]
        assert c.edit_mode == "str_replace"
        assert c.pre_completion_hook
        assert not c.loop_detection_hook

    def test_config_d_loop_detect(self) -> None:
        c = ABLATION_CONFIGS["D"]
        assert c.edit_mode == "str_replace"
        assert not c.pre_completion_hook
        assert c.loop_detection_hook

    def test_config_e_full(self) -> None:
        c = ABLATION_CONFIGS["E"]
        assert c.edit_mode == "hashline"
        assert c.pre_completion_hook
        assert c.loop_detection_hook
