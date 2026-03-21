"""BugFix plugin — reproduce-first bug fix protocol."""

from __future__ import annotations

import logging
from pathlib import Path

from claw_forge.agent.runner import run_agent
from claw_forge.plugins.base import BasePlugin, PluginContext, PluginResult

logger = logging.getLogger(__name__)

_BUG_FIX_PROTOCOL = """\
You are a bug-fix agent. Your ONLY job is to fix the reported bug.

Protocol (strictly in order — never skip):
1. READ the bug report carefully
2. REPRODUCE: write a failing test that demonstrates the bug (RED)
   - If you cannot write a failing test, describe why and ask for human input
3. ISOLATE: find the exact line(s) causing the bug using git log, grep, and reading code
4. HYPOTHESIZE: write 2-3 candidate causes ranked by likelihood
5. VERIFY: confirm the top hypothesis with minimal changes
6. FIX: make the targeted fix — touch ONLY what is needed
7. GREEN: run the regression test — it must now pass
8. REGRESSION CHECK: run full test suite — must be 100% green
9. COMMIT: atomic commit with message "fix: <title>\\n\\nRegression test: <test_name>"

Rules:
- Never fix more than the reported bug in one session
- Never modify files not related to the bug unless constraints explicitly allow it
- If stuck for >10 tool calls without progress → call human_input tool
- Regression test is MANDATORY — do not skip even for "obvious" fixes

Parallel Sub-Agents:
If the fix requires changes to 5+ independent files, use the Agent tool to \
parallelize independent modifications. Do NOT use sub-agents for the sequential \
reproduce → isolate → fix → verify workflow.
"""


class BugFixPlugin(BasePlugin):
    """Fix bugs using a reproduce-first protocol with mandatory regression tests."""

    @property
    def name(self) -> str:
        return "bugfix"

    @property
    def description(self) -> str:
        return "Fix bugs: reproduce → isolate → fix → regression test"

    def get_system_prompt(self, context: PluginContext) -> str:
        """Return bug-fix agent system prompt, injecting bug report if present."""
        from claw_forge.bugfix.report import BugReport

        parts = [_BUG_FIX_PROTOCOL]

        bug_report = context.metadata.get("bug_report")
        if isinstance(bug_report, BugReport):
            parts.append("\n---\n")
            parts.append(bug_report.to_agent_prompt())

        return "\n".join(parts)

    async def execute(self, context: PluginContext) -> PluginResult:
        """Execute bug fix workflow."""
        from claw_forge.bugfix.report import BugReport

        project = Path(context.project_path)
        if not project.exists():
            return PluginResult(
                success=False,
                output=f"Project path not found: {project}",
            )

        bug_report: BugReport | None = context.metadata.get("bug_report")
        title = bug_report.title if bug_report else "Unknown bug"

        system_prompt = self.get_system_prompt(context)

        prompt = (
            f"Fix the following bug: {title}\n\n"
            "Follow the reproduce-first protocol in your system prompt exactly.\n"
            "Start by writing a failing regression test, then isolate and fix the bug."
        )
        if bug_report:
            prompt += f"\n\n{bug_report.to_agent_prompt()}"

        from claude_agent_sdk import ThinkingConfig

        thinking: ThinkingConfig = {"type": "adaptive"}

        output_parts: list[str] = []
        files_modified: list[str] = []

        try:
            async for message in run_agent(
                prompt,
                cwd=project,
                allowed_tools=["Read", "Write", "Edit", "Bash", "MultiEdit"],
                system_prompt=system_prompt,
                auto_inject_skills=True,
                thinking=thinking,
                permission_mode="default",
            ):
                msg_type = message.__class__.__name__
                if msg_type == "AssistantMessage":
                    for block in message.content:  # type: ignore[union-attr]
                        if hasattr(block, "text"):
                            output_parts.append(block.text)
                elif (
                    msg_type == "ResultMessage"
                    and hasattr(message, "files_modified")
                    and message.files_modified
                ):
                    files_modified.extend(message.files_modified)
        except Exception as exc:
            logger.exception("Bug fix agent failed")
            return PluginResult(
                success=False,
                output=f"Agent error: {exc}",
            )

        return PluginResult(
            success=True,
            output="\n".join(output_parts),
            files_modified=files_modified,
            metadata={"title": title},
        )
