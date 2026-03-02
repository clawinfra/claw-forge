from __future__ import annotations

"""Tests for pause/resume (drain mode) behaviour."""


import asyncio  # noqa: E402

import pytest  # noqa: E402

from claw_forge.orchestrator.dispatcher import Dispatcher  # noqa: E402
from claw_forge.state.scheduler import TaskNode  # noqa: E402

# ── Helpers ───────────────────────────────────────────────────────────────────


async def _simple_handler(task: TaskNode) -> dict:
    return {"status": "done", "task": task.id}


async def _slow_handler(task: TaskNode) -> dict:
    await asyncio.sleep(0.05)
    return {"status": "done", "task": task.id}


# ── Pause / resume unit tests ─────────────────────────────────────────────────


class TestPauseResumeState:
    def test_not_paused_by_default(self) -> None:
        d = Dispatcher(handler=_simple_handler)
        assert d.is_paused is False

    def test_pause_sets_flag(self) -> None:
        d = Dispatcher(handler=_simple_handler)
        d.pause()
        assert d.is_paused is True

    def test_resume_clears_flag(self) -> None:
        d = Dispatcher(handler=_simple_handler)
        d.pause()
        d.resume()
        assert d.is_paused is False

    def test_pause_then_resume_then_pause(self) -> None:
        d = Dispatcher(handler=_simple_handler)
        d.pause()
        assert d.is_paused is True
        d.resume()
        assert d.is_paused is False
        d.pause()
        assert d.is_paused is True

    def test_resume_without_pause_is_idempotent(self) -> None:
        d = Dispatcher(handler=_simple_handler)
        d.resume()  # should not raise
        assert d.is_paused is False


# ── Dispatcher stops new waves when paused ────────────────────────────────────


class TestPauseStopsDispatch:
    @pytest.mark.asyncio
    async def test_pause_before_run_skips_all_waves(self) -> None:
        """If paused before run(), no tasks should be dispatched."""
        d = Dispatcher(handler=_simple_handler)
        d.add_task(TaskNode("a", "coding", 5, []))
        d.add_task(TaskNode("b", "coding", 5, []))
        d.pause()
        result = await d.run()

        # No tasks completed since we paused before starting
        assert len(result.completed) == 0
        assert len(result.failed) == 0

    @pytest.mark.asyncio
    async def test_paused_flag_stops_between_waves(self) -> None:
        """Pause mid-run: wave 1 completes, wave 2 is skipped."""
        completed_ids: list[str] = []

        async def tracking_handler(task: TaskNode) -> dict:
            completed_ids.append(task.id)
            return {}

        d = Dispatcher(handler=tracking_handler)
        # Wave 1: 'a' (no deps)
        d.add_task(TaskNode("a", "coding", 5, []))
        # Wave 2: 'b' depends on 'a'
        d.add_task(TaskNode("b", "coding", 5, ["a"]))

        # Pause AFTER wave 1 would complete but BEFORE wave 2 starts
        # We do this by patching the pause flag to True after 'a' runs
        original_handler = d._handler

        async def pausing_handler(task: TaskNode) -> dict:
            result = await original_handler(task)
            if task.id == "a":
                d.pause()  # Pause after first wave task completes
            return result

        d._handler = pausing_handler
        await d.run()

        # 'a' completed, 'b' was skipped because paused between waves
        assert "a" in completed_ids
        assert "b" not in completed_ids


# ── In-flight agents complete when paused ────────────────────────────────────


class TestInflightCompletesOnPause:
    @pytest.mark.asyncio
    async def test_inflight_tasks_complete_when_paused(self) -> None:
        """Tasks already running in a wave must finish even if paused."""
        completed_ids: list[str] = []

        async def slow_tracking_handler(task: TaskNode) -> dict:
            await asyncio.sleep(0.01)
            completed_ids.append(task.id)
            return {}

        d = Dispatcher(handler=slow_tracking_handler, max_concurrency=10)
        # All in wave 1 (no deps) — they run concurrently
        for i in range(4):
            d.add_task(TaskNode(f"t{i}", "coding", 5, []))

        # Pause while tasks are running (they still complete)
        async def run_and_pause() -> None:
            task = asyncio.create_task(d.run())
            await asyncio.sleep(0.005)  # let tasks start
            d.pause()
            await task

        await run_and_pause()

        # All wave-1 tasks completed despite pause
        assert len(completed_ids) == 4


# ── Resume restores normal dispatch ─────────────────────────────────────────


class TestResumeRestoresDispatch:
    @pytest.mark.asyncio
    async def test_resume_allows_more_tasks(self) -> None:
        """After resume, new tasks added and run() called should dispatch normally."""
        d = Dispatcher(handler=_simple_handler)
        d.add_task(TaskNode("a", "coding", 5, []))
        d.pause()

        # Run while paused — no tasks should complete
        result1 = await d.run()
        assert len(result1.completed) == 0

        # Resume and run again
        d.resume()
        d.add_task(TaskNode("b", "coding", 5, []))
        result2 = await d.run()

        # Both tasks available — 'a' and 'b'
        assert result2.all_succeeded


# ── State service pause/resume endpoints ──────────────────────────────────────


class TestPauseResumeAPI:
    """Test the state service REST endpoints for pause/resume."""

    async def _make_client(self):  # type: ignore[return]
        """Create an in-memory service with DB pre-initialized."""
        from httpx import ASGITransport, AsyncClient

        from claw_forge.state.service import AgentStateService

        svc = AgentStateService("sqlite+aiosqlite:///:memory:")
        await svc.init_db()
        app = svc.create_app()
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        return client, svc

    @pytest.mark.asyncio
    async def test_pause_endpoint_sets_flag(self) -> None:
        client, _ = await self._make_client()
        async with client:
            # Create a session
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            assert resp.status_code == 201
            session_id = resp.json()["id"]

            # Pause it
            resp = await client.post(f"/project/pause?session_id={session_id}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["paused"] is True
            assert data["session_id"] == session_id

    @pytest.mark.asyncio
    async def test_resume_endpoint_clears_flag(self) -> None:
        client, _ = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]

            # Pause then resume
            await client.post(f"/project/pause?session_id={session_id}")
            resp = await client.post(f"/project/resume?session_id={session_id}")
            assert resp.status_code == 200
            assert resp.json()["paused"] is False

    @pytest.mark.asyncio
    async def test_is_paused_endpoint(self) -> None:
        client, _ = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]

            # Initially not paused
            resp = await client.get(f"/project/paused?session_id={session_id}")
            assert resp.status_code == 200
            assert resp.json()["paused"] is False

            # Pause
            await client.post(f"/project/pause?session_id={session_id}")
            resp = await client.get(f"/project/paused?session_id={session_id}")
            assert resp.json()["paused"] is True

    @pytest.mark.asyncio
    async def test_pause_unknown_session_returns_404(self) -> None:
        client, _ = await self._make_client()
        async with client:
            resp = await client.post("/project/pause?session_id=nonexistent")
            assert resp.status_code == 404
