"""Semaphore-bounded agent pool runner."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from claw_forge.pool.manager import ProviderPoolManager, ProviderPoolExhausted
from claw_forge.pool.providers.base import ProviderResponse

logger = logging.getLogger(__name__)


class AgentRun:
    """A single agent execution with its messages and config."""

    def __init__(
        self,
        agent_id: str,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.0,
        tools: list[dict[str, Any]] | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.model = model
        self.system = system
        self.messages = messages
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.tools = tools
        self.response: ProviderResponse | None = None
        self.error: str | None = None


class PoolRunner:
    """Run multiple agent tasks concurrently with semaphore bounding.

    Uses the ProviderPoolManager for automatic failover across providers.
    """

    def __init__(
        self,
        pool: ProviderPoolManager,
        max_concurrent: int = 5,
    ) -> None:
        self._pool = pool
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active: set[str] = set()

    async def run_batch(self, runs: list[AgentRun]) -> list[AgentRun]:
        """Execute a batch of agent runs concurrently."""
        async with asyncio.TaskGroup() as tg:
            for run in runs:
                tg.create_task(self._execute(run))
        return runs

    async def _execute(self, run: AgentRun) -> None:
        async with self._semaphore:
            self._active.add(run.agent_id)
            try:
                run.response = await self._pool.execute(
                    model=run.model,
                    messages=run.messages,
                    max_tokens=run.max_tokens,
                    temperature=run.temperature,
                    system=run.system,
                    tools=run.tools,
                )
            except ProviderPoolExhausted as e:
                run.error = str(e)
                logger.error("Agent %s: pool exhausted: %s", run.agent_id, e)
            except Exception as e:
                run.error = str(e)
                logger.exception("Agent %s: unexpected error", run.agent_id)
            finally:
                self._active.discard(run.agent_id)

    @property
    def active_count(self) -> int:
        return len(self._active)
