"""Regression tests for BUG-10, BUG-11, BUG-12."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from claw_forge.plugins.coding import extract_code_blocks, write_code_blocks
from claw_forge.pool.manager import ProviderPoolExhausted, ProviderPoolManager
from claw_forge.pool.providers.base import (
    BaseProvider,
    ProviderConfig,
    ProviderError,
    ProviderResponse,
    ProviderType,
    RateLimitError,
)

# ── BUG-10: Event loop closed warnings in test teardown ──────────────────────


class TestBug10EventLoopCleanup:
    """Verify that AgentStateService fixtures properly dispose their engines."""

    @pytest.mark.asyncio
    async def test_service_dispose_closes_engine(self) -> None:
        """AgentStateService.dispose() should close the underlying engine."""
        from claw_forge.state.service import AgentStateService

        svc = AgentStateService(database_url="sqlite+aiosqlite:///:memory:")
        await svc.init_db()
        # dispose should not raise
        await svc.dispose()
        # Calling dispose again should be safe (idempotent)
        await svc.dispose()

    @pytest.mark.asyncio
    async def test_service_async_context_manager_disposes(self) -> None:
        """Using AgentStateService as an async context manager should auto-dispose."""
        from claw_forge.state.service import AgentStateService

        svc = AgentStateService(database_url="sqlite+aiosqlite:///:memory:")
        async with svc as s:
            # Should be usable inside context
            assert s is svc
        # After exiting context, engine should be disposed (no warnings)

    @pytest.mark.asyncio
    async def test_service_fixture_pattern_no_warning(self) -> None:
        """Replicate the fixture pattern: create, init, yield, dispose."""
        from claw_forge.state.service import AgentStateService

        svc = AgentStateService(database_url="sqlite+aiosqlite:///:memory:")
        await svc.init_db()
        # Simulate some usage
        assert svc._engine is not None
        # Cleanup
        await svc.dispose()


# ── BUG-11: API-only mode — LLM output not written to disk ──────────────────


class TestBug11ExtractCodeBlocks:
    """Test fenced code block extraction from LLM output."""

    def test_extract_single_file(self) -> None:
        text = "Here is the code:\n```src/main.py\nprint('hello')\n```\nDone."
        blocks = extract_code_blocks(text)
        assert len(blocks) == 1
        assert blocks[0][0] == "src/main.py"
        assert blocks[0][1] == "print('hello')\n"

    def test_extract_multiple_files(self) -> None:
        text = (
            "```app.py\nfrom flask import Flask\n```\n"
            "And the tests:\n"
            "```tests/test_app.py\nimport pytest\n```"
        )
        blocks = extract_code_blocks(text)
        assert len(blocks) == 2
        assert blocks[0][0] == "app.py"
        assert blocks[1][0] == "tests/test_app.py"

    def test_ignores_language_only_blocks(self) -> None:
        text = "```python\nprint('hello')\n```"
        blocks = extract_code_blocks(text)
        assert len(blocks) == 0

    def test_ignores_blocks_without_file_extension(self) -> None:
        text = "```bash\necho hello\n```"
        blocks = extract_code_blocks(text)
        assert len(blocks) == 0

    def test_handles_nested_dirs(self) -> None:
        text = "```src/utils/helpers.py\ndef helper(): pass\n```"
        blocks = extract_code_blocks(text)
        assert len(blocks) == 1
        assert blocks[0][0] == "src/utils/helpers.py"

    def test_empty_string(self) -> None:
        assert extract_code_blocks("") == []

    def test_no_code_blocks(self) -> None:
        assert extract_code_blocks("Just some text without code.") == []


    def test_ignores_shell_command_paths(self) -> None:
        """Regression: shell command paths like path/to/check must not become files."""
        text = "```path/to/check\nls /tmp\n```\n"
        blocks = extract_code_blocks(text)
        assert blocks == [], f"Expected no blocks, got: {blocks}"

    def test_accepts_extensioned_nested_paths(self) -> None:
        """Files like src/hello/cli.py must still be recognised."""
        text = "```src/hello/cli.py\nprint('hi')\n```"
        blocks = extract_code_blocks(text)
        assert len(blocks) == 1
        assert blocks[0][0] == "src/hello/cli.py"

class TestBug11WriteCodeBlocks:
    """Test that code blocks are actually written to disk."""

    def test_write_single_file(self, tmp_path: Path) -> None:
        text = "```hello.py\nprint('hello world')\n```"
        written = write_code_blocks(tmp_path, text)
        assert written == ["hello.py"]
        assert (tmp_path / "hello.py").read_text() == "print('hello world')\n"

    def test_write_nested_file(self, tmp_path: Path) -> None:
        text = "```src/lib/utils.py\ndef util(): return 42\n```"
        written = write_code_blocks(tmp_path, text)
        assert written == ["src/lib/utils.py"]
        assert (tmp_path / "src" / "lib" / "utils.py").read_text() == "def util(): return 42\n"

    def test_write_multiple_files(self, tmp_path: Path) -> None:
        text = (
            "```a.py\nA\n```\n"
            "some text\n"
            "```b/c.py\nBC\n```"
        )
        written = write_code_blocks(tmp_path, text)
        assert set(written) == {"a.py", "b/c.py"}
        assert (tmp_path / "a.py").read_text() == "A\n"
        assert (tmp_path / "b" / "c.py").read_text() == "BC\n"

    def test_no_file_blocks_returns_empty(self, tmp_path: Path) -> None:
        text = "```python\nno file path here\n```"
        written = write_code_blocks(tmp_path, text)
        assert written == []


# ── BUG-12: Rate-limit retry has no backoff ──────────────────────────────────


class _TimingProvider(BaseProvider):
    """Provider that records call timestamps and always raises."""

    def __init__(self, config: ProviderConfig, error: Exception) -> None:
        super().__init__(config)
        self.call_times: list[float] = []
        self._error = error

    async def execute(self, model: str, messages: list, **kwargs) -> ProviderResponse:  # type: ignore[override]
        self.call_times.append(time.monotonic())
        raise self._error

    async def health_check(self) -> bool:
        return True


class TestBug12RetryBackoff:
    """Verify exponential backoff on retryable errors and rate limits."""

    @pytest.mark.asyncio
    async def test_retryable_error_has_backoff(self) -> None:
        """Retryable ProviderError should sleep between retries (not immediate)."""
        config = ProviderConfig(
            name="test", provider_type=ProviderType.ANTHROPIC, api_key="k"
        )
        error = ProviderError("server error", retryable=True)
        provider = _TimingProvider(config, error)

        mgr = ProviderPoolManager(
            [config], max_retries=3, backoff_base=0.1, backoff_max=5.0
        )
        mgr._providers = [provider]
        from claw_forge.pool.health import CircuitBreaker
        mgr._circuits = {
            "test": CircuitBreaker("test", failure_threshold=100)
        }

        with pytest.raises(ProviderPoolExhausted):
            await mgr.execute("model", [{"role": "user", "content": "hi"}])

        # Should have been called 3 times (once per attempt, single provider)
        assert len(provider.call_times) >= 2

        # Verify there's actual delay between calls (not immediate retry)
        for i in range(1, len(provider.call_times)):
            gap = provider.call_times[i] - provider.call_times[i - 1]
            # With backoff_base=0.1, minimum gap should be > 0.05s
            assert gap > 0.05, f"Gap between retry {i-1} and {i} too small: {gap:.3f}s"

    @pytest.mark.asyncio
    async def test_rate_limit_has_backoff(self) -> None:
        """RateLimitError without retry_after should use exponential backoff."""
        config = ProviderConfig(
            name="test", provider_type=ProviderType.ANTHROPIC, api_key="k"
        )
        error = RateLimitError("429 too many requests", retry_after=None)
        provider = _TimingProvider(config, error)

        mgr = ProviderPoolManager(
            [config], max_retries=3, backoff_base=0.1, backoff_max=5.0
        )
        mgr._providers = [provider]
        from claw_forge.pool.health import CircuitBreaker
        mgr._circuits = {
            "test": CircuitBreaker("test", failure_threshold=100)
        }

        with pytest.raises(ProviderPoolExhausted):
            await mgr.execute("model", [{"role": "user", "content": "hi"}])

        assert len(provider.call_times) >= 2

        for i in range(1, len(provider.call_times)):
            gap = provider.call_times[i] - provider.call_times[i - 1]
            assert gap > 0.05, f"Rate limit retry gap too small: {gap:.3f}s"

    @pytest.mark.asyncio
    async def test_non_retryable_error_no_backoff(self) -> None:
        """Non-retryable errors should NOT sleep — just skip to next provider."""
        config = ProviderConfig(
            name="test", provider_type=ProviderType.ANTHROPIC, api_key="k"
        )
        error = ProviderError("bad request", retryable=False)
        provider = _TimingProvider(config, error)

        mgr = ProviderPoolManager(
            [config], max_retries=2, backoff_base=0.5, backoff_max=5.0
        )
        mgr._providers = [provider]
        from claw_forge.pool.health import CircuitBreaker
        mgr._circuits = {
            "test": CircuitBreaker("test", failure_threshold=100)
        }

        with pytest.raises(ProviderPoolExhausted):
            await mgr.execute("model", [{"role": "user", "content": "hi"}])

        # Non-retryable errors should fail fast without long delays
        if len(provider.call_times) >= 2:
            total_time = provider.call_times[-1] - provider.call_times[0]
            # Should be very fast since no backoff sleep
            assert total_time < 0.5, f"Non-retryable took too long: {total_time:.3f}s"

    @pytest.mark.asyncio
    async def test_rate_limit_with_retry_after_respects_header(self) -> None:
        """RateLimitError with retry_after should use that value."""
        config = ProviderConfig(
            name="test", provider_type=ProviderType.ANTHROPIC, api_key="k"
        )
        error = RateLimitError("429", retry_after=0.15)
        provider = _TimingProvider(config, error)

        mgr = ProviderPoolManager(
            [config], max_retries=2, backoff_base=0.01, backoff_max=5.0
        )
        mgr._providers = [provider]
        from claw_forge.pool.health import CircuitBreaker
        mgr._circuits = {
            "test": CircuitBreaker("test", failure_threshold=100)
        }

        with pytest.raises(ProviderPoolExhausted):
            await mgr.execute("model", [{"role": "user", "content": "hi"}])

        # With retry_after=0.15, gap should be at least 0.1s
        if len(provider.call_times) >= 2:
            gap = provider.call_times[1] - provider.call_times[0]
            assert gap >= 0.1, f"retry_after not respected: gap={gap:.3f}s"
