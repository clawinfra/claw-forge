"""Tests for async dispatcher."""

import pytest

from claw_forge.orchestrator.dispatcher import Dispatcher
from claw_forge.state.scheduler import TaskNode


async def _success_handler(task: TaskNode) -> dict:
    return {"status": "done", "task": task.id}


async def _failing_handler(task: TaskNode) -> dict:
    if task.id == "fail":
        raise RuntimeError("intentional")
    return {"status": "done"}


class TestDispatcher:
    @pytest.mark.asyncio
    async def test_simple_dispatch(self):
        d = Dispatcher(handler=_success_handler)
        d.add_task(TaskNode("a", "coding", 1, []))
        d.add_task(TaskNode("b", "testing", 1, []))
        result = await d.run()
        assert result.all_succeeded
        assert "a" in result.completed
        assert "b" in result.completed

    @pytest.mark.asyncio
    async def test_dependency_waves(self):
        order = []

        async def _tracking_handler(task):
            order.append(task.id)
            return {}

        d = Dispatcher(handler=_tracking_handler)
        d.add_task(TaskNode("a", "init", 1, []))
        d.add_task(TaskNode("b", "code", 1, ["a"]))
        result = await d.run()
        assert result.all_succeeded
        assert order.index("a") < order.index("b")
