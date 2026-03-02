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
            "You are a testing agent. Your responsibilities:\n\n"
            "1. Identify the project's test framework and run tests\n"
            "2. Analyze test failures and provide clear diagnostics\n"
            "3. Write new tests for uncovered code paths\n"
            "4. Ensure tests are deterministic and well-isolated\n"
            "5. Report coverage metrics when available\n\n"
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
