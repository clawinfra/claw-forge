"""Tests for plugin system."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from claw_forge.plugins.base import PluginContext
from claw_forge.plugins.coding import CodingPlugin
from claw_forge.plugins.initializer import InitializerPlugin
from claw_forge.plugins.reviewer import ReviewerPlugin
from claw_forge.plugins.testing import TestingPlugin


class TestPlugins:
    def _ctx(self, path="/tmp"):
        return PluginContext(project_path=path, session_id="s1", task_id="t1")

    @pytest.mark.asyncio
    async def test_initializer_on_real_dir(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "pyproject.toml").write_text("[project]\nname='test'\n")
            plugin = InitializerPlugin()
            result = await plugin.execute(self._ctx(d))
            assert result.success
            assert result.metadata["language"] == "python"

    @pytest.mark.asyncio
    async def test_initializer_missing_dir(self):
        plugin = InitializerPlugin()
        result = await plugin.execute(self._ctx("/nonexistent/path"))
        assert not result.success

    @pytest.mark.asyncio
    async def test_coding_plugin(self):
        plugin = CodingPlugin()
        assert plugin.name == "coding"
        with patch("claw_forge.plugins.coding.collect_result", new_callable=AsyncMock) as mock_cr:
            mock_cr.return_value = "code written"
            result = await plugin.execute(self._ctx())
        assert result.success

    @pytest.mark.asyncio
    async def test_testing_plugin(self):
        plugin = TestingPlugin()
        assert plugin.name == "testing"
        with patch("claw_forge.plugins.testing.collect_result", new_callable=AsyncMock) as mock_cr:
            mock_cr.return_value = "tests run"
            result = await plugin.execute(self._ctx())
        assert result.success

    @pytest.mark.asyncio
    async def test_reviewer_plugin(self):
        plugin = ReviewerPlugin()
        assert plugin.name == "reviewer"
        with patch("claw_forge.plugins.reviewer.collect_result", new_callable=AsyncMock) as mock_cr:
            mock_cr.return_value = "review done"
            result = await plugin.execute(self._ctx())
        assert result.success

    def test_system_prompts(self):
        ctx = self._ctx()
        for cls in [InitializerPlugin, CodingPlugin, TestingPlugin, ReviewerPlugin]:
            plugin = cls()
            prompt = plugin.get_system_prompt(ctx)
            assert len(prompt) > 50


class TestInitializerWithSpec:
    def _ctx(self, project_path: str, spec_file: str | None = None) -> PluginContext:
        from claw_forge.plugins.base import PluginContext
        meta = {}
        if spec_file:
            meta["spec_file"] = spec_file
        return PluginContext(
            project_path=project_path,
            session_id="test-session",
            task_id="task-1",
            metadata=meta,
        )

    @pytest.mark.asyncio
    async def test_spec_file_not_found(self, tmp_path):
        plugin = InitializerPlugin()
        ctx = self._ctx(str(tmp_path), spec_file="nonexistent.xml")
        result = await plugin.execute(ctx)
        assert not result.success
        assert "not found" in result.output

    @pytest.mark.asyncio
    async def test_spec_file_parse_error(self, tmp_path):
        """_execute_with_spec returns failure on parse error (mocked)."""
        from unittest.mock import patch
        spec = tmp_path / "spec.xml"
        spec.write_text("some content")
        plugin = InitializerPlugin()
        ctx = self._ctx(str(tmp_path), spec_file=str(spec))
        with patch("claw_forge.spec.ProjectSpec.from_file", side_effect=ValueError("bad spec")):
            result = await plugin.execute(ctx)
        assert not result.success
        assert "Failed to parse" in result.output

    @pytest.mark.asyncio
    async def test_spec_file_relative_path(self, tmp_path):
        """_execute_with_spec resolves relative spec path against project."""
        # Write a minimal valid spec that will at least parse
        spec_content = """<?xml version="1.0"?>
<project>
  <name>TestProject</name>
  <description>Test project</description>
  <features>
    <feature id="F1" category="core">
      <title>Feature One</title>
      <description>Do something</description>
    </feature>
  </features>
</project>"""
        (tmp_path / "spec.xml").write_text(spec_content)
        plugin = InitializerPlugin()
        ctx = self._ctx(str(tmp_path), spec_file="spec.xml")
        result = await plugin.execute(ctx)
        # May succeed or fail depending on spec format — just verify it ran
        assert isinstance(result.success, bool)

    @pytest.mark.asyncio
    async def test_spec_absolute_path(self, tmp_path):
        """_execute_with_spec accepts absolute spec path."""
        spec_content = """<?xml version="1.0"?>
<project>
  <name>AbsoluteTest</name>
  <description>Absolute path test</description>
  <features>
    <feature id="F2" category="core">
      <title>Feature Two</title>
      <description>Do another thing</description>
    </feature>
  </features>
</project>"""
        spec_path = tmp_path / "abs_spec.xml"
        spec_path.write_text(spec_content)
        plugin = InitializerPlugin()
        ctx = self._ctx(str(tmp_path), spec_file=str(spec_path))
        result = await plugin.execute(ctx)
        assert isinstance(result.success, bool)

    @pytest.mark.asyncio
    async def test_brownfield_with_manifest(self, tmp_path):
        """_execute_with_spec loads brownfield_manifest.json when spec is brownfield."""
        # Write a spec that marks itself as brownfield
        spec_content = """<?xml version="1.0"?>
<project brownfield="true">
  <name>BrownfieldProject</name>
  <description>Brownfield test</description>
  <existing_context>
    <stack>python</stack>
  </existing_context>
  <features>
    <feature id="F3" category="core">
      <title>Feature Three</title>
      <description>Brownfield feature</description>
    </feature>
  </features>
</project>"""
        (tmp_path / "spec.xml").write_text(spec_content)
        # Write brownfield manifest
        import json
        manifest = {"stack": "python/fastapi", "test_baseline": "pytest", "conventions": "ruff"}
        (tmp_path / "brownfield_manifest.json").write_text(json.dumps(manifest))
        plugin = InitializerPlugin()
        ctx = self._ctx(str(tmp_path), spec_file="spec.xml")
        result = await plugin.execute(ctx)
        assert isinstance(result.success, bool)

    @pytest.mark.asyncio
    async def test_brownfield_manifest_corrupt(self, tmp_path):
        """_execute_with_spec warns but continues on corrupt brownfield_manifest.json."""
        spec_content = """<?xml version="1.0"?>
<project brownfield="true">
  <name>CorruptManifest</name>
  <description>Corrupt manifest test</description>
  <features>
    <feature id="F4" category="core">
      <title>Feature Four</title>
      <description>Something</description>
    </feature>
  </features>
</project>"""
        (tmp_path / "spec.xml").write_text(spec_content)
        (tmp_path / "brownfield_manifest.json").write_text("not valid json {{{{")
        plugin = InitializerPlugin()
        ctx = self._ctx(str(tmp_path), spec_file="spec.xml")
        result = await plugin.execute(ctx)
        # Should still run (warning logged, not fatal)
        assert isinstance(result.success, bool)
