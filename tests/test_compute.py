"""Tests for claw_forge.compute — @offload_heavy decorator and process pool."""
from __future__ import annotations

import asyncio
import os

import pytest

from claw_forge.compute import get_pool, offload_heavy, shutdown_pool


def _cpu_work(n: int) -> int:
    """Pure CPU-bound function — returns (n * 2) + pid to prove cross-process."""
    return n * 2 + os.getpid()


@offload_heavy
def decorated_cpu_work(n: int) -> int:
    return n * 2 + os.getpid()


class TestOffloadHeavy:
    @pytest.mark.asyncio
    async def test_returns_awaitable(self) -> None:
        result = decorated_cpu_work(5)
        assert asyncio.iscoroutine(result)
        await result  # cleanup

    @pytest.mark.asyncio
    async def test_runs_in_separate_process(self) -> None:
        result = await decorated_cpu_work(5)
        child_component = result - 10  # n*2 = 10, remainder is child pid
        assert child_component != os.getpid()

    @pytest.mark.asyncio
    async def test_correct_computation(self) -> None:
        result = await decorated_cpu_work(7)
        assert result >= 14


class TestPool:
    def test_lazy_init(self) -> None:
        pool = get_pool()
        assert pool is not None
        assert pool._max_workers <= 4

    def test_shutdown_idempotent(self) -> None:
        shutdown_pool()
        shutdown_pool()  # should not raise

    def test_pool_recreated_after_shutdown(self) -> None:
        pool1 = get_pool()
        shutdown_pool()
        pool2 = get_pool()
        assert pool2 is not pool1

    @pytest.mark.asyncio
    async def test_kwargs_not_supported(self) -> None:
        """run_in_executor does not support kwargs — verify clear failure."""
        with pytest.raises(TypeError):
            await decorated_cpu_work(n=5)
