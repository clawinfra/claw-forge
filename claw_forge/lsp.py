"""LSP skill auto-detection and injection for Claude agent SDK."""
from __future__ import annotations

from pathlib import Path

from claude_agent_sdk.types import SdkPluginConfig

# After `uv tool install`, skills are bundled at claw_forge/skills/ (force-include).
# In dev mode, skills live at the repo root (parent.parent).
_pkg_skills = Path(__file__).parent / "skills"
_dev_skills = Path(__file__).parent.parent / "skills"
SKILLS_DIR = _pkg_skills if _pkg_skills.exists() else _dev_skills

# Map file extensions → skill directory names
EXT_TO_SKILL: dict[str, str] = {
    ".py": "pyright",
    ".pyi": "pyright",
    ".ts": "typescript-lsp",
    ".tsx": "typescript-lsp",
    ".js": "typescript-lsp",
    ".jsx": "typescript-lsp",
    ".go": "gopls",
    ".rs": "rust-analyzer",
    ".c": "clangd",
    ".cpp": "clangd",
    ".cc": "clangd",
    ".h": "clangd",
    ".hpp": "clangd",
    ".sol": "solidity-lsp",
}


def detect_lsp_plugins(project_path: str | Path) -> list[SdkPluginConfig]:
    """Scan project_path for source files, return SdkPluginConfig list
    for each detected language. Each config points to the bundled skill dir.
    Deduplicates — returns one plugin per language even if multiple ext match.
    Skips skills whose SKILL.md doesn't exist.
    """
    path = Path(project_path)
    if not path.is_dir():
        return []

    extensions: set[str] = set()
    for f in path.rglob("*"):
        if f.is_file():
            extensions.add(f.suffix.lower())

    return lsp_plugins_for_extensions(extensions)


async def detect_lsp_plugins_async(project_path: str | Path) -> list[SdkPluginConfig]:
    """Async wrapper — runs blocking rglob scan in a thread."""
    import asyncio
    return await asyncio.to_thread(detect_lsp_plugins, project_path)


def lsp_plugins_for_extensions(extensions: set[str]) -> list[SdkPluginConfig]:
    """Given a set of file extensions, return matching SdkPluginConfig list."""
    seen_skills: set[str] = set()
    plugins: list[SdkPluginConfig] = []

    for ext in sorted(extensions):  # sorted for deterministic ordering
        skill_name = EXT_TO_SKILL.get(ext)
        if skill_name is None or skill_name in seen_skills:
            continue

        skill_dir = SKILLS_DIR / skill_name
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue

        seen_skills.add(skill_name)
        plugins.append(SdkPluginConfig(type="local", path=str(skill_dir)))

    return plugins


# ---------------------------------------------------------------------------
# Context-based (non-LSP) skill injection
# ---------------------------------------------------------------------------

# Skills injected based on agent type
AGENT_TYPE_SKILLS: dict[str, list[str]] = {
    "coding": ["systematic-debug", "verification-gate", "test-driven"],
    "testing": ["test-driven", "verification-gate"],
    "reviewing": ["code-review", "security-audit"],
    "initializer": ["git-workflow"],
}

# Skills injected based on task description keywords
TASK_KEYWORD_SKILLS: dict[str, list[str]] = {
    "api": ["api-client"],
    "http": ["api-client"],
    "rest": ["api-client"],
    "database": ["database"],
    "sql": ["database"],
    "migration": ["database"],
    "docker": ["docker"],
    "container": ["docker"],
    "performance": ["performance"],
    "slow": ["performance"],
    "benchmark": ["performance"],
    "security": ["security-audit"],
    "vulnerability": ["security-audit"],
    "audit": ["security-audit"],
    "parallel": ["parallel-dispatch"],
    "concurrent": ["parallel-dispatch"],
    "git": ["git-workflow"],
    "branch": ["git-workflow"],
    "commit": ["git-workflow"],
    "research": ["web-research"],
    "search": ["web-research"],
}


def _skill_plugin(skill_name: str) -> SdkPluginConfig | None:
    """Return an SdkPluginConfig for a skill name, or None if SKILL.md is missing."""
    skill_dir = SKILLS_DIR / skill_name
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    return SdkPluginConfig(type="local", path=str(skill_dir))


def skills_for_agent(
    agent_type: str,
    task_description: str = "",
) -> list[SdkPluginConfig]:
    """Return SdkPluginConfig list for the given agent type and task keywords.

    Combines AGENT_TYPE_SKILLS (by agent_type) with TASK_KEYWORD_SKILLS (by
    keywords found in task_description). Deduplicates by skill name.

    Args:
        agent_type: Agent role — e.g. "coding", "testing", "reviewing", "initializer".
        task_description: Optional task text to scan for keyword-triggered skills.

    Returns:
        Deduplicated list of SdkPluginConfig pointing to matching skill dirs.
        Skips any skill whose SKILL.md is not present on disk.
    """
    seen: set[str] = set()
    skill_names: list[str] = []

    # Agent-type driven skills
    for name in AGENT_TYPE_SKILLS.get(agent_type, []):
        if name not in seen:
            seen.add(name)
            skill_names.append(name)

    # Keyword-driven skills (case-insensitive match on task_description words)
    if task_description:
        lower = task_description.lower()
        for keyword, names in TASK_KEYWORD_SKILLS.items():
            if keyword in lower:
                for name in names:
                    if name not in seen:
                        seen.add(name)
                        skill_names.append(name)

    plugins: list[SdkPluginConfig] = []
    for name in skill_names:
        plugin = _skill_plugin(name)
        if plugin is not None:
            plugins.append(plugin)

    return plugins
