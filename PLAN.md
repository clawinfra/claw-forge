# PLAN.md — Brownfield Project Support

**Author:** Alex Chen  
**Date:** 2026-03-02  
**Status:** Ready for Builder

---

## Architecture Overview

```
                    CLI Layer (cli.py)
                         │
         ┌───────────────┼───────────────┐
         │               │               │
   analyze cmd      add cmd          fix cmd
         │               │               │
         ▼               ▼               ▼
  BrownfieldAnalyzer   BrownfieldAdd   BrownfieldFix
  (plugins/analyzer.py) (plugins/brownfield_add.py) (plugins/brownfield_fix.py)
         │               │               │
         │               ├───────────────┤
         │               │               │
         ▼               ▼               ▼
  brownfield_manifest   Reads manifest   Reads manifest
  .json written         + runs agent     + runs agent
                        via runner.py    via runner.py
                              │
                              ▼
                     collect_result()
                     (agent/runner.py)
```

**Data flow for `claw-forge add`:**

```
User: claw-forge add "Add rate limiting"
  │
  ├─ 1. Check brownfield_manifest.json exists
  │     └─ If missing → run BrownfieldAnalyzer.execute() first
  │
  ├─ 2. Read manifest → build brownfield-aware system prompt
  │
  ├─ 3. Create git branch feat/<slug>
  │
  ├─ 4. Run existing tests → capture baseline
  │
  ├─ 5. Run agent via collect_result() with:
  │     - Brownfield system prompt (conventions, patterns, manifest)
  │     - CodingPlugin-style tool list
  │     - cwd = project directory
  │
  ├─ 6. Run tests again → must pass (baseline + new)
  │
  └─ 7. Commit on feature branch
```

---

## New Files

### 1. `claw_forge/plugins/analyzer.py` — BrownfieldAnalyzer

```python
"""Brownfield project analyzer — scans existing codebases."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claw_forge.plugins.base import BasePlugin, PluginContext, PluginResult


# ── Stack Detection ──────────────────────────────────────────────────────────

# Map config files → language/framework/package_manager/test_runner
STACK_MARKERS: dict[str, dict[str, str]] = {
    "pyproject.toml": {"language": "python", "package_manager": "uv"},
    "setup.py": {"language": "python", "package_manager": "pip"},
    "setup.cfg": {"language": "python", "package_manager": "pip"},
    "requirements.txt": {"language": "python", "package_manager": "pip"},
    "package.json": {"language": "javascript", "package_manager": "npm"},
    "yarn.lock": {"language": "javascript", "package_manager": "yarn"},
    "pnpm-lock.yaml": {"language": "javascript", "package_manager": "pnpm"},
    "Cargo.toml": {"language": "rust", "package_manager": "cargo", "test_runner": "cargo test"},
    "go.mod": {"language": "go", "package_manager": "go", "test_runner": "go test"},
    "Gemfile": {"language": "ruby", "package_manager": "bundler"},
    "composer.json": {"language": "php", "package_manager": "composer"},
}

FRAMEWORK_MARKERS: dict[str, str] = {
    "fastapi": "fastapi",
    "flask": "flask",
    "django": "django",
    "express": "express",
    "next": "nextjs",
    "react": "react",
    "vue": "vue",
    "angular": "angular",
    "actix": "actix-web",
    "axum": "axum",
    "gin": "gin",
    "echo": "echo",
    "rails": "rails",
    "laravel": "laravel",
}

TEST_RUNNER_MARKERS: dict[str, str] = {
    "pytest": "pytest",
    "unittest": "unittest",
    "jest": "jest",
    "vitest": "vitest",
    "mocha": "mocha",
    "rspec": "rspec",
    "phpunit": "phpunit",
}


class BrownfieldAnalyzer(BasePlugin):
    """Analyzes an existing codebase and produces brownfield_manifest.json."""

    @property
    def name(self) -> str:
        return "brownfield-analyzer"

    @property
    def description(self) -> str:
        return "Analyze existing codebase: stack, conventions, tests, hot files"

    def get_system_prompt(self, context: PluginContext) -> str:
        return ""  # Analyzer doesn't use an agent — it's pure Python analysis

    async def execute(self, context: PluginContext) -> PluginResult:
        """Run full analysis pipeline and write brownfield_manifest.json.

        Returns PluginResult with:
          - success: True if analysis completed
          - output: Human-readable summary string
          - metadata: The full manifest dict
          - files_created: ["brownfield_manifest.json"]
        """
        ...

    def _detect_stack(self, project: Path) -> dict[str, str]:
        """Detect language, framework, package_manager, test_runner.

        Scans for marker files (pyproject.toml, package.json, Cargo.toml, etc.)
        then reads dependency files to detect framework and test runner.

        Args:
            project: Path to project root.

        Returns:
            Dict with keys: language, language_version, framework,
            package_manager, test_runner. Values are empty string if unknown.
        """
        ...

    def _detect_framework(self, project: Path, language: str) -> str:
        """Read dependency files to detect framework.

        For Python: reads pyproject.toml [project.dependencies] or
        requirements.txt. For JS: reads package.json dependencies.
        For Rust: reads Cargo.toml [dependencies].

        Args:
            project: Path to project root.
            language: Detected language string.

        Returns:
            Framework name or empty string.
        """
        ...

    def _detect_test_runner(self, project: Path, language: str) -> str:
        """Detect test runner from dev dependencies or config files.

        Checks: pyproject.toml [tool.pytest], jest.config.*, vitest.config.*,
        Cargo.toml [[test]], etc.

        Args:
            project: Path to project root.
            language: Detected language string.

        Returns:
            Test runner name or empty string.
        """
        ...

    def _detect_language_version(self, project: Path, language: str) -> str:
        """Detect language version from config files.

        Python: pyproject.toml requires-python or .python-version.
        Node: package.json engines.node or .nvmrc.
        Rust: rust-toolchain.toml or cargo --version.
        Go: go.mod go directive.

        Args:
            project: Path to project root.
            language: Detected language string.

        Returns:
            Version string or empty string.
        """
        ...

    def _get_hot_files(
        self, project: Path, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Find most-changed files via git log --stat.

        Runs: git -C <project> log --format= --name-only --diff-filter=AMRC
        Counts occurrences of each file path, returns top N.

        Filters out:
          - Files that no longer exist on disk
          - Lock files, node_modules, __pycache__, .git
          - Binary files (images, compiled)

        Args:
            project: Path to project root (must be a git repo).
            limit: Max number of hot files to return.

        Returns:
            List of {"path": str, "change_count": int, "role": str}.
            role is inferred from path (e.g. "test suite" for tests/ files,
            "configuration" for config files, "source" for src/ files).
        """
        ...

    def _detect_conventions(self, project: Path, language: str) -> dict[str, str]:
        """Detect code conventions by sampling source files.

        Reads up to 5 source files and analyzes:
        - naming: snake_case vs camelCase vs PascalCase (from function/variable names)
        - error_handling: pattern detection (try/except, Result<>, .catch, etc.)
        - logging: library detection (logging, structlog, winston, tracing, etc.)
        - imports: style detection (absolute vs relative, grouped, etc.)

        Args:
            project: Path to project root.
            language: Detected language string.

        Returns:
            Dict with keys: naming, error_handling, logging, imports.
        """
        ...

    def _run_test_baseline(
        self, project: Path, test_runner: str
    ) -> dict[str, Any]:
        """Run the test suite and capture baseline results.

        Executes the test command (e.g. pytest --tb=no -q, npm test, cargo test)
        with a timeout of 300 seconds.

        Parses output to extract:
        - total_tests: int
        - passing: int
        - failing: int
        - coverage_pct: float (if coverage data available, else -1)

        Also stores test_command used.

        Args:
            project: Path to project root.
            test_runner: Name of test runner (pytest, jest, etc.)

        Returns:
            Dict with keys: framework, total_tests, passing, failing,
            coverage_pct, test_command.
        """
        ...

    def _detect_entry_points(self, project: Path, language: str) -> list[dict[str, str]]:
        """Find project entry points.

        Checks for:
        - Python: __main__.py, manage.py, app.py, main.py, pyproject.toml [project.scripts]
        - JS: package.json "main"/"bin", index.js/ts
        - Rust: src/main.rs, src/lib.rs
        - Go: main.go, cmd/

        Args:
            project: Path to project root.
            language: Detected language string.

        Returns:
            List of {"type": str, "path": str, "description": str}.
            type is one of: "cli", "web", "lib", "config", "test".
        """
        ...

    def _detect_architecture(
        self, project: Path, language: str
    ) -> dict[str, Any]:
        """Infer architecture layers and patterns from directory structure.

        Scans top-level and second-level directories for common patterns:
        - layers: ["api", "service", "model"] based on dir names
        - patterns: ["MVC", "repository", "dependency injection"] based on heuristics
        - key_modules: [{path, role}] for important directories

        Args:
            project: Path to project root.
            language: Detected language string.

        Returns:
            Dict with keys: layers (list[str]), patterns (list[str]),
            key_modules (list[dict[str, str]]).
        """
        ...

    def _build_manifest(
        self,
        project: Path,
        stack: dict[str, str],
        conventions: dict[str, str],
        test_baseline: dict[str, Any],
        hot_files: list[dict[str, Any]],
        entry_points: list[dict[str, str]],
        architecture: dict[str, Any],
    ) -> dict[str, Any]:
        """Assemble the full brownfield_manifest.json dict.

        Args:
            project: Path to project root.
            stack: From _detect_stack().
            conventions: From _detect_conventions().
            test_baseline: From _run_test_baseline().
            hot_files: From _get_hot_files().
            entry_points: From _detect_entry_points().
            architecture: From _detect_architecture().

        Returns:
            Complete manifest dict matching the brownfield_manifest.json schema.
        """
        ...

    def _infer_role_from_path(self, file_path: str) -> str:
        """Infer a human-readable role from a file path.

        Examples:
          "tests/test_auth.py" → "test suite"
          "src/models/user.py" → "data model"
          "src/api/routes.py" → "API endpoint"
          "Dockerfile" → "configuration"

        Args:
            file_path: Relative path string.

        Returns:
            Role string.
        """
        ...
```

### 2. `claw_forge/plugins/brownfield_add.py` — BrownfieldAddPlugin

```python
"""Brownfield add plugin — adds a feature to an existing codebase."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from claw_forge.agent import collect_result
from claw_forge.plugins.base import BasePlugin, PluginContext, PluginResult


class BrownfieldAddPlugin(BasePlugin):
    """Agent plugin for adding a feature to an existing codebase."""

    @property
    def name(self) -> str:
        return "brownfield-add"

    @property
    def description(self) -> str:
        return "Add a feature to an existing codebase, respecting conventions"

    def get_system_prompt(self, context: PluginContext) -> str:
        """Build brownfield-aware system prompt.

        Includes:
        - Full manifest content (stack, conventions, architecture)
        - Instructions to match existing patterns
        - Instructions to run tests before and after
        - Instructions to never modify unrelated files
        - Instructions to commit on branch

        The manifest is read from context.metadata["manifest"] (dict).

        Args:
            context: PluginContext with metadata["manifest"] populated.

        Returns:
            System prompt string.
        """
        ...

    async def execute(self, context: PluginContext) -> PluginResult:
        """Execute the add-feature flow.

        Steps:
        1. Read brownfield_manifest.json from project root
           (or run BrownfieldAnalyzer if missing).
        2. Create git branch feat/<slug> from current HEAD.
        3. Run existing tests → abort if baseline fails.
        4. Build system prompt with manifest context.
        5. Call collect_result() with brownfield system prompt.
        6. Run tests again → report pass/fail.
        7. Git commit on branch.

        context.metadata must contain:
          - "feature": str — feature description
          - "model": str (optional) — model override

        Args:
            context: PluginContext with project_path and metadata.

        Returns:
            PluginResult with success, output, files_modified, files_created.
        """
        ...

    def _slugify(self, text: str) -> str:
        """Convert feature description to branch-safe slug.

        Lowercase, replace non-alphanumeric with hyphens, truncate to 60 chars,
        strip leading/trailing hyphens.

        Args:
            text: Feature description string.

        Returns:
            Branch-safe slug string.
        """
        ...

    def _create_branch(self, project: Path, branch_name: str) -> bool:
        """Create and checkout a new git branch.

        Runs: git -C <project> checkout -b <branch_name>

        Args:
            project: Path to project root.
            branch_name: Full branch name (e.g. "feat/add-rate-limiting").

        Returns:
            True if branch created successfully, False otherwise.
        """
        ...

    def _run_tests(self, project: Path, test_command: str) -> tuple[bool, str]:
        """Run test suite and return (passed, output).

        Runs the test_command with subprocess, timeout 300s.

        Args:
            project: Path to project root.
            test_command: Full test command string (e.g. "uv run pytest tests/ -v").

        Returns:
            Tuple of (all_passed: bool, output: str).
        """
        ...

    def _git_commit(self, project: Path, message: str) -> bool:
        """Stage all changes and commit.

        Runs: git -C <project> add -A && git -C <project> commit -m <message>
        Uses author: Alex Chen <alex.chen31337@gmail.com>

        Args:
            project: Path to project root.
            message: Commit message.

        Returns:
            True if commit succeeded, False otherwise.
        """
        ...

    def _ensure_manifest(self, project: Path) -> dict:
        """Load brownfield_manifest.json, running analyze if missing.

        Args:
            project: Path to project root.

        Returns:
            Manifest dict.

        Raises:
            RuntimeError: If analysis fails.
        """
        ...
```

### 3. `claw_forge/plugins/brownfield_fix.py` — BrownfieldFixPlugin

```python
"""Brownfield fix plugin — fixes bugs with reproduce-first protocol."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from claw_forge.agent import collect_result
from claw_forge.plugins.base import BasePlugin, PluginContext, PluginResult


class BrownfieldFixPlugin(BasePlugin):
    """Agent plugin for fixing bugs in existing codebases (Red-Green protocol)."""

    @property
    def name(self) -> str:
        return "brownfield-fix"

    @property
    def description(self) -> str:
        return "Fix a bug using reproduce-first protocol (Red-Green)"

    def get_system_prompt(self, context: PluginContext) -> str:
        """Build bug-fix system prompt with Red-Green protocol.

        Includes everything from BrownfieldAddPlugin.get_system_prompt() plus:
        - Explicit Red-Green protocol instructions:
          a. Write a failing test that reproduces the bug
          b. Run it — must FAIL (RED)
          c. Find root cause with systematic debugging
          d. Apply minimal surgical fix
          e. Run the test — must PASS (GREEN)
          f. Run full test suite — must be all green
        - Bug description from context.metadata["description"]
        - Manifest conventions

        Args:
            context: PluginContext with metadata["manifest"] and
                metadata["description"].

        Returns:
            System prompt string.
        """
        ...

    async def execute(self, context: PluginContext) -> PluginResult:
        """Execute the bug-fix flow.

        Steps:
        1. Read brownfield_manifest.json (or run analyzer if missing).
        2. Create git branch fix/<slug> from current HEAD.
        3. Run existing tests → abort if baseline fails.
        4. Build Red-Green system prompt.
        5. Call collect_result() with bug-fix prompt.
        6. Run tests → verify all pass.
        7. Git commit on branch.
        8. Generate fix report in metadata.

        context.metadata must contain:
          - "description": str — bug description
          - "model": str (optional) — model override

        Args:
            context: PluginContext with project_path and metadata.

        Returns:
            PluginResult with metadata["fix_report"] containing:
              - bug_description: str
              - branch: str
              - test_added: str (path to new test)
              - files_modified: list[str]
              - root_cause: str (from agent output)
        """
        ...

    def _slugify(self, text: str) -> str:
        """Same as BrownfieldAddPlugin._slugify.

        NOTE for Builder: Extract to a shared utility function
        in claw_forge/plugins/brownfield_utils.py to avoid duplication.
        """
        ...

    def _create_branch(self, project: Path, branch_name: str) -> bool:
        """Same as BrownfieldAddPlugin._create_branch.

        NOTE for Builder: Extract to shared brownfield_utils.py.
        """
        ...

    def _run_tests(self, project: Path, test_command: str) -> tuple[bool, str]:
        """Same as BrownfieldAddPlugin._run_tests.

        NOTE for Builder: Extract to shared brownfield_utils.py.
        """
        ...

    def _git_commit(self, project: Path, message: str) -> bool:
        """Same as BrownfieldAddPlugin._git_commit.

        NOTE for Builder: Extract to shared brownfield_utils.py.
        """
        ...

    def _ensure_manifest(self, project: Path) -> dict:
        """Same as BrownfieldAddPlugin._ensure_manifest.

        NOTE for Builder: Extract to shared brownfield_utils.py.
        """
        ...
```

### 4. `claw_forge/plugins/brownfield_utils.py` — Shared Utilities

```python
"""Shared utilities for brownfield plugins."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any


GIT_AUTHOR = "Alex Chen <alex.chen31337@gmail.com>"


def slugify(text: str, max_length: int = 60) -> str:
    """Convert text to branch-safe slug.

    Lowercase, replace non-alphanumeric with hyphens, collapse consecutive
    hyphens, truncate to max_length, strip leading/trailing hyphens.

    Args:
        text: Input string.
        max_length: Maximum slug length.

    Returns:
        Branch-safe slug.
    """
    ...


def create_git_branch(project: Path, branch_name: str) -> bool:
    """Create and checkout a new git branch.

    Args:
        project: Project root path.
        branch_name: Branch name (e.g. "feat/my-feature").

    Returns:
        True if successful.

    Raises:
        RuntimeError: If git command fails.
    """
    ...


def run_tests(project: Path, test_command: str, timeout: int = 300) -> tuple[bool, str]:
    """Run test suite and return (passed, output).

    Args:
        project: Project root path.
        test_command: Test command string.
        timeout: Timeout in seconds.

    Returns:
        (all_passed, output_text).
    """
    ...


def git_commit(project: Path, message: str) -> bool:
    """Stage all and commit with standard author.

    Args:
        project: Project root path.
        message: Commit message.

    Returns:
        True if successful.
    """
    ...


def load_manifest(project: Path) -> dict[str, Any] | None:
    """Load brownfield_manifest.json if it exists.

    Args:
        project: Project root path.

    Returns:
        Manifest dict or None.
    """
    ...


def ensure_manifest(project: Path) -> dict[str, Any]:
    """Load manifest, running BrownfieldAnalyzer if missing.

    Args:
        project: Project root path.

    Returns:
        Manifest dict.

    Raises:
        RuntimeError: If analysis fails.
    """
    ...


def build_brownfield_prompt_section(manifest: dict[str, Any]) -> str:
    """Build the brownfield context section for agent system prompts.

    Formats the manifest into a readable prompt section that tells
    the agent about the project's stack, conventions, and patterns.

    Args:
        manifest: The brownfield manifest dict.

    Returns:
        Formatted prompt section string.
    """
    ...
```

---

## brownfield_manifest.json Schema

```json
{
  "version": "1.0",
  "generated_at": "ISO 8601 timestamp",
  "project_root": "absolute path string",
  "stack": {
    "language": "string (python|javascript|typescript|rust|go|ruby|php)",
    "language_version": "string (e.g. '3.12', '20', '1.75')",
    "framework": "string (e.g. 'fastapi', 'express', 'actix-web') or ''",
    "package_manager": "string (uv|pip|npm|yarn|pnpm|cargo|go|bundler|composer)",
    "test_runner": "string (pytest|jest|vitest|cargo test|go test|rspec|phpunit) or ''"
  },
  "conventions": {
    "naming": "string (snake_case|camelCase|PascalCase|kebab-case|mixed)",
    "error_handling": "string description of pattern",
    "logging": "string description of logging approach",
    "imports": "string description of import style"
  },
  "test_baseline": {
    "framework": "string — test runner name",
    "total_tests": "integer",
    "passing": "integer",
    "failing": "integer",
    "coverage_pct": "float (-1 if unknown)",
    "test_command": "string — exact command to run tests"
  },
  "hot_files": [
    {
      "path": "string — relative path from project root",
      "change_count": "integer — number of git commits touching this file",
      "role": "string — inferred role (e.g. 'authentication module')"
    }
  ],
  "entry_points": [
    {
      "type": "string (cli|web|lib|config|test)",
      "path": "string — relative path",
      "description": "string"
    }
  ],
  "architecture": {
    "layers": ["string — detected architectural layers"],
    "patterns": ["string — detected design patterns"],
    "key_modules": [
      {
        "path": "string — directory or file path",
        "role": "string — module purpose"
      }
    ]
  }
}
```

---

## CLI Interface Changes

### New commands to add in `claw_forge/cli.py`:

```python
@app.command()
def analyze(
    project: str = typer.Option(".", "--project", "-p"),
    config: str = typer.Option("claw-forge.yaml", "--config", "-c"),
) -> None:
    """Analyze an existing project and generate brownfield_manifest.json."""
    ...


@app.command()
def add(
    feature: str = typer.Argument(..., help="Feature description"),
    project: str = typer.Option(".", "--project", "-p"),
    config: str = typer.Option("claw-forge.yaml", "--config", "-c"),
    model: str = typer.Option(
        "claude-sonnet-4-20250514", "--model", "-m"
    ),
) -> None:
    """Add a feature to an existing codebase."""
    ...


@app.command()
def fix(
    description: str = typer.Argument(..., help="Bug description"),
    project: str = typer.Option(".", "--project", "-p"),
    config: str = typer.Option("claw-forge.yaml", "--config", "-c"),
    model: str = typer.Option(
        "claude-sonnet-4-20250514", "--model", "-m"
    ),
) -> None:
    """Fix a bug using reproduce-first protocol (Red-Green)."""
    ...
```

**Implementation pattern** (same as existing `init` command):
1. Create `PluginContext` with project_path, session_id, task_id
2. Set metadata (feature/description, model)
3. Call `asyncio.run(plugin.execute(ctx))`
4. Print results via `console`

---

## Agent System Prompts

### Brownfield Add Prompt (key sections)

```
You are an expert software engineer working on an EXISTING codebase.

## Project Context (from brownfield_manifest.json)
Stack: {stack.language} {stack.language_version} / {stack.framework}
Test runner: {stack.test_runner}
Test baseline: {test_baseline.passing}/{test_baseline.total_tests} passing

## CRITICAL RULES — Existing Codebase
1. Read brownfield_manifest.json first — understand the project before changing anything
2. Run existing tests FIRST: `{test_baseline.test_command}` — they MUST pass
3. Match existing conventions:
   - Naming: {conventions.naming}
   - Error handling: {conventions.error_handling}
   - Logging: {conventions.logging}
   - Imports: {conventions.imports}
4. NEVER modify files unrelated to your task
5. All existing tests must still pass after your changes
6. Add new tests for your feature
7. Commit with: git add -A && git commit -m "feat: <description>"

## Hot Files (most active — likely core business logic)
{formatted hot_files list}

## Architecture
Layers: {architecture.layers}
Patterns: {architecture.patterns}
Key modules: {formatted key_modules}

## Your Task
Add this feature: {feature_description}
```

### Brownfield Fix Prompt (additions)

```
## Bug Fix Protocol (Red-Green — MANDATORY)
You MUST follow this exact sequence:

### Step 1: RED — Write a failing test
- Write a test that reproduces the bug described below
- Run it — it MUST FAIL
- If it passes, your test doesn't reproduce the bug. Try again.

### Step 2: Find Root Cause
- Use systematic debugging: read code, add logging, trace the execution path
- Identify the EXACT line(s) causing the bug
- Document your root cause analysis

### Step 3: GREEN — Surgical Fix
- Apply the MINIMUM code change that fixes the bug
- Do NOT refactor, do NOT "improve" unrelated code
- Run your test — it MUST PASS now

### Step 4: Full Suite
- Run all tests: `{test_baseline.test_command}`
- ALL must pass (existing + your new test)

### Step 5: Commit
- git add -A && git commit -m "fix: <description>"

## Bug Description
{description}
```

---

## Integration Points

### With `runner.py`
- BrownfieldAdd and BrownfieldFix both call `collect_result()` from `claw_forge.agent`
- Same pattern as existing `CodingPlugin.execute()`
- Pass `cwd=Path(context.project_path)`, `allowed_tools=["Read", "Write", "Edit", "Bash"]`

### With `lsp.py`
- No changes needed. `run_agent()` already auto-detects LSP plugins via `detect_lsp_plugins(cwd)`
- Brownfield plugins pass `cwd` which triggers LSP detection automatically

### With `cli.py`
- Add 3 new `@app.command()` functions: `analyze`, `add`, `fix`
- Follow the exact pattern of the existing `init` command
- Use `asyncio.run(plugin.execute(ctx))` for async execution

### With `base.py`
- BrownfieldAnalyzer, BrownfieldAddPlugin, BrownfieldFixPlugin all extend `BasePlugin`
- Return `PluginResult` with standard fields
- Optionally register via entry_points in pyproject.toml

---

## Error Handling Strategy

| Scenario | Handling |
|---|---|
| Not a git repo | `PluginResult(success=False, output="Not a git repo: ...")` |
| No source files found | Return minimal manifest with empty fields |
| Git log fails | Skip hot_files, continue with other analysis |
| Test suite fails baseline | Abort add/fix with clear message: "Existing tests fail — fix them first" |
| Branch already exists | Append timestamp suffix: `feat/my-feature-1709350200` |
| Agent fails (collect_result empty) | Return `PluginResult(success=False, output="Agent did not produce output")` |
| Tests fail after agent changes | Return `PluginResult(success=False, output="Tests failed after changes: ...")` |
| subprocess timeout (300s) | Catch `subprocess.TimeoutExpired`, return failure result |
| brownfield_manifest.json parse error | Delete corrupted file, re-run analyze |

All subprocess calls use:
```python
subprocess.run(
    ["git", ...],  # No shell=True
    cwd=str(project),
    capture_output=True,
    text=True,
    timeout=300,
)
```

---

## Test Plan

### `tests/test_analyzer.py`

Test the `BrownfieldAnalyzer` in isolation with mocked filesystem and git.

| Test | What it tests | Mocking strategy |
|---|---|---|
| `test_detect_stack_python` | Detects Python from pyproject.toml | `tmp_path` with pyproject.toml |
| `test_detect_stack_javascript` | Detects JS from package.json | `tmp_path` with package.json |
| `test_detect_stack_rust` | Detects Rust from Cargo.toml | `tmp_path` with Cargo.toml |
| `test_detect_stack_go` | Detects Go from go.mod | `tmp_path` with go.mod |
| `test_detect_stack_unknown` | Returns empty for unknown project | Empty `tmp_path` |
| `test_detect_framework_fastapi` | Detects FastAPI from deps | pyproject.toml with fastapi dep |
| `test_detect_framework_express` | Detects Express from package.json | package.json with express dep |
| `test_detect_test_runner_pytest` | Detects pytest | pyproject.toml with [tool.pytest] |
| `test_detect_test_runner_jest` | Detects jest | package.json with jest dep |
| `test_hot_files_basic` | Parses git log output | `unittest.mock.patch("subprocess.run")` returning mock git log |
| `test_hot_files_filters_deleted` | Skips files no longer on disk | Mock git log + tmp_path missing files |
| `test_hot_files_empty_repo` | Returns empty list for new repo | Mock git log empty |
| `test_detect_conventions_python` | Detects snake_case, logging | `tmp_path` with sample .py files |
| `test_detect_conventions_javascript` | Detects camelCase | `tmp_path` with sample .js files |
| `test_run_test_baseline_pytest` | Parses pytest output | `mock.patch("subprocess.run")` returning pytest output |
| `test_run_test_baseline_timeout` | Handles test timeout | Mock TimeoutExpired |
| `test_run_test_baseline_no_tests` | Returns zeros when no tests | Mock empty test output |
| `test_detect_entry_points_python` | Finds main.py, manage.py | `tmp_path` with those files |
| `test_detect_architecture_layers` | Detects src/api, src/models | `tmp_path` with directory structure |
| `test_execute_full_pipeline` | End-to-end: creates manifest | `tmp_path` with full project + mocked git/subprocess |
| `test_execute_not_git_repo` | Fails gracefully for non-git | `tmp_path` without .git |
| `test_manifest_schema_valid` | Output matches JSON schema | Validate manifest structure after execute |
| `test_infer_role_from_path` | Various path → role mappings | Direct function call |

### `tests/test_brownfield_commands.py`

Test CLI commands and plugin execute flows.

| Test | What it tests | Mocking strategy |
|---|---|---|
| `test_analyze_command_basic` | CLI runs analyzer, writes manifest | `tmp_path` project + mock subprocess |
| `test_analyze_command_output` | CLI prints correct summary | Capture `console.print` |
| `test_add_command_basic` | CLI creates branch, runs agent | Mock `collect_result`, mock subprocess |
| `test_add_auto_analyzes` | Add runs analyze when no manifest | Mock BrownfieldAnalyzer + collect_result |
| `test_add_creates_branch` | Correct branch name from feature | Mock subprocess, verify git checkout -b |
| `test_add_baseline_fails` | Aborts if existing tests fail | Mock test runner returning failure |
| `test_add_tests_after_fail` | Reports failure if new tests fail | Mock agent succeeds, tests fail after |
| `test_fix_command_basic` | CLI creates branch, runs fix agent | Mock collect_result + subprocess |
| `test_fix_creates_correct_branch` | Branch is fix/<slug> | Verify subprocess call |
| `test_fix_baseline_fails` | Aborts if baseline tests fail | Mock test failure |
| `test_slugify_basic` | "Hello World" → "hello-world" | Direct function call |
| `test_slugify_special_chars` | Strips special chars | Direct function call |
| `test_slugify_truncation` | Truncates to 60 chars | Direct function call |
| `test_slugify_consecutive_hyphens` | Collapses hyphens | Direct function call |
| `test_create_branch_success` | Git branch created | Mock subprocess |
| `test_create_branch_already_exists` | Handles existing branch | Mock subprocess CalledProcessError |
| `test_run_tests_pass` | Returns (True, output) | Mock subprocess |
| `test_run_tests_fail` | Returns (False, output) | Mock subprocess returncode=1 |
| `test_run_tests_timeout` | Returns (False, timeout msg) | Mock TimeoutExpired |
| `test_git_commit_success` | Stages and commits | Mock subprocess |
| `test_build_brownfield_prompt` | Prompt includes manifest data | Direct function call |
| `test_ensure_manifest_exists` | Loads existing manifest | Write manifest to tmp_path |
| `test_ensure_manifest_missing` | Runs analyzer then loads | Mock BrownfieldAnalyzer |

---

## Constraints for Builder

- **Line length ≤ 100** — enforced by ruff
- **Full type annotations** on every function
- **No new dependencies** — use only: subprocess, pathlib, json, re, datetime (stdlib)
- **All existing 557+ tests must pass** — run `uv run pytest tests/ -x -q` before and after
- **New code ≥ 90% coverage** — use `uv run pytest --cov=claw_forge/plugins/analyzer --cov=claw_forge/plugins/brownfield_add --cov=claw_forge/plugins/brownfield_fix --cov=claw_forge/plugins/brownfield_utils tests/test_analyzer.py tests/test_brownfield_commands.py`
- **Git author:** Alex Chen / alex.chen31337@gmail.com
- **No `shell=True`** in any subprocess call
- **No `print()`** — use `logging` or Rich `console`
- **`from __future__ import annotations`** at top of every new file
- **Extract shared code** into `brownfield_utils.py` — don't duplicate slugify/branch/test/commit logic

---

## Files to Create

| File | Purpose |
|---|---|
| `claw_forge/plugins/analyzer.py` | BrownfieldAnalyzer plugin |
| `claw_forge/plugins/brownfield_add.py` | BrownfieldAddPlugin |
| `claw_forge/plugins/brownfield_fix.py` | BrownfieldFixPlugin |
| `claw_forge/plugins/brownfield_utils.py` | Shared utilities |
| `tests/test_analyzer.py` | Analyzer unit tests |
| `tests/test_brownfield_commands.py` | CLI + plugin tests |
| `docs/brownfield.md` | User guide (DONE — already written) |

## Files to Modify

| File | Change |
|---|---|
| `claw_forge/cli.py` | Add `analyze`, `add`, `fix` commands |
| `ARCHITECTURE.md` | Add brownfield section |
| `README.md` | Add brownfield section |

---

## Documentation Updates

### ARCHITECTURE.md Addition

Add a new section "### 10. Brownfield Support" after section 9:

```markdown
### 10. Brownfield Support

Three commands for working with existing codebases:

| Command | Plugin | Purpose |
|---|---|---|
| `analyze` | `BrownfieldAnalyzer` | Scan project → `brownfield_manifest.json` |
| `add` | `BrownfieldAddPlugin` | Add feature on branch, respecting conventions |
| `fix` | `BrownfieldFixPlugin` | Bug fix with Red-Green protocol |

`BrownfieldAnalyzer` is pure Python analysis (no agent needed). `add` and `fix`
call `collect_result()` from `claw_forge.agent` with brownfield-aware system prompts
that include project conventions from the manifest.

See [docs/brownfield.md](docs/brownfield.md) for the full user guide.
```

### README.md Addition

Add after the Quick Start section:

```markdown
## Brownfield Mode (Existing Projects)

Work on existing codebases — claw-forge analyzes your project and respects your patterns.

\```bash
# Analyze your project
claw-forge analyze --project ./myapp

# Add a feature (auto-analyzes if needed)
claw-forge add "Add rate limiting to API endpoints" --project ./myapp

# Fix a bug (Red-Green protocol)
claw-forge fix "Login 500 on emails with plus signs" --project ./myapp
\```

See [docs/brownfield.md](docs/brownfield.md) for the full guide.
```
