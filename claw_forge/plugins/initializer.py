"""Initializer plugin — project analysis and manifest generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claw_forge.plugins.base import BasePlugin, PluginContext, PluginResult


class InitializerPlugin(BasePlugin):
    """Analyzes a project and generates a session manifest."""

    @property
    def name(self) -> str:
        return "initializer"

    @property
    def description(self) -> str:
        return "Analyze project structure, detect language/framework, generate session manifest"

    def get_system_prompt(self, context: PluginContext) -> str:
        return (
            "You are a project analyzer. Examine the project structure, identify the "
            "language, framework, build system, and key files. Generate a comprehensive "
            "session manifest that will help other agents understand and work with this project.\n\n"
            "Output a JSON manifest with: project_name, language, framework, description, "
            "key_files (with roles), build_commands, test_commands, and any special notes."
        )

    async def execute(self, context: PluginContext) -> PluginResult:
        project = Path(context.project_path)
        if not project.exists():
            return PluginResult(success=False, output=f"Project path not found: {project}")

        analysis = self._analyze_project(project)
        return PluginResult(
            success=True,
            output=f"Project analyzed: {analysis.get('language', 'unknown')} / {analysis.get('framework', 'unknown')}",
            metadata=analysis,
        )

    def _analyze_project(self, path: Path) -> dict[str, Any]:
        indicators: dict[str, tuple[str, str]] = {
            "pyproject.toml": ("python", ""),
            "setup.py": ("python", ""),
            "Cargo.toml": ("rust", ""),
            "go.mod": ("go", ""),
            "package.json": ("javascript", "node"),
            "tsconfig.json": ("typescript", ""),
            "pom.xml": ("java", "maven"),
            "build.gradle": ("java", "gradle"),
            "CMakeLists.txt": ("cpp", "cmake"),
            "Makefile": ("c", "make"),
        }

        language = "unknown"
        framework = ""
        key_files: list[str] = []

        for filename, (lang, fw) in indicators.items():
            if (path / filename).exists():
                language = lang
                if fw:
                    framework = fw
                key_files.append(filename)
                break

        # Collect key files
        for pattern in ["README*", "LICENSE*", "Dockerfile", ".github/workflows/*"]:
            key_files.extend(str(f.relative_to(path)) for f in path.glob(pattern) if f.is_file())

        return {
            "language": language,
            "framework": framework,
            "key_files": key_files[:20],
            "has_tests": any(
                (path / d).exists() for d in ["tests", "test", "spec", "__tests__"]
            ),
            "has_ci": (path / ".github" / "workflows").exists(),
        }
