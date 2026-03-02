"""Coding plugin — implements code changes."""

from __future__ import annotations

from pathlib import Path

from claw_forge.agent import collect_result
from claw_forge.plugins.base import BasePlugin, PluginContext, PluginResult


class CodingPlugin(BasePlugin):
    """Agent plugin for implementing code changes."""

    @property
    def name(self) -> str:
        return "coding"

    @property
    def description(self) -> str:
        return "Implement code changes: new features, bug fixes, refactoring"

    def get_system_prompt(self, context: PluginContext) -> str:
        return (
            "You are an expert coding agent. Your task is to implement code changes "
            "in the project. Follow these principles:\n\n"
            "1. Read and understand existing code before making changes\n"
            "2. Follow the project's coding style and conventions\n"
            "3. Write clean, well-documented, type-annotated code\n"
            "4. Make minimal, focused changes — don't refactor unrelated code\n"
            "5. Add or update tests for any changes you make\n"
            "6. Verify your changes compile/pass linting before finishing\n\n"
            f"Project: {context.project_path}\n"
            f"Task: {context.metadata.get('description', 'No description')}"
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
            output=result or "Coding task completed",
            metadata={"plugin": self.name, "task_id": context.task_id},
        )
