"""Tests for claw_forge.agent.mcp_builder."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from claw_forge.agent.mcp_builder import load_skills_as_mcp, skill_to_mcp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_skill(base: Path, name: str, skill_yaml_content: dict | None = None) -> Path:
    """Create a skill directory with a SKILL.md and optional skill.yaml."""
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"# {name}\n\nSkill documentation.\n")
    if skill_yaml_content is not None:
        (skill_dir / "skill.yaml").write_text(yaml.safe_dump(skill_yaml_content))
    return skill_dir / "SKILL.md"


# ---------------------------------------------------------------------------
# skill_to_mcp tests
# ---------------------------------------------------------------------------


class TestSkillToMcp:
    def test_returns_none_when_no_skill_yaml(self):
        with tempfile.TemporaryDirectory() as d:
            skill_md = _write_skill(Path(d), "my-skill")
            result = skill_to_mcp(skill_md)
        assert result is None

    def test_returns_none_when_skill_yaml_has_no_mcp_section(self):
        with tempfile.TemporaryDirectory() as d:
            skill_md = _write_skill(
                Path(d),
                "my-skill",
                {"name": "my-skill", "description": "A skill"},
            )
            result = skill_to_mcp(skill_md)
        assert result is None

    def test_returns_mcp_config_when_mcp_section_present(self):
        with tempfile.TemporaryDirectory() as d:
            skill_md = _write_skill(
                Path(d),
                "my-mcp-skill",
                {
                    "name": "my-mcp-skill",
                    "description": "An MCP skill",
                    "mcp": {
                        "command": "npx",
                        "args": ["-y", "@my/mcp-server"],
                        "env": {"MY_KEY": "value"},
                    },
                },
            )
            result = skill_to_mcp(skill_md)

        assert result is not None
        assert result["command"] == "npx"
        assert result["args"] == ["-y", "@my/mcp-server"]
        assert result["env"] == {"MY_KEY": "value"}

    def test_mcp_config_with_command_only(self):
        with tempfile.TemporaryDirectory() as d:
            skill_md = _write_skill(
                Path(d),
                "minimal-mcp",
                {
                    "name": "minimal-mcp",
                    "mcp": {"command": "python"},
                },
            )
            result = skill_to_mcp(skill_md)

        assert result is not None
        assert result["command"] == "python"
        assert "args" not in result
        assert "env" not in result

    def test_mcp_config_with_args_no_env(self):
        with tempfile.TemporaryDirectory() as d:
            skill_md = _write_skill(
                Path(d),
                "args-skill",
                {
                    "name": "args-skill",
                    "mcp": {"command": "node", "args": ["server.js"]},
                },
            )
            result = skill_to_mcp(skill_md)

        assert result is not None
        assert result["command"] == "node"
        assert result["args"] == ["server.js"]
        assert "env" not in result

    def test_returns_none_for_empty_skill_yaml(self):
        with tempfile.TemporaryDirectory() as d:
            skill_dir = Path(d) / "empty-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("# Empty\n")
            (skill_dir / "skill.yaml").write_text("")  # empty YAML → None

            result = skill_to_mcp(skill_dir / "SKILL.md")

        assert result is None

    def test_returns_none_for_mcp_false_in_skill_yaml(self):
        with tempfile.TemporaryDirectory() as d:
            skill_md = _write_skill(
                Path(d),
                "no-mcp",
                {"name": "no-mcp", "mcp": False},
            )
            result = skill_to_mcp(skill_md)
        assert result is None

    def test_returns_none_for_mcp_none_in_skill_yaml(self):
        with tempfile.TemporaryDirectory() as d:
            skill_md = _write_skill(
                Path(d),
                "null-mcp",
                {"name": "null-mcp", "mcp": None},
            )
            result = skill_to_mcp(skill_md)
        assert result is None


# ---------------------------------------------------------------------------
# load_skills_as_mcp tests
# ---------------------------------------------------------------------------


class TestLoadSkillsAsMcp:
    def test_empty_directory_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as d:
            result = load_skills_as_mcp(Path(d))
        assert result == {}

    def test_skills_without_mcp_are_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            _write_skill(Path(d), "skill-a", {"name": "skill-a"})
            _write_skill(Path(d), "skill-b", {"name": "skill-b", "description": "no mcp"})
            result = load_skills_as_mcp(Path(d))
        assert result == {}

    def test_skills_without_skill_yaml_are_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            _write_skill(Path(d), "skill-no-yaml")  # no skill.yaml
            result = load_skills_as_mcp(Path(d))
        assert result == {}

    def test_returns_mcp_skills_keyed_by_name(self):
        with tempfile.TemporaryDirectory() as d:
            _write_skill(
                Path(d),
                "mcp-skill",
                {
                    "name": "mcp-skill",
                    "mcp": {"command": "npx", "args": ["-y", "mcp-skill"]},
                },
            )
            result = load_skills_as_mcp(Path(d))

        assert "mcp-skill" in result
        assert result["mcp-skill"]["command"] == "npx"

    def test_mixed_skills_returns_only_mcp_ones(self):
        with tempfile.TemporaryDirectory() as d:
            _write_skill(Path(d), "no-mcp-skill", {"name": "no-mcp-skill"})
            _write_skill(
                Path(d),
                "has-mcp",
                {"name": "has-mcp", "mcp": {"command": "uvx", "args": ["has-mcp"]}},
            )
            result = load_skills_as_mcp(Path(d))

        assert "has-mcp" in result
        assert "no-mcp-skill" not in result
        assert len(result) == 1

    def test_multiple_mcp_skills(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(3):
                _write_skill(
                    Path(d),
                    f"mcp-{i}",
                    {"name": f"mcp-{i}", "mcp": {"command": f"cmd-{i}"}},
                )
            # One non-MCP skill
            _write_skill(Path(d), "plain", {"name": "plain"})

            result = load_skills_as_mcp(Path(d))

        assert len(result) == 3
        for i in range(3):
            assert f"mcp-{i}" in result
            assert result[f"mcp-{i}"]["command"] == f"cmd-{i}"

    def test_falls_back_to_dir_name_when_name_missing(self):
        """If skill.yaml has no 'name', fall back to directory name."""
        with tempfile.TemporaryDirectory() as d:
            skill_dir = Path(d) / "my-skill-dir"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("# skill\n")
            # skill.yaml with mcp but no 'name' key
            (skill_dir / "skill.yaml").write_text(
                yaml.safe_dump({"mcp": {"command": "run-it"}})
            )
            result = load_skills_as_mcp(Path(d))

        assert "my-skill-dir" in result
