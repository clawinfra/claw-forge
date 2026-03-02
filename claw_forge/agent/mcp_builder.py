"""Build MCP server configs from claw-forge skill YAML definitions."""
from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]
from claude_agent_sdk import McpServerConfig


def skill_to_mcp(skill_path: Path) -> McpServerConfig | None:
    """Convert a SKILL.md or skill.yaml into an McpServerConfig if applicable.

    Args:
        skill_path: Path to the SKILL.md file (or any file inside a skill directory).

    Returns:
        A McpServerConfig TypedDict if the skill has an ``mcp`` section in its
        ``skill.yaml``, otherwise ``None``.
    """
    skill_yaml = skill_path.parent / "skill.yaml"
    if not skill_yaml.exists():
        return None

    with open(skill_yaml) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        return None

    mcp = data.get("mcp")
    if not mcp:
        return None

    # Build a McpStdioServerConfig (most common for CLI-based skills)
    config: McpServerConfig = {
        "command": mcp["command"],
    }
    if "args" in mcp:
        config["args"] = mcp["args"]  # type: ignore[typeddict-unknown-key]
    if "env" in mcp:
        config["env"] = mcp["env"]  # type: ignore[typeddict-unknown-key]

    return config


def load_skills_as_mcp(skills_dir: Path) -> dict[str, McpServerConfig]:
    """Load all skill directories that have MCP config.

    Args:
        skills_dir: Root directory containing skill subdirectories, each with a
            ``SKILL.md`` and optionally a ``skill.yaml``.

    Returns:
        Dict mapping skill name → McpServerConfig for each skill that declares
        an ``mcp`` section.
    """
    configs: dict[str, McpServerConfig] = {}
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        # Load skill.yaml to find the skill name
        skill_yaml = skill_md.parent / "skill.yaml"
        if skill_yaml.exists():
            with open(skill_yaml) as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict) and data.get("mcp"):
                name = data.get("name", skill_md.parent.name)
                cfg = skill_to_mcp(skill_md)
                if cfg is not None:
                    configs[name] = cfg
    return configs
