"""Tests for claw_forge.scaffold — detect_stack, generate_claude_md, scaffold_commands."""

from __future__ import annotations

from pathlib import Path

import pytest

from claw_forge.scaffold import (
    COMMANDS_SCAFFOLD_DIR,
    detect_stack,
    generate_claude_md,
    scaffold_commands,
    scaffold_project,
)

# ---------------------------------------------------------------------------
# detect_stack
# ---------------------------------------------------------------------------


def test_detect_stack_python_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")
    stack = detect_stack(tmp_path)
    assert stack["language"] == "python"


def test_detect_stack_python_setup_py(tmp_path: Path) -> None:
    (tmp_path / "setup.py").write_text("from setuptools import setup\n")
    stack = detect_stack(tmp_path)
    assert stack["language"] == "python"


def test_detect_stack_node_package_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "myapp"}\n')
    stack = detect_stack(tmp_path)
    assert stack["language"] == "node"


def test_detect_stack_go_mod(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module mymod\n\ngo 1.21\n")
    stack = detect_stack(tmp_path)
    assert stack["language"] == "go"


def test_detect_stack_cargo_toml(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'mylib'\n")
    stack = detect_stack(tmp_path)
    assert stack["language"] == "rust"


def test_detect_stack_solidity_hardhat(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "contracts"}\n')
    (tmp_path / "hardhat.config.js").write_text("module.exports = {};\n")
    stack = detect_stack(tmp_path)
    assert "solidity" in stack["extras"]


def test_detect_stack_solidity_foundry(tmp_path: Path) -> None:
    (tmp_path / "foundry.toml").write_text("[profile.default]\n")
    stack = detect_stack(tmp_path)
    assert "solidity" in stack["extras"]


def test_detect_stack_empty_dir(tmp_path: Path) -> None:
    stack = detect_stack(tmp_path)
    assert stack["language"] == "unknown"


def test_detect_stack_returns_all_keys(tmp_path: Path) -> None:
    stack = detect_stack(tmp_path)
    assert "language" in stack
    assert "framework" in stack
    assert "package_manager" in stack
    assert "test_runner" in stack
    assert "extras" in stack


def test_detect_stack_docker_extra(tmp_path: Path) -> None:
    (tmp_path / "Dockerfile").write_text("FROM python:3.11\n")
    stack = detect_stack(tmp_path)
    assert "docker" in stack["extras"]


def test_detect_stack_node_vitest(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "myapp", "devDependencies": {"vitest": "^1"}}')
    stack = detect_stack(tmp_path)
    assert stack["test_runner"] == "vitest"


# ---------------------------------------------------------------------------
# generate_claude_md
# ---------------------------------------------------------------------------


def test_generate_claude_md_python_contains_uv_pytest(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")
    md = generate_claude_md(tmp_path)
    assert "uv run pytest" in md


def test_generate_claude_md_node_contains_npm_install(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "myapp"}')
    md = generate_claude_md(tmp_path)
    assert "npm install" in md


def test_generate_claude_md_rust_contains_cargo_test(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'mylib'\n")
    md = generate_claude_md(tmp_path)
    assert "cargo test" in md


def test_generate_claude_md_go_contains_go_test(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module mymod\n")
    md = generate_claude_md(tmp_path)
    assert "go test" in md


def test_generate_claude_md_always_has_agent_notes(tmp_path: Path) -> None:
    md = generate_claude_md(tmp_path)
    assert "claw-forge Agent Notes" in md


def test_generate_claude_md_always_has_localhost_8888(tmp_path: Path) -> None:
    md = generate_claude_md(tmp_path)
    assert "http://localhost:8888" in md


def test_generate_claude_md_unknown_stack_generic(tmp_path: Path) -> None:
    md = generate_claude_md(tmp_path)
    assert "Add your build/test/lint commands here" in md


def test_generate_claude_md_contains_stack_summary(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    md = generate_claude_md(tmp_path)
    assert "python" in md


# ---------------------------------------------------------------------------
# scaffold_commands
# ---------------------------------------------------------------------------


def test_scaffold_commands_copies_md_files(tmp_path: Path) -> None:
    if not COMMANDS_SCAFFOLD_DIR.exists():
        pytest.skip("COMMANDS_SCAFFOLD_DIR not present in this environment")
    copied = scaffold_commands(tmp_path)
    dest_dir = tmp_path / ".claude" / "commands"
    assert dest_dir.exists()
    for path in copied:
        assert Path(path).exists()


def test_scaffold_commands_skips_existing_files(tmp_path: Path) -> None:
    if not COMMANDS_SCAFFOLD_DIR.exists():
        pytest.skip("COMMANDS_SCAFFOLD_DIR not present in this environment")
    # Create one file in advance
    dest_dir = tmp_path / ".claude" / "commands"
    dest_dir.mkdir(parents=True)
    src_files = list(COMMANDS_SCAFFOLD_DIR.glob("*.md"))
    if not src_files:
        pytest.skip("No .md files in COMMANDS_SCAFFOLD_DIR")
    existing = dest_dir / src_files[0].name
    original_content = "# my custom content\n"
    existing.write_text(original_content)

    scaffold_commands(tmp_path)
    # Existing file must not be overwritten
    assert existing.read_text() == original_content


def test_scaffold_commands_returns_list_of_copied(tmp_path: Path) -> None:
    if not COMMANDS_SCAFFOLD_DIR.exists():
        pytest.skip("COMMANDS_SCAFFOLD_DIR not present in this environment")
    copied = scaffold_commands(tmp_path)
    assert isinstance(copied, list)


def test_scaffold_commands_creates_dir_if_not_exists(tmp_path: Path) -> None:
    dest_dir = tmp_path / ".claude" / "commands"
    assert not dest_dir.exists()
    scaffold_commands(tmp_path)
    assert dest_dir.exists()


def test_scaffold_commands_empty_scaffold_dir_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If COMMANDS_SCAFFOLD_DIR doesn't exist, returns empty list."""
    import claw_forge.scaffold as scaffold_mod
    monkeypatch.setattr(scaffold_mod, "COMMANDS_SCAFFOLD_DIR", tmp_path / "nonexistent")
    result = scaffold_commands(tmp_path / "project")
    assert result == []


def test_scaffold_commands_copies_into_correct_subdir(tmp_path: Path) -> None:
    """Verify files land in .claude/commands/ not project root."""
    if not COMMANDS_SCAFFOLD_DIR.exists():
        pytest.skip("COMMANDS_SCAFFOLD_DIR not present in this environment")
    copied = scaffold_commands(tmp_path)
    for path in copied:
        assert ".claude/commands" in path or str(tmp_path / ".claude" / "commands") in path


# ---------------------------------------------------------------------------
# scaffold_project
# ---------------------------------------------------------------------------


def test_scaffold_project_returns_correct_keys(tmp_path: Path) -> None:
    result = scaffold_project(tmp_path)
    assert "claude_md_written" in result
    assert "commands_copied" in result
    assert "stack" in result


def test_scaffold_project_writes_claude_md(tmp_path: Path) -> None:
    result = scaffold_project(tmp_path)
    assert (tmp_path / "CLAUDE.md").exists()
    assert result["claude_md_written"] is True


def test_scaffold_project_idempotent_claude_md(tmp_path: Path) -> None:
    """If CLAUDE.md already exists, don't overwrite it."""
    existing = tmp_path / "CLAUDE.md"
    existing.write_text("# My custom CLAUDE.md\n")
    result = scaffold_project(tmp_path)
    assert result["claude_md_written"] is False
    assert existing.read_text() == "# My custom CLAUDE.md\n"


def test_scaffold_project_stack_has_language(tmp_path: Path) -> None:
    result = scaffold_project(tmp_path)
    assert "language" in result["stack"]


def test_scaffold_project_python_stack(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    result = scaffold_project(tmp_path)
    assert result["stack"]["language"] == "python"


def test_scaffold_project_commands_copied_is_list(tmp_path: Path) -> None:
    result = scaffold_project(tmp_path)
    assert isinstance(result["commands_copied"], list)
