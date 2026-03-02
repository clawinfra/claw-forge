"""Testing plugin — runs and analyzes test suites."""

from __future__ import annotations

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

    async def execute(self, context: PluginContext) -> PluginResult:
        return PluginResult(
            success=True,
            output="Testing task placeholder — requires LLM tool loop integration",
            metadata={"plugin": self.name, "task_id": context.task_id},
        )
