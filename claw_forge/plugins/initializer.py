"""Initializer plugin — project analysis, spec parsing, and manifest generation."""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import Any

from claw_forge.plugins.base import BasePlugin, PluginContext, PluginResult

logger = logging.getLogger(__name__)


class InitializerPlugin(BasePlugin):
    """Analyzes a project and generates a session manifest.

    If a spec file is provided (via context.metadata["spec_file"]),
    parses it using ProjectSpec (XML or plain text) and returns
    granular features (typically 100-400 items).
    """

    @property
    def name(self) -> str:
        return "initializer"

    @property
    def description(self) -> str:
        return "Analyze project structure, detect language/framework, generate session manifest"

    def get_system_prompt(self, context: PluginContext) -> str:
        return (
            "You are a project initialization agent for claw-forge. Your job is to read "
            "`app_spec.txt`, break the project into atomic implementable features with "
            "dependencies, create those features in the state service, and set up the project "
            "structure.\n\n"
            "## Your Role\n"
            "- Parse app_spec.txt and extract implementable features\n"
            "- Define dependencies between features (DAG — no cycles)\n"
            "- Create feature entries in the state service\n"
            "- Set up project directory structure and git repo\n"
            "- Generate session_manifest.json for other agents\n"
            "- Do NOT implement any features — that's the coding agent's job\n\n"
            "## Feature Decomposition Rules\n"
            "Each feature must be: implementable in a single agent session (1-4 hours), "
            "testable in isolation, mergeable without breaking other features.\n\n"
            "Naming: `<verb> <noun>` — 'Create User model', 'Add auth middleware'\n\n"
            "Priority: 10=Foundation, 7-9=Core, 4-6=Secondary, 1-3=Polish/docs/CI\n\n"
            "## Steps\n"
            "1. Parse spec → extract project name, tech stack, features\n"
            "2. Generate feature graph (validate no cycles)\n"
            "3. Create session: POST http://localhost:8420/sessions\n"
            "4. Create all feature tasks: POST http://localhost:8420/sessions/$SESSION_ID/tasks\n"
            "5. Set up project structure (based on tech stack), initialize git\n"
            "6. Generate session_manifest.json\n"
            "7. Report complete: PATCH http://localhost:8420/sessions/$SESSION_ID\n\n"
            "## session_manifest.json structure\n"
            '{"project_name": ..., "project_path": ..., "session_id": ..., '
            '"tech_stack": ..., "state_service_url": "http://localhost:8420", '
            '"features": [{"task_id": ..., "title": ..., "status": "pending", '
            '"priority": ..., "depends_on": []}]}\n\n"'
            "Output a JSON manifest with: project_name, language, framework, description, "
            "key_files (with roles), build_commands, test_commands, and any special notes."
        )

    def _build_prompt(self, context: PluginContext) -> str:
        return (
            f"{self.get_system_prompt(context)}\n\n"
            f"Project path: {context.project_path}\n"
            f"Session: {context.session_id}\n"
            f"Task ID: {context.task_id}"
        )

    async def execute(self, context: PluginContext) -> PluginResult:
        project = Path(context.project_path)
        if not project.exists():
            return PluginResult(success=False, output=f"Project path not found: {project}")

        # Check if a spec file was provided
        spec_file = context.metadata.get("spec_file")
        if spec_file:
            return self._execute_with_spec(project, Path(spec_file))

        # Fallback to basic project analysis
        analysis = self._analyze_project(project)
        return PluginResult(
            success=True,
            output=(
                f"Project analyzed: {analysis.get('language', 'unknown')} / "
                f"{analysis.get('framework', 'unknown')}"
            ),
            metadata=analysis,
        )

    def _execute_with_spec(self, project: Path, spec_path: Path) -> PluginResult:
        """Parse a spec file and return features for bulk creation."""
        from claw_forge.spec import ProjectSpec

        # Resolve spec path relative to project if not absolute
        if not spec_path.is_absolute():
            spec_path = project / spec_path

        if not spec_path.exists():
            return PluginResult(
                success=False,
                output=f"Spec file not found: {spec_path}",
            )

        try:
            spec = ProjectSpec.from_file(spec_path)
        except Exception as exc:
            return PluginResult(
                success=False,
                output=f"Failed to parse spec: {exc}",
            )

        # Count categories
        category_counts = Counter(f.category for f in spec.features)
        num_features = len(spec.features)
        num_categories = len(category_counts)
        num_phases = len(spec.implementation_phases)

        logger.info(
            "Parsed %d features across %d categories in %d phases",
            num_features,
            num_categories,
            num_phases,
        )

        # Build feature list for bulk creation
        feature_list = []
        for i, feat in enumerate(spec.features):
            feature_list.append(
                {
                    "index": i,
                    "category": feat.category,
                    "name": feat.name,
                    "description": feat.description,
                    "steps": feat.steps,
                    "depends_on_indices": feat.depends_on_indices,
                }
            )

        # Build the summary
        category_summary = ", ".join(
            f"{cat} ({count})" for cat, count in category_counts.most_common()
        )

        # Compute wave count (number of distinct dependency layers)
        wave_count = self._compute_wave_count(spec.features)

        return PluginResult(
            success=True,
            output=(
                f"Parsed {num_features} features across {num_categories} categories "
                f"in {num_phases} phases"
            ),
            metadata={
                "project_name": spec.project_name,
                "overview": spec.overview,
                "tech_stack": {
                    "frontend_framework": spec.tech_stack.frontend_framework,
                    "frontend_port": spec.tech_stack.frontend_port,
                    "backend_runtime": spec.tech_stack.backend_runtime,
                    "backend_db": spec.tech_stack.backend_db,
                    "backend_port": spec.tech_stack.backend_port,
                },
                "feature_count": num_features,
                "category_counts": dict(category_counts),
                "category_summary": category_summary,
                "phase_count": num_phases,
                "phases": spec.implementation_phases,
                "wave_count": wave_count,
                "features": feature_list,
                "success_criteria": spec.success_criteria,
                "design_system": spec.design_system,
                "api_endpoints": spec.api_endpoints,
                "database_tables": spec.database_tables,
            },
        )

    @staticmethod
    def _compute_wave_count(features: list) -> int:
        """Compute number of dependency waves (topological layers).

        Wave 0 = features with no dependencies.
        Wave N = features whose deps are all in waves < N.
        """
        if not features:
            return 0

        num = len(features)
        wave: list[int] = [-1] * num

        # Features with no deps are wave 0
        for i, feat in enumerate(features):
            if not feat.depends_on_indices:
                wave[i] = 0

        changed = True
        while changed:
            changed = False
            for i, feat in enumerate(features):
                if wave[i] >= 0:
                    continue
                deps = feat.depends_on_indices
                # Filter valid deps
                valid_deps = [d for d in deps if 0 <= d < num]
                if not valid_deps:
                    wave[i] = 0
                    changed = True
                    continue
                if all(wave[d] >= 0 for d in valid_deps):
                    wave[i] = max(wave[d] for d in valid_deps) + 1
                    changed = True

        # Any still -1 are in cycles; assign max+1
        max_wave = max((w for w in wave if w >= 0), default=0)
        for i in range(num):
            if wave[i] < 0:
                wave[i] = max_wave + 1

        return max(wave) + 1 if wave else 0

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
            key_files.extend(
                str(f.relative_to(path)) for f in path.glob(pattern) if f.is_file()
            )

        return {
            "language": language,
            "framework": framework,
            "key_files": key_files[:20],
            "has_tests": any(
                (path / d).exists() for d in ["tests", "test", "spec", "__tests__"]
            ),
            "has_ci": (path / ".github" / "workflows").exists(),
        }
