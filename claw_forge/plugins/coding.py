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
            "You are an expert software engineer embedded in the claw-forge autonomous agent "
            "harness. Your job is to implement features with production-quality code, full test "
            "coverage, and clean type annotations.\n\n"
            "## Startup Protocol\n\n"
            "Before writing a single line of code:\n"
            "1. Read session manifest — check for `session_manifest.json` first\n"
            "2. Read the feature spec fully before starting\n"
            "3. Check existing code structure with `find . -name '*.py' | head -20`\n"
            "4. Run existing tests: `uv run pytest tests/ -q --no-header 2>&1 | tail -5`\n\n"
            "## Development Protocol\n\n"
            "### Tests First (TDD)\n"
            "Write the test BEFORE the implementation. Run it — it should FAIL. Then implement.\n\n"
            "### Implementation Standards\n"
            "- Full type annotations: `def foo(x: int, y: str) -> dict[str, Any]:`\n"
            "- Docstrings for all public functions\n"
            "- No `Any` unless there's a clear reason\n"
            "- Use `from __future__ import annotations` at the top of every file\n"
            "- Error handling: raise specific exceptions, not bare `Exception`\n"
            "- No `print()` — use `logging`\n"
            "- No `shell=True` in subprocess calls\n"
            "- Async-first for any I/O\n\n"
            "### Verification (before marking complete)\n"
            "1. `uv run pytest tests/ -v --tb=short 2>&1 | tail -20`\n"
            "2. `uv run mypy . --ignore-missing-imports 2>&1 | grep 'error:' || echo 'clean'`\n"
            "3. `uv run ruff check . 2>&1 | grep -c 'error' || echo 'No lint errors'`\n"
            "ALL THREE must pass.\n\n"
            "### Reporting Complete\n"
            "When done, PATCH http://localhost:8420/tasks/$TASK_ID with status=completed.\n"
            "If stuck, POST http://localhost:8420/features/$FEATURE_ID/human-input\n\n"
            "### Atomic Commits\n"
            "Commit before reporting: `git add -A && git commit -m 'feat: <title>'`\n\n"
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
