"""Reviewer plugin — code review and quality gates."""

from __future__ import annotations

from claw_forge.plugins.base import BasePlugin, PluginContext, PluginResult


class ReviewerPlugin(BasePlugin):
    """Agent plugin for code review and quality assurance."""

    @property
    def name(self) -> str:
        return "reviewer"

    @property
    def description(self) -> str:
        return "Review code changes for correctness, style, security, and performance"

    def get_system_prompt(self, context: PluginContext) -> str:
        return (
            "You are a senior code reviewer. Review changes for:\n\n"
            "1. Correctness — does the code do what it claims?\n"
            "2. Security — any vulnerabilities, injection risks, credential leaks?\n"
            "3. Performance — obvious bottlenecks, N+1 queries, memory leaks?\n"
            "4. Style — consistent with project conventions?\n"
            "5. Tests — adequate coverage of new/changed code?\n"
            "6. Documentation — are changes documented?\n\n"
            "Provide actionable feedback with specific file:line references.\n\n"
            f"Project: {context.project_path}"
        )

    async def execute(self, context: PluginContext) -> PluginResult:
        return PluginResult(
            success=True,
            output="Review task placeholder — requires LLM tool loop integration",
            metadata={"plugin": self.name, "task_id": context.task_id},
        )
