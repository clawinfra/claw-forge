"""Testing plugin — runs and analyzes test suites."""

from __future__ import annotations

from pathlib import Path

from claw_forge.agent import collect_result
from claw_forge.plugins.base import BasePlugin, PluginContext, PluginResult


class TestingPlugin(BasePlugin):
    """Agent plugin for running tests and analyzing results."""

    @property
    def name(self) -> str:
        return "testing"

    @property
    def description(self) -> str:
        return "Run test suites, analyze failures, suggest fixes"

    def get_system_prompt(self, context: PluginContext) -> str:
        return (
            "You are an expert QA engineer embedded in the claw-forge harness. Your job is to "
            "run the full test suite, identify failures with root cause analysis, and suggest "
            "(but not implement) fixes.\n\n"
            "## Your Role\n"
            "- Run tests, report results\n"
            "- Identify root causes\n"
            "- Suggest fixes with specific guidance\n"
            "- Mark features as regression-safe\n"
            "- Do NOT implement fixes yourself — that's the coding agent's job\n"
            "- Do NOT modify production code\n\n"
            "## Startup Protocol\n"
            "1. Check manifest: `cat session_manifest.json 2>/dev/null | python3 -m json.tool`\n"
            "2. What changed: `git log --oneline -10 && git diff HEAD~1 HEAD --name-only`\n"
            "3. Check state service: `curl -s http://localhost:8420/sessions/$SESSION_ID/tasks`\n\n"
            "## Test Execution\n"
            "Full suite: `uv run pytest tests/ -v --tb=long --cov=claw_forge "
            "--cov-report=term-missing`\n"
            "Type check: `uv run mypy claw_forge/ --ignore-missing-imports`\n\n"
            "## Root Cause Classification\n"
            "- `regression`: Was passing, now failing\n"
            "- `missing_feature`: Feature not yet implemented\n"
            "- `wrong_assertion`: Test itself is incorrect\n"
            "- `environment`: Missing dependency, wrong version\n"
            "- `flaky`: Non-deterministic failure\n\n"
            "## Coverage Requirements\n"
            "New code must have ≥90% coverage. Report PATCH "
            "http://localhost:8420/tasks/$TASK_ID with results.\n\n"
            f"Project: {context.project_path}"
        )

    def _build_prompt(self, context: PluginContext) -> str:
        return (
            f"{self.get_system_prompt(context)}\n\n"
            f"Session: {context.session_id}\n"
            f"Task ID: {context.task_id}"
        )

    async def execute(self, context: PluginContext) -> PluginResult:
        prompt = self._build_prompt(context)
        result = await collect_result(
            prompt,
            cwd=Path(context.project_path),
            allowed_tools=["Read", "Write", "Edit", "Bash"],
        )
        return PluginResult(
            success=True,
            output=result or "Testing task completed",
            metadata={"plugin": self.name, "task_id": context.task_id},
        )
