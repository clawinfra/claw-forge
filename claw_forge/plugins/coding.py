"""Coding plugin — implements code changes."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from claw_forge.agent import collect_result
from claw_forge.plugins.base import BasePlugin, PluginContext, PluginResult

logger = logging.getLogger(__name__)

# Regex to extract fenced code blocks with a filename or language hint.
# Matches:
#   ```path/to/file.ext\n<code>\n```
#   ```lang\n<code>\n```
_CODE_BLOCK_RE = re.compile(
    r"```(\S+)\n(.*?)```",
    re.DOTALL,
)

# Heuristic: if the first line (the "lang" part) looks like a file path, treat
# it as the target filename.  Otherwise it's just a language tag and we skip.
_FILE_PATH_RE = re.compile(r"^[\w./-]+\.\w{1,10}$")


def extract_code_blocks(text: str) -> list[tuple[str, str]]:
    """Parse fenced code blocks and return ``(filename, content)`` pairs.

    Only blocks whose tag looks like a file path are returned.  Pure language
    tags (e.g. ``python``, ``js``) are ignored because we cannot determine a
    target file name from them alone.
    """
    results: list[tuple[str, str]] = []
    for m in _CODE_BLOCK_RE.finditer(text):
        tag = m.group(1).strip()
        code = m.group(2)
        if _FILE_PATH_RE.match(tag):
            results.append((tag, code))
    return results


def write_code_blocks(project_path: Path, text: str) -> list[str]:
    """Extract fenced code blocks from *text* and write them under *project_path*.

    Returns the list of relative file paths that were written.
    """
    written: list[str] = []
    for filename, content in extract_code_blocks(text):
        target = project_path / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(filename)
        logger.info("Wrote code block to %s", target)
    return written


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
            "### Parallel Sub-Agents\n"
            "When your task involves 5+ independent file modifications or independent subtasks, "
            "use the Agent tool to parallelize:\n"
            "- Spawn one sub-agent per independent file or module\n"
            "- Each sub-agent gets a focused, self-contained instruction\n"
            "- Do NOT spawn sub-agents for sequential work (where step N depends on step N-1)\n\n"
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
        project_path = Path(context.project_path)

        # Context reset support: load existing HANDOFF.md if present
        # so the builder can resume from a previous context reset.
        from claw_forge.harness.context_reset import ContextResetManager
        threshold = int(context.config.get("context_reset_threshold", 80))
        reset_mgr = ContextResetManager(project_path, threshold=threshold)
        existing_handoff = reset_mgr.load_handoff()
        if existing_handoff:
            prompt = reset_mgr.build_reset_prompt(existing_handoff) + "\n\n" + prompt

        result = await collect_result(
            prompt,
            cwd=project_path,
            allowed_tools=["Read", "Write", "Edit", "Bash"],
        )

        # API-only mode: the LLM may return code in fenced blocks without
        # using tool calls to write files.  Parse and materialise them.
        written_files: list[str] = []
        if result:
            written_files = write_code_blocks(project_path, result)

        # Record a tool call for the completed execution and save a
        # handoff artifact so the next invocation can resume cleanly.
        from claw_forge.harness.handoff import HandoffArtifact
        reset_mgr.record_tool_call()
        handoff = HandoffArtifact(
            completed=[f"Task {context.task_id}"],
            state=[f"Files written: {written_files}"] if written_files else ["No files written"],
            next_steps=["Continue with next task"],
            decisions_made=[],
            quality_bar="Pending review",
        )
        reset_mgr.save_handoff(handoff)

        metadata: dict[str, object] = {
            "plugin": self.name,
            "task_id": context.task_id,
            "written_files": written_files,
            "context_reset_status": reset_mgr.get_status(),
        }

        return PluginResult(
            success=True,
            output=result or "Coding task completed",
            metadata=metadata,
        )
