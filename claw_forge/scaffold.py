"""Project scaffolding — generates CLAUDE.md and copies commands on claw-forge init."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

COMMANDS_SCAFFOLD_DIR = Path(__file__).parent / "commands_scaffold"
SPEC_TEMPLATE = Path(__file__).parent / "spec" / "app_spec.template.xml"

# ---------------------------------------------------------------------------
# Stack detection
# ---------------------------------------------------------------------------

_STACK_INDICATORS: list[tuple[str, str, str, str]] = [
    # (filename, language, framework, package_manager)
    ("pyproject.toml", "python", "", "uv"),
    ("setup.py", "python", "", "pip"),
    ("setup.cfg", "python", "", "pip"),
    ("requirements.txt", "python", "", "pip"),
    ("Cargo.toml", "rust", "", "cargo"),
    ("go.mod", "go", "", "go"),
    ("package.json", "node", "", "npm"),
]

_FRAMEWORK_INDICATORS: list[tuple[str, str]] = [
    # (filename_or_glob, framework)
    ("manage.py", "django"),
    ("wsgi.py", "django"),
    ("asgi.py", "fastapi_or_django"),
    ("next.config.js", "next"),
    ("next.config.ts", "next"),
    ("nuxt.config.js", "nuxt"),
    ("nuxt.config.ts", "nuxt"),
    ("vite.config.js", "vite"),
    ("vite.config.ts", "vite"),
    ("angular.json", "angular"),
    ("svelte.config.js", "svelte"),
]

_SOLIDITY_INDICATORS = [
    "hardhat.config.js", "hardhat.config.ts", "foundry.toml", "truffle-config.js"
]


def detect_stack(project_path: Path) -> dict[str, str]:
    """Detect language, framework, package manager, test runner from project files.

    Returns dict with keys: language, framework, package_manager, test_runner, extras.
    Checks for: pyproject.toml/setup.py (Python), package.json (Node), go.mod (Go),
    Cargo.toml (Rust), hardhat.config.js/foundry.toml (Solidity),
    requirements.txt, Dockerfile, docker-compose.yml.
    """
    result: dict[str, str] = {
        "language": "unknown",
        "framework": "unknown",
        "package_manager": "unknown",
        "test_runner": "unknown",
        "extras": "",
    }

    # Primary language detection
    for filename, language, framework, package_manager in _STACK_INDICATORS:
        if (project_path / filename).exists():
            result["language"] = language
            if framework:
                result["framework"] = framework
            result["package_manager"] = package_manager
            break

    # Framework detection
    if result["framework"] == "unknown":
        for filename, framework in _FRAMEWORK_INDICATORS:
            if (project_path / filename).exists():
                result["framework"] = framework
                break

    # Test runner detection
    lang = result["language"]
    if lang == "python":
        if (project_path / "pytest.ini").exists() or (project_path / "pyproject.toml").exists():
            result["test_runner"] = "pytest"
        else:
            result["test_runner"] = "pytest"
    elif lang == "node":
        pkg_json = project_path / "package.json"
        if pkg_json.exists():
            content = pkg_json.read_text()
            if "vitest" in content:
                result["test_runner"] = "vitest"
            elif "jest" in content:
                result["test_runner"] = "jest"
            else:
                result["test_runner"] = "jest"
    elif lang == "go":
        result["test_runner"] = "go test"
    elif lang == "rust":
        result["test_runner"] = "cargo test"

    # Extras (Solidity, Docker, etc.)
    extras: list[str] = []
    for sol_file in _SOLIDITY_INDICATORS:
        if (project_path / sol_file).exists():
            extras.append("solidity")
            break
    if (project_path / "Dockerfile").exists() or (project_path / "docker-compose.yml").exists():
        extras.append("docker")
    result["extras"] = ",".join(extras)

    return result


# ---------------------------------------------------------------------------
# CLAUDE.md generation
# ---------------------------------------------------------------------------

_BUILD_SECTIONS: dict[str, str] = {
    "python": (
        "## Build & Test\n"
        "- Install: `uv sync`\n"
        "- Test: `uv run pytest tests/ -q`\n"
        "- Lint: `uv run ruff check . && uv run mypy .`\n"
        "- Type check: `uv run pyright`\n"
    ),
    "node": (
        "## Build & Test\n"
        "- Install: `npm install`\n"
        "- Test: `npx jest` or `npx vitest`\n"
        "- Lint: `npx eslint . && npx tsc --noEmit`\n"
    ),
    "go": (
        "## Build & Test\n"
        "- Build: `go build ./...`\n"
        "- Test: `go test ./... -v`\n"
        "- Lint: `go vet ./... && staticcheck ./...`\n"
    ),
    "rust": (
        "## Build & Test\n"
        "- Build: `cargo build`\n"
        "- Test: `cargo test`\n"
        "- Lint: `cargo clippy -- -D warnings`\n"
    ),
    "unknown": (
        "## Build & Test\n"
        "- Add your build/test/lint commands here\n"
    ),
}

_AGENT_NOTES = (
    "## claw-forge Agent Notes\n"
    "- State service: http://localhost:8888\n"
    "- Report task complete: PATCH /features/{id} with status=done\n"
    "- Request human input: POST /features/{id}/human-input\n"
    "- Skills available: see skills/ directory (auto-injected based on file types)\n"
)


def generate_claude_md(project_path: Path) -> str:
    """Generate a CLAUDE.md tailored to the detected stack.

    Includes:
    - Project overview section (placeholder for user to fill)
    - Detected stack summary
    - Build, test, lint commands for that stack
    - claw-forge agent instructions
    - Link to skills available
    """
    stack = detect_stack(project_path)
    lang = stack.get("language", "unknown")
    framework = stack.get("framework", "unknown")
    extras = stack.get("extras", "")

    lines: list[str] = [
        "# CLAUDE.md\n",
        "> Auto-generated by claw-forge. Edit freely — this file is yours.\n",
        "\n",
        "## Project Overview\n",
        "<!-- TODO: describe what this project does -->\n",
        "\n",
        "## Stack\n",
        f"- Language: {lang}\n",
        f"- Framework: {framework}\n",
    ]
    if extras:
        lines.append(f"- Extras: {extras}\n")
    lines.append("\n")
    lines.append(_BUILD_SECTIONS.get(lang, _BUILD_SECTIONS["unknown"]))
    lines.append("\n")
    lines.append(_AGENT_NOTES)

    return "".join(lines)


# ---------------------------------------------------------------------------
# Command scaffolding
# ---------------------------------------------------------------------------


def scaffold_commands(project_path: Path) -> list[str]:
    """Copy .claude/commands/ from package into project_path/.claude/commands/.

    - Creates .claude/commands/ if not exists
    - Copies each .md from COMMANDS_SCAFFOLD_DIR
    - Skips files that already exist (don't overwrite user customisations)
    - Returns list of files copied
    """
    dest_dir = project_path / ".claude" / "commands"
    dest_dir.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    if not COMMANDS_SCAFFOLD_DIR.exists():
        return copied

    for src in sorted(COMMANDS_SCAFFOLD_DIR.glob("*.md")):
        dest = dest_dir / src.name
        if dest.exists():
            continue
        shutil.copy2(src, dest)
        copied.append(str(dest))

    return copied


# ---------------------------------------------------------------------------
# Full scaffold
# ---------------------------------------------------------------------------


_CLAUDE_SETTINGS = """\
{
  "enableAllProjectMcpServers": true
}
"""


def scaffold_dot_claude(project_path: Path) -> bool:
    """Ensure .claude/ directory exists with a settings.json.

    Returns True if the directory was newly created.
    """
    dot_claude = project_path / ".claude"
    created = not dot_claude.exists()
    dot_claude.mkdir(parents=True, exist_ok=True)

    settings = dot_claude / "settings.json"
    if not settings.exists():
        settings.write_text(_CLAUDE_SETTINGS, encoding="utf-8")

    return created


def scaffold_project(project_path: Path) -> dict[str, Any]:
    """Run full scaffold: generate CLAUDE.md, ensure .claude/, copy commands.

    Returns dict:
      claude_md_written: bool     — True if CLAUDE.md was created
      dot_claude_created: bool    — True if .claude/ was newly created
      commands_copied: list[str]
      spec_example_written: bool  — True if app_spec.example.xml was created
      stack: dict
    """
    stack = detect_stack(project_path)

    claude_md_path = project_path / "CLAUDE.md"
    claude_md_written = False
    if not claude_md_path.exists():
        claude_md_path.write_text(generate_claude_md(project_path), encoding="utf-8")
        claude_md_written = True

    dot_claude_created = scaffold_dot_claude(project_path)
    commands_copied = scaffold_commands(project_path)

    # Copy spec template so users have a concrete XML example to reference
    spec_example_path = project_path / "app_spec.example.xml"
    spec_example_written = False
    if not spec_example_path.exists() and SPEC_TEMPLATE.exists():
        shutil.copy2(SPEC_TEMPLATE, spec_example_path)
        spec_example_written = True

    return {
        "claude_md_written": claude_md_written,
        "dot_claude_created": dot_claude_created,
        "commands_copied": commands_copied,
        "spec_example_written": spec_example_written,
        "stack": stack,
    }
