"""Tests for plugin system."""

import pytest
import tempfile
from pathlib import Path

from claw_forge.plugins.base import PluginContext, PluginResult
from claw_forge.plugins.initializer import InitializerPlugin
from claw_forge.plugins.coding import CodingPlugin
from claw_forge.plugins.testing import TestingPlugin
from claw_forge.plugins.reviewer import ReviewerPlugin


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
        result = await plugin.execute(self._ctx())
        assert result.success

    @pytest.mark.asyncio
    async def test_testing_plugin(self):
        plugin = TestingPlugin()
        assert plugin.name == "testing"
        result = await plugin.execute(self._ctx())
        assert result.success

    @pytest.mark.asyncio
    async def test_reviewer_plugin(self):
        plugin = ReviewerPlugin()
        assert plugin.name == "reviewer"
        result = await plugin.execute(self._ctx())
        assert result.success

    def test_system_prompts(self):
        ctx = self._ctx()
        for cls in [InitializerPlugin, CodingPlugin, TestingPlugin, ReviewerPlugin]:
            plugin = cls()
            prompt = plugin.get_system_prompt(ctx)
            assert len(prompt) > 50
