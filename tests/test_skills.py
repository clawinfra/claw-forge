"""Tests for context-based (non-LSP) skill injection."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claw_forge.lsp import skills_for_agent

# ---------------------------------------------------------------------------
# skills_for_agent — agent type matching
# ---------------------------------------------------------------------------


class TestSkillsForAgentByType:
    def test_coding_returns_systematic_debug(self) -> None:
        plugins = skills_for_agent("coding", "")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "systematic-debug" in skill_names

    def test_coding_returns_verification_gate(self) -> None:
        plugins = skills_for_agent("coding", "")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "verification-gate" in skill_names

    def test_coding_returns_test_driven(self) -> None:
        plugins = skills_for_agent("coding", "")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "test-driven" in skill_names

    def test_reviewing_returns_code_review(self) -> None:
        plugins = skills_for_agent("reviewing", "")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "code-review" in skill_names

    def test_reviewing_returns_security_audit(self) -> None:
        plugins = skills_for_agent("reviewing", "")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "security-audit" in skill_names

    def test_testing_returns_test_driven(self) -> None:
        plugins = skills_for_agent("testing", "")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "test-driven" in skill_names

    def test_testing_returns_verification_gate(self) -> None:
        plugins = skills_for_agent("testing", "")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "verification-gate" in skill_names

    def test_initializer_returns_git_workflow(self) -> None:
        plugins = skills_for_agent("initializer", "")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "git-workflow" in skill_names

    def test_unknown_agent_type_returns_empty(self) -> None:
        plugins = skills_for_agent("unknown_type_xyz", "")
        assert plugins == []

    def test_empty_string_agent_type_returns_empty(self) -> None:
        plugins = skills_for_agent("", "")
        assert plugins == []


# ---------------------------------------------------------------------------
# skills_for_agent — keyword matching
# ---------------------------------------------------------------------------


class TestSkillsForAgentByKeyword:
    def test_keyword_docker_returns_docker_skill(self) -> None:
        plugins = skills_for_agent("", "deploy this docker container")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "docker" in skill_names

    def test_keyword_api_returns_api_client(self) -> None:
        plugins = skills_for_agent("", "call the REST api endpoint")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "api-client" in skill_names

    def test_keyword_http_returns_api_client(self) -> None:
        plugins = skills_for_agent("", "make an http request")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "api-client" in skill_names

    def test_keyword_database_returns_database(self) -> None:
        plugins = skills_for_agent("", "update the database schema")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "database" in skill_names

    def test_keyword_sql_returns_database(self) -> None:
        plugins = skills_for_agent("", "optimize this sql query")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "database" in skill_names

    def test_keyword_performance_returns_performance(self) -> None:
        plugins = skills_for_agent("", "the performance is poor")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "performance" in skill_names

    def test_keyword_slow_returns_performance(self) -> None:
        plugins = skills_for_agent("", "fix the slow query")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "performance" in skill_names

    def test_keyword_security_returns_security_audit(self) -> None:
        plugins = skills_for_agent("", "run a security check")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "security-audit" in skill_names

    def test_keyword_git_returns_git_workflow(self) -> None:
        plugins = skills_for_agent("", "create a git branch")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "git-workflow" in skill_names

    def test_keyword_research_returns_web_research(self) -> None:
        plugins = skills_for_agent("", "research how asyncio works")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "web-research" in skill_names

    def test_keyword_parallel_returns_parallel_dispatch(self) -> None:
        plugins = skills_for_agent("", "run these tasks in parallel")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "parallel-dispatch" in skill_names


# ---------------------------------------------------------------------------
# skills_for_agent — combined + deduplication
# ---------------------------------------------------------------------------


class TestSkillsForAgentDedup:
    def test_testing_with_slow_keyword_has_test_driven_and_performance(self) -> None:
        plugins = skills_for_agent("testing", "fix slow query")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "test-driven" in skill_names
        assert "performance" in skill_names

    def test_no_duplicate_skills_from_agent_type_and_keyword(self) -> None:
        # "coding" type includes "systematic-debug"; keyword "git" adds "git-workflow"
        # No duplicates should appear
        plugins = skills_for_agent("coding", "commit to git")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert len(skill_names) == len(set(skill_names))

    def test_security_keyword_with_reviewing_type_deduplicates_security_audit(self) -> None:
        # "reviewing" includes security-audit; "security" keyword also maps to security-audit
        plugins = skills_for_agent("reviewing", "security audit the code")
        skill_names = [Path(p["path"]).name for p in plugins]
        assert skill_names.count("security-audit") == 1

    def test_all_returned_plugins_have_type_local(self) -> None:
        plugins = skills_for_agent("coding", "deploy docker container")
        for plugin in plugins:
            assert plugin["type"] == "local"

    def test_all_returned_paths_exist_on_filesystem(self) -> None:
        plugins = skills_for_agent("coding", "")
        for plugin in plugins:
            skill_path = Path(plugin["path"])
            assert (skill_path / "SKILL.md").exists(), (
                f"SKILL.md missing at {skill_path}"
            )

    def test_keyword_matching_is_case_insensitive(self) -> None:
        plugins_lower = skills_for_agent("", "docker")
        plugins_upper = skills_for_agent("", "DOCKER")
        assert [p["path"] for p in plugins_lower] == [p["path"] for p in plugins_upper]


# ---------------------------------------------------------------------------
# runner.py auto_inject_skills integration
# ---------------------------------------------------------------------------


class TestRunnerAutoInjectSkills:
    @pytest.mark.asyncio
    async def test_auto_inject_skills_false_skips_skill_injection(self) -> None:
        """auto_inject_skills=False: no skill plugins are injected."""
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
                auto_detect_lsp=False,
                auto_inject_skills=False,
            ):
                pass

        call_kwargs = mock_options_class.call_args.kwargs
        assert call_kwargs.get("plugins") == []

    @pytest.mark.asyncio
    async def test_auto_inject_skills_true_injects_coding_skills(self) -> None:
        """auto_inject_skills=True with agent_type='coding' injects skill plugins."""
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
                "implement the feature",
                auto_detect_lsp=False,
                auto_inject_skills=True,
                agent_type="coding",
            ):
                pass

        call_kwargs = mock_options_class.call_args.kwargs
        plugins = call_kwargs.get("plugins", [])
        skill_names = [Path(p["path"]).name for p in plugins]
        assert "systematic-debug" in skill_names
        assert "verification-gate" in skill_names
        assert "test-driven" in skill_names

    @pytest.mark.asyncio
    async def test_auto_inject_skills_deduplicates_with_lsp_plugins(
        self, tmp_path: Path
    ) -> None:
        """No duplicate plugin paths when lsp + skill plugins are merged."""
        import claw_forge.agent.runner as runner_module
        from claw_forge.lsp import lsp_plugins_for_extensions

        explicit = lsp_plugins_for_extensions({".py"})
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
                "implement the feature",
                lsp_plugins=explicit,
                auto_detect_lsp=False,
                auto_inject_skills=True,
                agent_type="coding",
            ):
                pass

        call_kwargs = mock_options_class.call_args.kwargs
        plugins = call_kwargs.get("plugins", [])
        paths = [p["path"] for p in plugins]
        assert len(paths) == len(set(paths)), "Duplicate plugin paths found"
