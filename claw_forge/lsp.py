"""LSP skill auto-detection and injection for Claude agent SDK."""
from __future__ import annotations

from pathlib import Path

from claude_agent_sdk.types import SdkPluginConfig

SKILLS_DIR = Path(__file__).parent.parent / "skills"

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
