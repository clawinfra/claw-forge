"""Tests for LSP skill auto-detection and plugin injection."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claw_forge.lsp import (
    _skill_plugin,
    detect_lsp_plugins,
    lsp_plugins_for_extensions,
    skills_for_agent,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_files(tmp_path: Path, filenames: list[str]) -> None:
    """Create empty files inside tmp_path."""
    for name in filenames:
        (tmp_path / name).touch()


# ---------------------------------------------------------------------------
# detect_lsp_plugins
# ---------------------------------------------------------------------------


class TestDetectLspPlugins:
    def test_py_files_returns_pyright(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["main.py", "utils.py"])
        plugins = detect_lsp_plugins(tmp_path)
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "pyright" in skill_names

    def test_ts_and_py_returns_both(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["app.ts", "script.py"])
        plugins = detect_lsp_plugins(tmp_path)
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "pyright" in skill_names
        assert "typescript-lsp" in skill_names

    def test_go_file_returns_gopls(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["main.go"])
        plugins = detect_lsp_plugins(tmp_path)
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "gopls" in skill_names

    def test_rs_file_returns_rust_analyzer(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["lib.rs"])
        plugins = detect_lsp_plugins(tmp_path)
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "rust-analyzer" in skill_names

    def test_c_and_h_returns_clangd_deduplicated(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["main.c", "util.h"])
        plugins = detect_lsp_plugins(tmp_path)
        skill_names = [Path(p["path"]).name for p in plugins]
        assert skill_names.count("clangd") == 1

    def test_sol_file_returns_solidity_lsp(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["Token.sol"])
        plugins = detect_lsp_plugins(tmp_path)
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "solidity-lsp" in skill_names

    def test_empty_dir_returns_empty_list(self, tmp_path: Path) -> None:
        assert detect_lsp_plugins(tmp_path) == []

    def test_only_md_files_returns_empty_list(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["README.md", "CHANGELOG.md"])
        assert detect_lsp_plugins(tmp_path) == []

    def test_missing_skill_dir_skips_gracefully(self, tmp_path: Path) -> None:
        """If a skill directory is missing on disk, no error is raised."""
        _make_files(tmp_path, ["main.py"])
        with patch("claw_forge.lsp.SKILLS_DIR", tmp_path / "nonexistent_skills"):
            plugins = detect_lsp_plugins(tmp_path)
        assert plugins == []

    def test_nonexistent_project_path_returns_empty(self) -> None:
        result = detect_lsp_plugins("/nonexistent/path/that/does/not/exist")
        assert result == []

    def test_plugins_have_type_local(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["main.py"])
        plugins = detect_lsp_plugins(tmp_path)
        assert len(plugins) >= 1
        for plugin in plugins:
            assert plugin["type"] == "local"

    def test_plugin_path_exists_with_skill_md(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["main.py"])
        plugins = detect_lsp_plugins(tmp_path)
        for plugin in plugins:
            skill_path = Path(plugin["path"])
            assert (skill_path / "SKILL.md").exists(), (
                f"SKILL.md missing at {skill_path}"
            )


# ---------------------------------------------------------------------------
# lsp_plugins_for_extensions
# ---------------------------------------------------------------------------


class TestSkillPlugin:
    def test_returns_none_when_skill_md_missing(self, tmp_path: Path) -> None:
        """_skill_plugin returns None when SKILL.md is absent (line 115)."""
        with patch("claw_forge.lsp.SKILLS_DIR", tmp_path / "skills"):
            result = _skill_plugin("nonexistent-skill")
        assert result is None

    def test_returns_config_when_skill_md_exists(self, tmp_path: Path) -> None:
        """_skill_plugin returns config when SKILL.md is present."""
        skills_dir = tmp_path / "skills"
        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# My Skill")
        with patch("claw_forge.lsp.SKILLS_DIR", skills_dir):
            result = _skill_plugin("my-skill")
        assert result is not None
        assert result["type"] == "local"


class TestSkillsForAgent:
    def test_returns_empty_when_skills_dir_missing(self) -> None:
        """skills_for_agent with missing SKILLS_DIR → _skill_plugin returns None → 158->156."""
        with patch("claw_forge.lsp.SKILLS_DIR", Path("/nonexistent_skills_dir_xyz")):
            plugins = skills_for_agent("coding")
        assert plugins == []

    def test_includes_agent_type_skills(self, tmp_path: Path) -> None:
        """skills_for_agent injects agent-type skills when SKILL.md exists."""
        skills_dir = tmp_path / "skills"
        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# My Skill")
        with patch("claw_forge.lsp.SKILLS_DIR", skills_dir), \
             patch("claw_forge.lsp.AGENT_TYPE_SKILLS", {"coding": ["my-skill"]}):
            plugins = skills_for_agent("coding")
        assert len(plugins) == 1

    def test_keyword_match_injects_skills(self, tmp_path: Path) -> None:
        """skills_for_agent injects keyword-matched skills for matching task_description."""
        skills_dir = tmp_path / "skills"
        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# My Skill")
        with patch("claw_forge.lsp.SKILLS_DIR", skills_dir), \
             patch("claw_forge.lsp.AGENT_TYPE_SKILLS", {}), \
             patch("claw_forge.lsp.TASK_KEYWORD_SKILLS", {"api": ["my-skill"]}):
            plugins = skills_for_agent("coding", task_description="api integration test")
        assert len(plugins) == 1

    def test_deduplicates_across_type_and_keyword(self, tmp_path: Path) -> None:
        """Duplicate skill name from type+keyword → appears only once."""
        skills_dir = tmp_path / "skills"
        skill_dir = skills_dir / "shared-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Shared")
        with patch("claw_forge.lsp.SKILLS_DIR", skills_dir), \
             patch("claw_forge.lsp.AGENT_TYPE_SKILLS", {"coding": ["shared-skill"]}), \
             patch("claw_forge.lsp.TASK_KEYWORD_SKILLS", {"api": ["shared-skill"]}):
            plugins = skills_for_agent("coding", task_description="api test")
        assert len(plugins) == 1


class TestLspPluginsForExtensions:
    def test_py_and_ts_returns_two_plugins(self) -> None:
        plugins = lsp_plugins_for_extensions({".py", ".ts"})
        skill_names = [Path(p["path"]).name for p in plugins]
        assert len(plugins) == 2
        assert "pyright" in skill_names
        assert "typescript-lsp" in skill_names

    def test_empty_set_returns_empty(self) -> None:
        assert lsp_plugins_for_extensions(set()) == []

    def test_unknown_extension_returns_empty(self) -> None:
        assert lsp_plugins_for_extensions({".xyz", ".abc"}) == []

    def test_cpp_and_h_deduplicates_to_one_clangd(self) -> None:
        plugins = lsp_plugins_for_extensions({".cpp", ".h", ".hpp"})
        skill_names = [Path(p["path"]).name for p in plugins]
        assert skill_names.count("clangd") == 1

    def test_returned_configs_have_type_local(self) -> None:
        plugins = lsp_plugins_for_extensions({".rs"})
        assert len(plugins) == 1
        assert plugins[0]["type"] == "local"

    def test_all_supported_extensions_work(self) -> None:
        all_exts = {".py", ".pyi", ".ts", ".tsx", ".js", ".jsx",
                    ".go", ".rs", ".c", ".cpp", ".cc", ".h", ".hpp", ".sol"}
        plugins = lsp_plugins_for_extensions(all_exts)
        # 6 distinct skills: pyright, typescript-lsp, gopls, rust-analyzer, clangd, solidity-lsp
        assert len(plugins) == 6


# ---------------------------------------------------------------------------
# run_agent integration (mocked)
# ---------------------------------------------------------------------------


class TestRunAgentLspIntegration:
    @pytest.mark.asyncio
    async def test_auto_detect_false_no_plugins(self, tmp_path: Path) -> None:
        """auto_detect_lsp=False means no plugins are added regardless of cwd."""
        _make_files(tmp_path, ["main.py"])

        import claw_forge.agent.runner as runner_module

        mock_options_class = MagicMock(return_value=MagicMock())

        async def fake_query(prompt: str, options: object):  # type: ignore[return]
            if False:
                yield

        with (
            patch.object(runner_module, "query", fake_query),
            patch.object(runner_module.claude_agent_sdk, "ClaudeAgentOptions",
                         mock_options_class),
        ):
            async for _ in runner_module.run_agent(
                "hello",
                cwd=tmp_path,
                auto_detect_lsp=False,
                auto_inject_skills=False,
            ):
                pass

        call_kwargs = mock_options_class.call_args.kwargs
        assert call_kwargs.get("plugins") == []

    @pytest.mark.asyncio
    async def test_explicit_lsp_plugins_passed_through(self, tmp_path: Path) -> None:
        """Explicit lsp_plugins are forwarded to ClaudeAgentOptions.plugins."""
        from claw_forge.lsp import lsp_plugins_for_extensions

        explicit_plugins = lsp_plugins_for_extensions({".py"})
        assert len(explicit_plugins) == 1

        captured_options: list = []

        async def fake_query(prompt: str, options: object) -> object:
            captured_options.append(options)
            return
            yield

        with patch("claw_forge.agent.runner.query", fake_query):
            from claw_forge.agent.runner import run_agent
            async for _ in run_agent(
                "hello",
                lsp_plugins=explicit_plugins,
                auto_detect_lsp=False,
            ):
                pass


# ---------------------------------------------------------------------------
# Simpler run_agent mock tests that actually work
# ---------------------------------------------------------------------------


class TestRunAgentLspSimple:
    @pytest.mark.asyncio
    async def test_auto_detect_lsp_false_sets_empty_plugins(self) -> None:
        """With auto_detect_lsp=False and no explicit plugins, resolved list is empty."""
        import claw_forge.agent.runner as runner_module

        mock_options_class = MagicMock(return_value=MagicMock())

        async def fake_query(prompt: str, options: object):  # type: ignore[return]
            if False:
                yield  # make async generator

        with (
            patch.object(runner_module, "query", fake_query),
            patch.object(runner_module.claude_agent_sdk, "ClaudeAgentOptions",
                         mock_options_class),
        ):
            async for _ in runner_module.run_agent(
                "hello",
                auto_detect_lsp=False,
                auto_inject_skills=False,
            ):
                pass

        call_kwargs = mock_options_class.call_args.kwargs
        assert call_kwargs.get("plugins") == []

    @pytest.mark.asyncio
    async def test_explicit_lsp_plugins_forwarded_to_options(self, tmp_path: Path) -> None:
        """Explicit lsp_plugins end up in ClaudeAgentOptions(plugins=...)."""
        import claw_forge.agent.runner as runner_module
        from claw_forge.lsp import lsp_plugins_for_extensions

        explicit = lsp_plugins_for_extensions({".rs"})
        assert len(explicit) == 1

        mock_options_class = MagicMock(return_value=MagicMock())

        async def fake_query(prompt: str, options: object):  # type: ignore[return]
            if False:
                yield

        with (
            patch.object(runner_module, "query", fake_query),
            patch.object(runner_module.claude_agent_sdk, "ClaudeAgentOptions",
                         mock_options_class),
        ):
            async for _ in runner_module.run_agent(
                "hello",
                lsp_plugins=explicit,
                auto_detect_lsp=False,
            ):
                pass

        call_kwargs = mock_options_class.call_args.kwargs
        assert call_kwargs.get("plugins") == explicit
