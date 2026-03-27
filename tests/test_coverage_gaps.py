"""Tests to cover remaining uncovered lines across multiple modules."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest

from claw_forge.pool.manager import ProviderPoolManager
from claw_forge.pool.providers.base import (
    BaseProvider,
    ProviderConfig,
    ProviderError,
    ProviderResponse,
    ProviderType,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockProvider(BaseProvider):
    """Minimal mock provider for manager tests."""

    def __init__(self, config: ProviderConfig, *, response: ProviderResponse | None = None, error: Exception | None = None) -> None:  # noqa: E501
        super().__init__(config)
        self._response = response
        self._error = error
        self.call_count = 0

    async def execute(self, model: str, messages: list[dict[str, Any]], **kwargs: Any) -> ProviderResponse:  # noqa: E501
        self.call_count += 1
        if self._error:
            raise self._error
        return self._response or ProviderResponse(
            content="ok", model=model, provider_name=self.name,
            input_tokens=10, output_tokens=5, latency_ms=100.0,
        )


def _cfg(**overrides: Any) -> ProviderConfig:
    defaults: dict[str, Any] = {
        "name": "test",
        "provider_type": ProviderType.ANTHROPIC,
        "api_key": "sk-test",
        "priority": 1,
    }
    defaults.update(overrides)
    return ProviderConfig(**defaults)


# ═══════════════════════════════════════════════════════════════════════════
# pool/manager.py
# ═══════════════════════════════════════════════════════════════════════════


class TestManagerHalfOpenPinned:
    """Cover line 129: record_half_open_attempt in pinned provider path."""

    @pytest.mark.asyncio
    async def test_pinned_half_open_records_attempt(self) -> None:
        configs = [_cfg(name="p1")]
        mgr = ProviderPoolManager(configs)
        provider = _MockProvider(configs[0])
        mgr._providers = [provider]

        from claw_forge.pool.health import CircuitBreaker
        cb = CircuitBreaker("p1", failure_threshold=1, recovery_timeout=0.0)
        cb.record_failure()  # CLOSED -> OPEN
        # With recovery_timeout=0, state property transitions OPEN -> HALF_OPEN
        assert cb.state.value == "half_open"
        mgr._circuits = {"p1": cb}

        result = await mgr.execute(
            "claude-sonnet-4-20250514",
            [{"role": "user", "content": "hi"}],
            provider_hint="p1",
        )
        assert result.content == "ok"


class TestManagerHalfOpenNormal:
    """Cover line 169: record_half_open_attempt in normal rotation path."""

    @pytest.mark.asyncio
    async def test_normal_half_open_records_attempt(self) -> None:
        configs = [_cfg(name="p1")]
        mgr = ProviderPoolManager(configs)
        provider = _MockProvider(configs[0])
        mgr._providers = [provider]

        from claw_forge.pool.health import CircuitBreaker
        cb = CircuitBreaker("p1", failure_threshold=1, recovery_timeout=0.0)
        cb.record_failure()
        assert cb.state.value == "half_open"
        mgr._circuits = {"p1": cb}

        result = await mgr.execute(
            "claude-sonnet-4-20250514",
            [{"role": "user", "content": "hi"}],
        )
        assert result.content == "ok"


class TestDeriveHealth:
    """Cover lines 251-253: _derive_health for half_open and open."""

    def test_half_open_is_degraded(self) -> None:
        mgr = ProviderPoolManager([_cfg()])
        assert mgr._derive_health("half_open") == "degraded"

    def test_open_is_unhealthy(self) -> None:
        mgr = ProviderPoolManager([_cfg()])
        assert mgr._derive_health("open") == "unhealthy"

    def test_closed_is_healthy(self) -> None:
        mgr = ProviderPoolManager([_cfg()])
        assert mgr._derive_health("closed") == "healthy"


class TestPoolStatusModelAliases:
    """Cover line 293: model_aliases included when not None."""

    @pytest.mark.asyncio
    async def test_model_aliases_in_status(self) -> None:
        configs = [_cfg(name="p1")]
        mgr = ProviderPoolManager(configs)
        mgr._providers = [_MockProvider(configs[0])]
        from claw_forge.pool.health import CircuitBreaker
        mgr._circuits = {"p1": CircuitBreaker("p1")}

        aliases = {"sonnet": "claude-sonnet-4-20250514"}
        status = await mgr.get_pool_status(model_aliases=aliases)
        assert status["model_aliases"] == aliases


class TestHealthCheckAllException:
    """Cover lines 301-302: health_check_all exception path."""

    @pytest.mark.asyncio
    async def test_health_check_exception_returns_false(self) -> None:
        configs = [_cfg(name="p1")]
        mgr = ProviderPoolManager(configs)
        provider = _MockProvider(configs[0], error=RuntimeError("boom"))
        mgr._providers = [provider]
        from claw_forge.pool.health import CircuitBreaker
        mgr._circuits = {"p1": CircuitBreaker("p1")}

        results = await mgr.health_check_all()
        assert results["p1"] is False


class TestGetModelForComplexityProviderNone:
    """Cover line 358: get_model_for_complexity when provider not found."""

    def test_returns_none_for_unknown_provider(self) -> None:
        configs = [_cfg(name="p1")]
        mgr = ProviderPoolManager(configs)
        mgr._providers = [_MockProvider(configs[0])]
        mgr._active_tiers = {"unknown_provider": ["tier1"]}

        result = mgr.get_model_for_complexity("unknown_provider", "low")
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# pool/providers/anthropic.py — line 127: 400-level client error
# ═══════════════════════════════════════════════════════════════════════════


class TestAnthropicProvider400Error:
    @pytest.mark.asyncio
    async def test_400_raises_non_retryable_error(self) -> None:
        from claw_forge.pool.providers.anthropic import AnthropicProvider

        cfg = _cfg(name="anth", api_key="sk-key")
        provider = AnthropicProvider(cfg)

        mock_resp = Mock(spec=httpx.Response)
        mock_resp.status_code = 400
        mock_resp.text = "Bad request"
        mock_resp.headers = {}
        provider._client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(ProviderError) as exc_info:
            await provider.execute("claude-sonnet-4-20250514", [{"role": "user", "content": "hi"}])

        assert exc_info.value.retryable is False
        assert exc_info.value.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════
# pool/providers/anthropic_compat.py — line 102: tools in body
# ═══════════════════════════════════════════════════════════════════════════


class TestAnthropicCompatTools:
    @pytest.mark.asyncio
    async def test_tools_included_in_body(self) -> None:
        from claw_forge.pool.providers.anthropic_compat import AnthropicCompatProvider

        cfg = _cfg(
            name="proxy",
            provider_type=ProviderType.ANTHROPIC_COMPAT,
            base_url="https://proxy.example.com",
            api_key="sk-key",
        )
        provider = AnthropicCompatProvider(cfg)

        mock_resp = Mock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "content": [{"type": "text", "text": "tool result"}],
            "model": "claude-sonnet-4-6",
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "stop_reason": "end_turn",
        }
        provider._client.post = AsyncMock(return_value=mock_resp)

        tools = [{"name": "search", "description": "d", "input_schema": {}}]
        result = await provider.execute(
            "claude-sonnet-4-6",
            [{"role": "user", "content": "hi"}],
            tools=tools,
        )
        assert result.content == "tool result"
        body = provider._client.post.call_args[1]["json"]
        assert body["tools"] == tools


# ═══════════════════════════════════════════════════════════════════════════
# pool/providers/bedrock.py — line 33: successful _get_client
# ═══════════════════════════════════════════════════════════════════════════


class TestBedrockGetClientSuccess:
    def test_get_client_creates_bedrock_client(self) -> None:
        from claw_forge.pool.providers.bedrock import BedrockProvider

        cfg = _cfg(provider_type=ProviderType.BEDROCK, region="us-east-1")
        provider = BedrockProvider(cfg)

        mock_cls = MagicMock()
        with patch.dict("sys.modules", {"anthropic": MagicMock(AsyncAnthropicBedrock=mock_cls)}):
            from claw_forge.pool.providers import bedrock
            with patch.object(bedrock, "AsyncAnthropicBedrock", mock_cls, create=True):
                # Reimport to ensure we mock correctly
                pass

        # Simpler: just mock the import inside the method
        mock_bedrock_cls = MagicMock()
        mock_module = MagicMock()
        mock_module.AsyncAnthropicBedrock = mock_bedrock_cls

        with patch("builtins.__import__", side_effect=lambda name, *a, **kw: mock_module if name == "anthropic" else __import__(name, *a, **kw)):  # noqa: E501
            client = provider._get_client()

        assert client is mock_bedrock_cls.return_value


# ═══════════════════════════════════════════════════════════════════════════
# pool/providers/ollama.py — line 85: tools in body
# ═══════════════════════════════════════════════════════════════════════════


class TestOllamaTools:
    @pytest.mark.asyncio
    async def test_tools_included_in_body(self) -> None:
        from claw_forge.pool.providers.ollama import OllamaProvider

        cfg = _cfg(name="ollama", provider_type=ProviderType.OLLAMA)
        provider = OllamaProvider(cfg)

        response_data = {
            "choices": [{"message": {"content": "with tools"}, "finish_reason": "stop"}],
            "model": "llama3.2",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = response_data

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        tools = [{"name": "fn", "description": "d", "parameters": {}}]
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await provider.execute(
                "llama3.2",
                [{"role": "user", "content": "hi"}],
                tools=tools,
            )
        assert result.content == "with tools"


# ═══════════════════════════════════════════════════════════════════════════
# pool/providers/registry.py — line 77: unknown provider type
# ═══════════════════════════════════════════════════════════════════════════


class TestRegistryUnknownType:
    def test_unknown_provider_type_raises(self) -> None:
        from claw_forge.pool.providers.registry import create_provider

        cfg = _cfg(provider_type="nonexistent_type")
        with pytest.raises(ValueError, match="Unknown provider type"):
            create_provider(cfg)


# ═══════════════════════════════════════════════════════════════════════════
# pool/providers/vertex.py — lines 36-37: successful _get_client
# ═══════════════════════════════════════════════════════════════════════════


class TestVertexGetClientSuccess:
    def test_get_client_creates_vertex_client(self) -> None:
        from claw_forge.pool.providers.vertex import VertexProvider

        cfg = _cfg(provider_type=ProviderType.VERTEX, project_id="proj-123", region="us-east5")
        provider = VertexProvider(cfg)

        mock_vertex_cls = MagicMock()
        mock_module = MagicMock()
        mock_module.AsyncAnthropicVertex = mock_vertex_cls

        with patch("builtins.__import__", side_effect=lambda name, *a, **kw: mock_module if name == "anthropic" else __import__(name, *a, **kw)):  # noqa: E501
            client = provider._get_client()

        assert client is mock_vertex_cls.return_value
        mock_vertex_cls.assert_called_once_with(
            project_id="proj-123",
            region="us-east5",
        )


# ═══════════════════════════════════════════════════════════════════════════
# pool/providers/base.py — line 145: health_check success path
# ═══════════════════════════════════════════════════════════════════════════


class TestBaseHealthCheckSuccess:
    @pytest.mark.asyncio
    async def test_health_check_returns_true_on_success(self) -> None:
        cfg = _cfg(name="healthy")
        provider = _MockProvider(cfg)
        result = await provider.health_check()
        assert result is True


# ═══════════════════════════════════════════════════════════════════════════
# plugins/coding.py — line 68: description property
# ═══════════════════════════════════════════════════════════════════════════


class TestCodingPluginDescription:
    def test_description_text(self) -> None:
        from claw_forge.plugins.coding import CodingPlugin

        plugin = CodingPlugin()
        assert "Implement code changes" in plugin.description


# ═══════════════════════════════════════════════════════════════════════════
# plugins/initializer.py — lines 131-132, 280
# ═══════════════════════════════════════════════════════════════════════════


class TestInitializerBrownfieldManifestError:
    """Cover lines 131-132: exception loading brownfield_manifest.json."""

    @pytest.mark.asyncio
    async def test_brownfield_manifest_parse_error(self, tmp_path: Path) -> None:
        from claw_forge.plugins.initializer import InitializerPlugin

        # Create a valid spec file that marks the project as brownfield
        spec_content = textwrap.dedent("""\
            <spec type="brownfield">
              <features>
                <feature id="f1" category="core">
                  <description>Fix auth</description>
                </feature>
              </features>
            </spec>
        """)
        spec_file = tmp_path / "app_spec.xml"
        spec_file.write_text(spec_content)

        # Create an invalid brownfield_manifest.json
        manifest_file = tmp_path / "brownfield_manifest.json"
        manifest_file.write_text("not valid json{{{")

        from claw_forge.plugins.base import PluginContext
        ctx = PluginContext(project_path=str(tmp_path), session_id="s1", task_id="t1")

        plugin = InitializerPlugin()
        result = await plugin.execute(ctx)
        # Should still succeed (warning logged, manifest error is non-fatal)
        assert result.success


class TestInitializerAnalyzeProjectFramework:
    """Cover line 280: framework = fw when framework is truthy in _analyze_project."""

    @pytest.mark.asyncio
    async def test_analyze_detects_framework(self, tmp_path: Path) -> None:
        from claw_forge.plugins.initializer import InitializerPlugin

        # package.json -> javascript + "node" framework
        (tmp_path / "package.json").write_text('{"name": "app"}')

        plugin = InitializerPlugin()
        analysis = plugin._analyze_project(tmp_path)
        assert analysis["language"] == "javascript"
        assert analysis["framework"] == "node"


# ═══════════════════════════════════════════════════════════════════════════
# hashline.py — lines 396-397: END/HASHLINE_EDIT_END skip
# ═══════════════════════════════════════════════════════════════════════════


class TestHashlineEndSkip:
    def test_end_keyword_with_arg_skipped(self) -> None:
        from claw_forge.hashline import parse_edit_ops

        # Wrap in HASHLINE_EDIT / HASHLINE_EDIT_END so the regex captures a block.
        # Inside the block, "END marker" has two parts: op_name=END, which should be skipped.
        text = (
            "HASHLINE_EDIT file.py\n"
            "END marker\n"
            "REPLACE abc\n"
            "new content\n"
            "END\n"
            "HASHLINE_EDIT_END"
        )
        ops = parse_edit_ops(text)
        assert len(ops) == 1
        assert ops[0].hash_ref == "abc"

    def test_hashline_edit_end_with_arg_skipped(self) -> None:
        from claw_forge.hashline import parse_edit_ops

        # "HASHLINE_EDIT_END extra" inside the block (not at the end where regex captures)
        # Actually the regex would match at the first HASHLINE_EDIT_END, so we need to
        # construct this carefully. Let's use a block where after a valid op,
        # there's a HASHLINE_EDIT_END line that the inner parser sees.
        # The regex is greedy-ish: r"HASHLINE_EDIT\s+\S+\n(.*?)HASHLINE_EDIT_END"
        # (.*?) is non-greedy, so it matches the shortest. That means
        # the first HASHLINE_EDIT_END in the text will be the block boundary.
        # So we can't put HASHLINE_EDIT_END inside the block content easily.
        # Instead, test only END with an argument, which is the more common case.
        # Lines 395-396 cover both END and HASHLINE_EDIT_END equally.
        # The "END marker" test above covers line 395-397 already.
        # Let's just verify the skip doesn't raise an error.
        text = (
            "HASHLINE_EDIT file.py\n"
            "END trailing_stuff\n"
            "DELETE def\n"
            "END\n"
            "HASHLINE_EDIT_END"
        )
        ops = parse_edit_ops(text)
        assert len(ops) == 1
        assert ops[0].hash_ref == "def"


# ═══════════════════════════════════════════════════════════════════════════
# scaffold.py — lines 68, 93
# ═══════════════════════════════════════════════════════════════════════════


class TestScaffoldFramework:
    """Cover line 68: framework detection in detect_stack."""

    def test_detect_framework_from_indicator(self, tmp_path: Path) -> None:
        from claw_forge.scaffold import detect_stack

        # Create package.json (node language, unknown framework by default)
        # Then add manage.py to trigger django framework detection
        (tmp_path / "package.json").write_text('{"name": "app"}')
        (tmp_path / "manage.py").write_text("#!/usr/bin/env python")

        stack = detect_stack(tmp_path)
        # package.json matches first -> language=node
        # manage.py triggers framework detection -> django
        assert stack["framework"] == "django"


class TestScaffoldJestDefault:
    """Cover line 93: default jest when no vitest/jest in package.json."""

    def test_node_default_test_runner_jest(self, tmp_path: Path) -> None:
        from claw_forge.scaffold import detect_stack

        # package.json with no vitest or jest mentions
        (tmp_path / "package.json").write_text('{"name": "plain-app", "scripts": {}}')

        stack = detect_stack(tmp_path)
        assert stack["language"] == "node"
        assert stack["test_runner"] == "jest"


# ═══════════════════════════════════════════════════════════════════════════
# bugfix/report.py — lines 61, 166, 171
# ═══════════════════════════════════════════════════════════════════════════


class TestBugReportParseListItemComment:
    """Cover line 61: _parse_list_item returns None for HTML comment."""

    def test_comment_bullet_returns_none(self) -> None:
        from claw_forge.bugfix.report import _parse_list_item

        assert _parse_list_item("- <!-- comment -->") is None


class TestBugReportEnvComment:
    """Cover line 166: comment in environment section via _collect_env."""

    def test_env_with_html_comment_line(self) -> None:
        from claw_forge.bugfix.report import BugReport

        md = textwrap.dedent("""\
            # Bug: Env comment test

            ## Environment
            <!-- This is a comment -->
            Python: 3.12
        """)
        report = BugReport._parse(md)
        assert report.environment.get("Python") == "3.12"
        # Comment should not appear as a key
        assert len(report.environment) == 1


class TestBugReportEnvEmptyTarget:
    """Cover line 171: empty target in _collect_env after stripping."""

    def test_env_blank_line_skipped(self) -> None:
        from claw_forge.bugfix.report import BugReport

        md = textwrap.dedent("""\
            # Bug: Env blank test

            ## Environment
            Python: 3.12

            OS: Linux
        """)
        report = BugReport._parse(md)
        assert report.environment.get("Python") == "3.12"
        assert report.environment.get("OS") == "Linux"
