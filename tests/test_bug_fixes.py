"""Regression tests for BUG-10, BUG-11, and BUG-12.

BUG-10: Event loop closed warnings in test teardown (aiosqlite cleanup)
BUG-11: API-only mode — code not written to disk (output_parser)
BUG-12: Rate-limit retry has no backoff (exponential backoff with jitter)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# BUG-10: Event loop closed warnings — service dispose
# ---------------------------------------------------------------------------


class TestBug10EventLoopCleanup:
    """Verify AgentStateService properly disposes its async engine."""

    @pytest.mark.asyncio
    async def test_dispose_closes_engine(self) -> None:
        """AgentStateService.dispose() should dispose the async engine."""
        from claw_forge.state.service import AgentStateService

        svc = AgentStateService("sqlite+aiosqlite:///:memory:")
        await svc.init_db()

        # Engine should be functional
        async with svc._engine.begin() as conn:
            result = await conn.execute(
                __import__("sqlalchemy").text("SELECT 1")
            )
            assert result.scalar() == 1

        # Dispose should succeed without error
        await svc.dispose()

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        """AgentStateService supports async with for auto-cleanup."""
        from claw_forge.state.service import AgentStateService

        async with AgentStateService("sqlite+aiosqlite:///:memory:") as svc:
            # DB should be initialized
            async with svc._engine.begin() as conn:
                result = await conn.execute(
                    __import__("sqlalchemy").text("SELECT 1")
                )
                assert result.scalar() == 1
        # After exiting context, engine should be disposed

    @pytest.mark.asyncio
    async def test_double_dispose_is_safe(self) -> None:
        """Calling dispose() twice should not raise."""
        from claw_forge.state.service import AgentStateService

        svc = AgentStateService("sqlite+aiosqlite:///:memory:")
        await svc.init_db()
        await svc.dispose()
        # Second dispose should be safe
        await svc.dispose()


# ---------------------------------------------------------------------------
# BUG-11: API-only mode — code not written to disk
# ---------------------------------------------------------------------------


class TestBug11OutputParser:
    """Verify code blocks are parsed and written to disk."""

    def test_extract_filename_with_path(self) -> None:
        """Code block with filename info string is extracted."""
        from claw_forge.output_parser import extract_code_blocks

        text = '```src/main.py\nprint("hello")\n```'
        blocks = extract_code_blocks(text)
        assert len(blocks) == 1
        assert blocks[0][0] == "src/main.py"
        assert 'print("hello")' in blocks[0][1]

    def test_extract_with_language_prefix(self) -> None:
        """Code block with lang:filename is extracted."""
        from claw_forge.output_parser import extract_code_blocks

        text = '```python:src/app.py\ndef main():\n    pass\n```'
        blocks = extract_code_blocks(text)
        assert len(blocks) == 1
        assert blocks[0][0] == "src/app.py"

    def test_extract_with_language_space_filename(self) -> None:
        """Code block with 'lang filename' is extracted."""
        from claw_forge.output_parser import extract_code_blocks

        text = '```python src/utils.py\ndef helper():\n    return 42\n```'
        blocks = extract_code_blocks(text)
        assert len(blocks) == 1
        assert blocks[0][0] == "src/utils.py"

    def test_skip_language_only_blocks(self) -> None:
        """Code blocks with only a language tag are skipped."""
        from claw_forge.output_parser import extract_code_blocks

        text = '```python\nprint("no filename")\n```'
        blocks = extract_code_blocks(text)
        assert len(blocks) == 0

    def test_skip_empty_info_string(self) -> None:
        """Code blocks with no info string are skipped."""
        from claw_forge.output_parser import extract_code_blocks

        text = '```\nbare block\n```'
        blocks = extract_code_blocks(text)
        assert len(blocks) == 0

    def test_multiple_blocks(self) -> None:
        """Multiple code blocks are all extracted."""
        from claw_forge.output_parser import extract_code_blocks

        text = (
            '```src/a.py\ncode_a\n```\n'
            'some text\n'
            '```src/b.py\ncode_b\n```'
        )
        blocks = extract_code_blocks(text)
        assert len(blocks) == 2
        assert blocks[0][0] == "src/a.py"
        assert blocks[1][0] == "src/b.py"

    def test_write_code_blocks(self, tmp_path: Path) -> None:
        """write_code_blocks creates files on disk."""
        from claw_forge.output_parser import write_code_blocks

        text = (
            "Here's the implementation:\n\n"
            '```src/main.py\nprint("hello world")\n```\n\n'
            '```tests/test_main.py\ndef test_hello():\n    assert True\n```'
        )
        written = write_code_blocks(text, tmp_path)
        assert len(written) == 2
        assert "src/main.py" in written
        assert "tests/test_main.py" in written

        # Verify files exist on disk
        assert (tmp_path / "src" / "main.py").exists()
        assert (tmp_path / "tests" / "test_main.py").exists()
        assert (tmp_path / "src" / "main.py").read_text() == 'print("hello world")\n'

    def test_write_blocks_creates_directories(self, tmp_path: Path) -> None:
        """Nested directories are created automatically."""
        from claw_forge.output_parser import write_code_blocks

        text = '```deep/nested/dir/file.py\ncontent\n```'
        written = write_code_blocks(text, tmp_path)
        assert len(written) == 1
        assert (tmp_path / "deep" / "nested" / "dir" / "file.py").exists()

    def test_write_blocks_rejects_absolute_paths(self, tmp_path: Path) -> None:
        """Absolute paths are rejected for security."""
        from claw_forge.output_parser import write_code_blocks

        text = '```/etc/passwd\nhacked\n```'
        written = write_code_blocks(text, tmp_path)
        assert len(written) == 0

    def test_write_blocks_rejects_path_traversal(self, tmp_path: Path) -> None:
        """Path traversal (../) is rejected."""
        from claw_forge.output_parser import write_code_blocks

        text = '```../../etc/shadow\nhacked\n```'
        written = write_code_blocks(text, tmp_path)
        assert len(written) == 0

    def test_write_blocks_no_code_blocks(self, tmp_path: Path) -> None:
        """When there are no code blocks, nothing is written."""
        from claw_forge.output_parser import write_code_blocks

        text = "Just some plain text with no code blocks."
        written = write_code_blocks(text, tmp_path)
        assert len(written) == 0

    def test_parse_filename_variants(self) -> None:
        """Test the _parse_filename helper for edge cases."""
        from claw_forge.output_parser import _parse_filename

        assert _parse_filename("src/main.py") == "src/main.py"
        assert _parse_filename("python:src/main.py") == "src/main.py"
        assert _parse_filename("python src/main.py") == "src/main.py"
        assert _parse_filename("python") is None
        assert _parse_filename("") is None
        assert _parse_filename("  ") is None
        assert _parse_filename("app.py") == "app.py"
        assert _parse_filename("Makefile") is None  # no dot or slash


# ---------------------------------------------------------------------------
# BUG-12: Rate-limit retry has no backoff
# ---------------------------------------------------------------------------


class TestBug12RateLimitBackoff:
    """Verify exponential backoff on rate-limit errors without retry_after."""

    @pytest.mark.asyncio
    async def test_rate_limit_with_retry_after(self) -> None:
        """When retry_after is set, use that value for sleep."""
        from claw_forge.pool.manager import ProviderPoolManager
        from claw_forge.pool.providers.base import (
            ProviderConfig,
            ProviderResponse,
            ProviderType,
            RateLimitError,
        )

        config = ProviderConfig(
            name="test-provider",
            provider_type=ProviderType.ANTHROPIC,
            api_key="test",
            priority=1,
        )
        pool = ProviderPoolManager([config], max_retries=2)

        call_count = 0
        sleep_durations: list[float] = []

        async def mock_execute(*args: Any, **kwargs: Any) -> ProviderResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RateLimitError("rate limited", retry_after=2.5)
            return ProviderResponse(
                content="ok", model="test", provider_name="test-provider"
            )

        pool._providers[0].execute = mock_execute  # type: ignore[attr-defined]

        original_sleep = asyncio.sleep

        async def tracking_sleep(duration: float) -> None:
            sleep_durations.append(duration)
            # Don't actually sleep in tests

        with patch("claw_forge.pool.manager.asyncio.sleep", side_effect=tracking_sleep):
            result = await pool.execute(
                model="test", messages=[{"role": "user", "content": "hi"}]
            )

        assert result.content == "ok"
        assert call_count == 2
        # Should have slept with the retry_after value (capped at backoff_max)
        assert len(sleep_durations) >= 1
        assert sleep_durations[0] == 2.5

    @pytest.mark.asyncio
    async def test_rate_limit_without_retry_after_uses_backoff(self) -> None:
        """When retry_after is None, exponential backoff with jitter is used."""
        from claw_forge.pool.manager import ProviderPoolManager
        from claw_forge.pool.providers.base import (
            ProviderConfig,
            ProviderResponse,
            ProviderType,
            RateLimitError,
        )

        config = ProviderConfig(
            name="test-provider",
            provider_type=ProviderType.ANTHROPIC,
            api_key="test",
            priority=1,
        )
        pool = ProviderPoolManager(
            [config], max_retries=3, backoff_base=1.0, backoff_max=30.0
        )

        call_count = 0
        sleep_durations: list[float] = []

        async def mock_execute(*args: Any, **kwargs: Any) -> ProviderResponse:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RateLimitError("rate limited")  # No retry_after
            return ProviderResponse(
                content="ok", model="test", provider_name="test-provider"
            )

        pool._providers[0].execute = mock_execute  # type: ignore[attr-defined]

        async def tracking_sleep(duration: float) -> None:
            sleep_durations.append(duration)

        with patch("claw_forge.pool.manager.asyncio.sleep", side_effect=tracking_sleep):
            result = await pool.execute(
                model="test", messages=[{"role": "user", "content": "hi"}]
            )

        assert result.content == "ok"
        assert call_count == 3
        # Should have used exponential backoff for both rate-limit retries
        assert len(sleep_durations) >= 2
        # First backoff: base=1.0 * 2^0 = 1.0, with jitter up to 0.5 → [1.0, 1.5]
        assert 1.0 <= sleep_durations[0] <= 1.5
        # Second backoff: base=1.0 * 2^1 = 2.0, with jitter up to 1.0 → [2.0, 3.0]
        assert 2.0 <= sleep_durations[1] <= 3.0

    @pytest.mark.asyncio
    async def test_rate_limit_backoff_never_exceeds_max(self) -> None:
        """Backoff should be capped at backoff_max."""
        from claw_forge.pool.manager import ProviderPoolExhausted, ProviderPoolManager
        from claw_forge.pool.providers.base import (
            ProviderConfig,
            ProviderType,
            RateLimitError,
        )

        config = ProviderConfig(
            name="test-provider",
            provider_type=ProviderType.ANTHROPIC,
            api_key="test",
            priority=1,
        )
        pool = ProviderPoolManager(
            [config], max_retries=3, backoff_base=10.0, backoff_max=5.0
        )

        async def mock_execute(*args: Any, **kwargs: Any) -> None:
            raise RateLimitError("rate limited")

        pool._providers[0].execute = mock_execute  # type: ignore[attr-defined]

        sleep_durations: list[float] = []

        async def tracking_sleep(duration: float) -> None:
            sleep_durations.append(duration)

        with patch("claw_forge.pool.manager.asyncio.sleep", side_effect=tracking_sleep):
            with pytest.raises(ProviderPoolExhausted):
                await pool.execute(
                    model="test", messages=[{"role": "user", "content": "hi"}]
                )

        # All sleep durations should be capped at backoff_max (5.0) + jitter (up to 2.5)
        for duration in sleep_durations:
            assert duration <= 5.0 + 5.0 * 0.5  # max + max jitter

    @pytest.mark.asyncio
    async def test_rate_limit_always_sleeps(self) -> None:
        """Rate-limit errors should ALWAYS trigger a sleep — never retry instantly."""
        from claw_forge.pool.manager import ProviderPoolExhausted, ProviderPoolManager
        from claw_forge.pool.providers.base import (
            ProviderConfig,
            ProviderType,
            RateLimitError,
        )

        config = ProviderConfig(
            name="test-provider",
            provider_type=ProviderType.ANTHROPIC,
            api_key="test",
            priority=1,
        )
        pool = ProviderPoolManager([config], max_retries=2)

        rate_limit_count = 0

        async def mock_execute(*args: Any, **kwargs: Any) -> None:
            nonlocal rate_limit_count
            rate_limit_count += 1
            raise RateLimitError("rate limited")  # No retry_after

        pool._providers[0].execute = mock_execute  # type: ignore[attr-defined]

        sleep_calls = 0

        async def counting_sleep(duration: float) -> None:
            nonlocal sleep_calls
            sleep_calls += 1
            assert duration > 0, "Backoff duration must be positive"

        with patch("claw_forge.pool.manager.asyncio.sleep", side_effect=counting_sleep):
            with pytest.raises(ProviderPoolExhausted):
                await pool.execute(
                    model="test", messages=[{"role": "user", "content": "hi"}]
                )

        # Every rate-limit error should have triggered a sleep
        assert sleep_calls > 0, "Rate-limit errors must trigger backoff sleep"
