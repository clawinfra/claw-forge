"""End-to-end tests for the React Kanban UI.

Tests:
  - ui/package.json exists with required dependencies
  - Key component source files exist
  - npm install + npm run build succeed (dist/ created)
  - TypeScript compiler reports no errors
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

UI_DIR = Path("/tmp/claw-forge/ui")
SRC_DIR = UI_DIR / "src"


# ---------------------------------------------------------------------------
# Skip helper
# ---------------------------------------------------------------------------

def _require_npm() -> None:
    """Skip the test if npm is not found on PATH."""
    if not shutil.which("npm"):
        pytest.skip("npm not available on PATH")


def _require_node() -> None:
    """Skip the test if node is not found on PATH."""
    if not shutil.which("node"):
        pytest.skip("node not available on PATH")


# ---------------------------------------------------------------------------
# Package.json structure
# ---------------------------------------------------------------------------


class TestPackageJson:
    def test_package_json_exists(self) -> None:
        """ui/package.json must exist."""
        assert (UI_DIR / "package.json").exists(), "ui/package.json not found"

    def test_package_json_valid_json(self) -> None:
        """ui/package.json must be valid JSON."""
        content = (UI_DIR / "package.json").read_text()
        pkg = json.loads(content)
        assert isinstance(pkg, dict)

    def test_package_json_has_name(self) -> None:
        """package.json must have a 'name' field."""
        pkg = json.loads((UI_DIR / "package.json").read_text())
        assert "name" in pkg
        assert pkg["name"]  # non-empty

    def test_package_json_has_scripts(self) -> None:
        """package.json must have dev/build scripts."""
        pkg = json.loads((UI_DIR / "package.json").read_text())
        scripts = pkg.get("scripts", {})
        assert "build" in scripts, "Missing 'build' script in package.json"
        assert "dev" in scripts, "Missing 'dev' script in package.json"

    def test_package_json_has_react_dep(self) -> None:
        """package.json must declare react as a dependency."""
        pkg = json.loads((UI_DIR / "package.json").read_text())
        deps = pkg.get("dependencies", {})
        assert "react" in deps, "react not in dependencies"
        assert "react-dom" in deps, "react-dom not in dependencies"

    def test_package_json_has_dev_deps(self) -> None:
        """package.json must declare TypeScript, Vite, and React types."""
        pkg = json.loads((UI_DIR / "package.json").read_text())
        dev_deps = pkg.get("devDependencies", {})
        assert "typescript" in dev_deps, "typescript not in devDependencies"
        assert "vite" in dev_deps, "vite not in devDependencies"

    def test_package_json_has_tanstack_query(self) -> None:
        """@tanstack/react-query should be a dependency."""
        pkg = json.loads((UI_DIR / "package.json").read_text())
        deps = pkg.get("dependencies", {})
        assert "@tanstack/react-query" in deps, "@tanstack/react-query missing"

    def test_package_json_has_lucide(self) -> None:
        """lucide-react should be listed as a dependency."""
        pkg = json.loads((UI_DIR / "package.json").read_text())
        deps = pkg.get("dependencies", {})
        assert "lucide-react" in deps, "lucide-react missing"


# ---------------------------------------------------------------------------
# Source file presence
# ---------------------------------------------------------------------------


class TestSourceFilePresence:
    def test_src_dir_exists(self) -> None:
        assert SRC_DIR.exists(), "ui/src/ directory not found"

    def test_app_tsx_exists(self) -> None:
        assert (SRC_DIR / "App.tsx").exists(), "App.tsx not found"

    def test_main_tsx_exists(self) -> None:
        assert (SRC_DIR / "main.tsx").exists(), "main.tsx not found"

    def test_types_ts_exists(self) -> None:
        assert (SRC_DIR / "types.ts").exists(), "types.ts not found"

    def test_api_ts_exists(self) -> None:
        assert (SRC_DIR / "api.ts").exists(), "api.ts not found"

    def test_feature_card_component_exists(self) -> None:
        assert (SRC_DIR / "components" / "FeatureCard.tsx").exists(), (
            "FeatureCard.tsx not found"
        )

    def test_connection_indicator_component_exists(self) -> None:
        assert (SRC_DIR / "components" / "ConnectionIndicator.tsx").exists(), (
            "ConnectionIndicator.tsx not found"
        )

    def test_activity_log_panel_exists(self) -> None:
        assert (SRC_DIR / "components" / "ActivityLogPanel.tsx").exists(), (
            "ActivityLogPanel.tsx not found"
        )

    def test_provider_pool_status_exists(self) -> None:
        assert (SRC_DIR / "components" / "ProviderPoolStatus.tsx").exists(), (
            "ProviderPoolStatus.tsx not found"
        )

    def test_index_css_exists(self) -> None:
        assert (SRC_DIR / "index.css").exists(), "index.css not found"

    def test_hooks_dir_has_websocket(self) -> None:
        assert (SRC_DIR / "hooks" / "useWebSocket.ts").exists(), (
            "useWebSocket.ts not found"
        )

    def test_hooks_dir_has_features(self) -> None:
        assert (SRC_DIR / "hooks" / "useFeatures.ts").exists(), (
            "useFeatures.ts not found"
        )

    def test_index_html_exists(self) -> None:
        assert (UI_DIR / "index.html").exists(), "ui/index.html not found"

    def test_tsconfig_exists(self) -> None:
        assert (UI_DIR / "tsconfig.json").exists(), "ui/tsconfig.json not found"

    def test_vite_config_exists(self) -> None:
        assert (UI_DIR / "vite.config.ts").exists(), "ui/vite.config.ts not found"

    def test_tailwind_config_exists(self) -> None:
        assert (UI_DIR / "tailwind.config.js").exists(), (
            "ui/tailwind.config.js not found"
        )


# ---------------------------------------------------------------------------
# Source file content smoke checks
# ---------------------------------------------------------------------------


class TestSourceContent:
    def test_app_tsx_imports_react(self) -> None:
        """App.tsx must import from react."""
        content = (SRC_DIR / "App.tsx").read_text()
        assert "react" in content.lower() or "React" in content

    def test_feature_card_tsx_exports_component(self) -> None:
        """FeatureCard.tsx must have an export."""
        content = (SRC_DIR / "components" / "FeatureCard.tsx").read_text()
        assert "export" in content

    def test_connection_indicator_tsx_exports_component(self) -> None:
        """ConnectionIndicator.tsx must have an export."""
        content = (SRC_DIR / "components" / "ConnectionIndicator.tsx").read_text()
        assert "export" in content

    def test_types_ts_defines_feature_type(self) -> None:
        """types.ts should define a Feature or feature-related type."""
        content = (SRC_DIR / "types.ts").read_text()
        # Either 'Feature' or 'feature' likely appears
        assert "feature" in content.lower() or "Feature" in content

    def test_api_ts_has_base_url(self) -> None:
        """api.ts should reference an API base URL or port."""
        content = (SRC_DIR / "api.ts").read_text()
        # Should mention localhost, VITE_, port, or similar
        assert any(
            term in content
            for term in ["localhost", "VITE_", "8888", "8420", "fetch", "httpx", "axios"]
        ), "api.ts doesn't seem to reference an API URL"


# ---------------------------------------------------------------------------
# npm install + build (integration)
# ---------------------------------------------------------------------------


class TestNpmBuild:
    def test_npm_install_succeeds(self) -> None:
        """npm install in ui/ must exit 0."""
        _require_npm()
        result = subprocess.run(
            ["npm", "install", "--prefer-offline"],
            cwd=UI_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"npm install failed (exit {result.returncode}):\n{result.stderr[-2000:]}"
        )
        assert (UI_DIR / "node_modules").exists(), "node_modules not created after npm install"

    def test_npm_build_creates_dist(self) -> None:
        """npm run build must exit 0 and create ui/dist/."""
        _require_npm()
        _require_node()

        # Ensure deps are installed first
        if not (UI_DIR / "node_modules").exists():
            subprocess.run(
                ["npm", "install", "--prefer-offline"],
                cwd=UI_DIR,
                capture_output=True,
                timeout=120,
            )

        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=UI_DIR,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert result.returncode == 0, (
            f"npm run build failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout[-3000:]}\nstderr: {result.stderr[-2000:]}"
        )
        dist_dir = UI_DIR / "dist"
        assert dist_dir.exists(), "dist/ directory not created by build"
        assert any(dist_dir.iterdir()), "dist/ directory is empty after build"

    def test_dist_contains_index_html(self) -> None:
        """Build output dist/ must contain index.html."""
        _require_npm()
        dist_html = UI_DIR / "dist" / "index.html"
        if not dist_html.exists():
            pytest.skip("dist/ not built yet — run test_npm_build_creates_dist first")
        assert dist_html.exists()


# ---------------------------------------------------------------------------
# TypeScript checks
# ---------------------------------------------------------------------------


class TestTypeScript:
    def test_tsc_no_emit_succeeds(self) -> None:
        """tsc --noEmit must exit 0 (no TypeScript errors)."""
        _require_node()
        if not (UI_DIR / "node_modules").exists():
            pytest.skip("node_modules not installed — run npm install first")

        # Find tsc in node_modules/.bin
        tsc = UI_DIR / "node_modules" / ".bin" / "tsc"
        if not tsc.exists():
            pytest.skip("tsc not found in node_modules/.bin")

        result = subprocess.run(
            [str(tsc), "--noEmit"],
            cwd=UI_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"TypeScript errors found:\n{result.stdout}\n{result.stderr}"
        )
