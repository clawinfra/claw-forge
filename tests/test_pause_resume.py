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
        """Create an in-memory service with DB pre-initialized.

        The returned client disposes the engine on close (BUG-10 fix).
        """
        from httpx import ASGITransport, AsyncClient

        from claw_forge.state.service import AgentStateService

        svc = AgentStateService("sqlite+aiosqlite:///:memory:")
        await svc.init_db()
        app = svc.create_app()

        class _CleanupClient(AsyncClient):
            async def aclose(self) -> None:
                await super().aclose()
                await svc.dispose()

        client = _CleanupClient(transport=ASGITransport(app=app), base_url="http://test")
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


# ── Stop-all / Resume-all task endpoints ─────────────────────────────────────


class TestStopAllResumeAll:
    """Test the stop-all and resume-all task endpoints."""

    async def _make_client(self):  # type: ignore[return]
        from httpx import ASGITransport, AsyncClient

        from claw_forge.state.service import AgentStateService

        svc = AgentStateService("sqlite+aiosqlite:///:memory:")
        await svc.init_db()
        app = svc.create_app()

        class _CleanupClient(AsyncClient):
            async def aclose(self) -> None:
                await super().aclose()
                await svc.dispose()

        return _CleanupClient(transport=ASGITransport(app=app), base_url="http://test")

    async def _setup_running_tasks(self, client, session_id: str) -> tuple[str, str]:
        """Create two tasks and set them to running. Returns (task1_id, task2_id)."""
        t1 = await client.post(
            f"/sessions/{session_id}/tasks",
            json={"plugin_name": "coding", "description": "task 1"},
        )
        t2 = await client.post(
            f"/sessions/{session_id}/tasks",
            json={"plugin_name": "coding", "description": "task 2"},
        )
        task1_id = t1.json()["id"]
        task2_id = t2.json()["id"]
        await client.patch(f"/tasks/{task1_id}", json={"status": "running"})
        await client.patch(f"/tasks/{task2_id}", json={"status": "running"})
        return task1_id, task2_id

    @pytest.mark.asyncio
    async def test_stop_all_sets_tasks_to_paused(self) -> None:
        client = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]
            task1_id, task2_id = await self._setup_running_tasks(client, session_id)

            resp = await client.post(f"/sessions/{session_id}/tasks/stop-all")
            assert resp.status_code == 200
            data = resp.json()
            assert set(data["stopped"]) == {task1_id, task2_id}

            tasks = await client.get(f"/sessions/{session_id}/tasks")
            for t in tasks.json():
                assert t["status"] == "paused", f"Expected paused, got {t['status']}"

    @pytest.mark.asyncio
    async def test_stop_all_sets_project_paused_flag(self) -> None:
        client = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]
            await self._setup_running_tasks(client, session_id)

            await client.post(f"/sessions/{session_id}/tasks/stop-all")
            resp = await client.get(f"/project/paused?session_id={session_id}")
            assert resp.json()["paused"] is True

    @pytest.mark.asyncio
    async def test_stop_poll_returns_pause_flag_after_stop_all(self) -> None:
        client = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]
            await self._setup_running_tasks(client, session_id)

            await client.post(f"/sessions/{session_id}/tasks/stop-all")
            resp = await client.get("/stop-poll")
            data = resp.json()
            assert data["pause"] is True
            # Flag is cleared after first poll
            resp2 = await client.get("/stop-poll")
            assert resp2.json()["pause"] is False

    @pytest.mark.asyncio
    async def test_resume_all_sets_tasks_to_pending(self) -> None:
        client = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]
            task1_id, task2_id = await self._setup_running_tasks(client, session_id)

            await client.post(f"/sessions/{session_id}/tasks/stop-all")
            resp = await client.post(f"/sessions/{session_id}/tasks/resume-all")
            assert resp.status_code == 200
            data = resp.json()
            assert set(data["resumed"]) == {task1_id, task2_id}

            tasks = await client.get(f"/sessions/{session_id}/tasks")
            for t in tasks.json():
                assert t["status"] == "pending"

    @pytest.mark.asyncio
    async def test_resume_all_clears_project_paused_flag(self) -> None:
        client = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]
            await self._setup_running_tasks(client, session_id)

            await client.post(f"/sessions/{session_id}/tasks/stop-all")
            await client.post(f"/sessions/{session_id}/tasks/resume-all")
            resp = await client.get(f"/project/paused?session_id={session_id}")
            assert resp.json()["paused"] is False

    @pytest.mark.asyncio
    async def test_stop_poll_returns_resume_flag_after_resume_all(self) -> None:
        client = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]
            await self._setup_running_tasks(client, session_id)

            await client.post(f"/sessions/{session_id}/tasks/stop-all")
            await client.get("/stop-poll")  # drain the pause flag
            await client.post(f"/sessions/{session_id}/tasks/resume-all")
            resp = await client.get("/stop-poll")
            data = resp.json()
            assert data["resume"] is True
            # Flag is cleared after first poll
            resp2 = await client.get("/stop-poll")
            assert resp2.json()["resume"] is False

    @pytest.mark.asyncio
    async def test_stop_all_no_running_tasks_returns_empty(self) -> None:
        """stop-all on a session with no running tasks returns empty list."""
        client = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]
            resp = await client.post(f"/sessions/{session_id}/tasks/stop-all")
            assert resp.status_code == 200
            assert resp.json()["stopped"] == []

    @pytest.mark.asyncio
    async def test_agent_logs_suppressed_after_stop_all(self) -> None:
        """Agent log POSTs return 'suppressed' for paused tasks."""
        client = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]
            task1_id, _ = await self._setup_running_tasks(client, session_id)

            # Before stop-all: log should broadcast (status "ok")
            resp = await client.post(
                f"/tasks/{task1_id}/agent-log",
                json={"role": "assistant", "content": "hello", "task_name": "t1"},
            )
            assert resp.json()["status"] == "ok"

            # After stop-all: logs suppressed for paused task IDs
            await client.post(f"/sessions/{session_id}/tasks/stop-all")
            resp = await client.post(
                f"/tasks/{task1_id}/agent-log",
                json={"role": "assistant", "content": "still running", "task_name": "t1"},
            )
            assert resp.json()["status"] == "suppressed"

    @pytest.mark.asyncio
    async def test_agent_logs_resume_after_resume_all(self) -> None:
        """Agent logs are broadcast again after resume-all clears the paused set."""
        client = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]
            task1_id, _ = await self._setup_running_tasks(client, session_id)

            await client.post(f"/sessions/{session_id}/tasks/stop-all")
            await client.post(f"/sessions/{session_id}/tasks/resume-all")

            # After resume: logs should flow again (task is now "pending" but we just
            # verify the suppression set was cleared)
            resp = await client.post(
                f"/tasks/{task1_id}/agent-log",
                json={"role": "assistant", "content": "resumed log", "task_name": "t1"},
            )
            assert resp.json()["status"] == "ok"


# ── Paused-status guard ───────────────────────────────────────────────────────


class TestPausedStatusGuard:
    """PATCH /tasks/{id} must not overwrite 'paused' with 'pending'.

    When a task is paused via POST /tasks/{id}/stop or POST /sessions/{id}/tasks/stop-all,
    the dispatcher's asyncio task is subsequently cancelled.  The CLI's finally-block
    calls PATCH /tasks/{id} with status='pending' before returning.  Without a guard,
    this overwrites the 'paused' status and the task jumps to the Pending column
    immediately — before the user explicitly resumes it.
    """

    async def _make_client(self):  # type: ignore[return]
        from httpx import ASGITransport, AsyncClient

        from claw_forge.state.service import AgentStateService

        svc = AgentStateService("sqlite+aiosqlite:///:memory:")
        await svc.init_db()
        app = svc.create_app()

        class _CleanupClient(AsyncClient):
            async def aclose(self) -> None:
                await super().aclose()
                await svc.dispose()

        return _CleanupClient(transport=ASGITransport(app=app), base_url="http://test")

    # ── Single-task stop ──────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_stop_one_task_status_not_overwritten_by_pending_patch(self) -> None:
        """POST /tasks/{id}/stop sets 'paused'; a subsequent PATCH to 'pending' is ignored."""
        client = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]

            t = await client.post(
                f"/sessions/{session_id}/tasks",
                json={"plugin_name": "coding", "description": "task A"},
            )
            task_id = t.json()["id"]

            # Mark running, then stop (sets to "paused")
            await client.patch(f"/tasks/{task_id}", json={"status": "running"})
            await client.post(f"/tasks/{task_id}/stop")

            # Simulate CLI cancel-finally: PATCH back to "pending"
            await client.patch(f"/tasks/{task_id}", json={"status": "pending"})

            resp = await client.get(f"/tasks/{task_id}")
            assert resp.json()["status"] == "paused", (
                f"Paused status was overwritten — got '{resp.json()['status']}'"
            )

    @pytest.mark.asyncio
    async def test_stop_one_task_paused_guard_does_not_block_other_transitions(self) -> None:
        """Guard only blocks paused→pending; running→pending must still work normally."""
        client = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]

            t = await client.post(
                f"/sessions/{session_id}/tasks",
                json={"plugin_name": "coding", "description": "task B"},
            )
            task_id = t.json()["id"]

            # running → pending (NOT paused) must still succeed
            await client.patch(f"/tasks/{task_id}", json={"status": "running"})
            await client.patch(f"/tasks/{task_id}", json={"status": "pending"})

            resp = await client.get(f"/tasks/{task_id}")
            assert resp.json()["status"] == "pending"

    # ── Stop-all ─────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_stop_all_tasks_not_overwritten_by_pending_patch(self) -> None:
        """stop-all sets all running tasks to 'paused'; PATCH to 'pending' is ignored for each."""
        client = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]

            t1 = await client.post(
                f"/sessions/{session_id}/tasks",
                json={"plugin_name": "coding", "description": "task 1"},
            )
            t2 = await client.post(
                f"/sessions/{session_id}/tasks",
                json={"plugin_name": "coding", "description": "task 2"},
            )
            task1_id = t1.json()["id"]
            task2_id = t2.json()["id"]

            await client.patch(f"/tasks/{task1_id}", json={"status": "running"})
            await client.patch(f"/tasks/{task2_id}", json={"status": "running"})

            # Stop all (sets both to "paused")
            await client.post(f"/sessions/{session_id}/tasks/stop-all")

            # Simulate CLI cancel-finally for both tasks
            await client.patch(f"/tasks/{task1_id}", json={"status": "pending"})
            await client.patch(f"/tasks/{task2_id}", json={"status": "pending"})

            tasks = (await client.get(f"/sessions/{session_id}/tasks")).json()
            for task in tasks:
                assert task["status"] == "paused", (
                    f"Task {task['id']}: expected 'paused' but got '{task['status']}'"
                )

    @pytest.mark.asyncio
    async def test_stop_all_resume_all_still_transitions_paused_to_pending(self) -> None:
        """resume-all must still move paused→pending (via SQLAlchemy, not the PATCH guard path)."""
        client = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]

            t1 = await client.post(
                f"/sessions/{session_id}/tasks",
                json={"plugin_name": "coding", "description": "task 1"},
            )
            task1_id = t1.json()["id"]
            await client.patch(f"/tasks/{task1_id}", json={"status": "running"})

            await client.post(f"/sessions/{session_id}/tasks/stop-all")
            await client.post(f"/sessions/{session_id}/tasks/resume-all")

            resp = await client.get(f"/tasks/{task1_id}")
            assert resp.json()["status"] == "pending", (
                f"resume-all should set paused→pending but got '{resp.json()['status']}'"
            )


# ── Batch requeue: failed/blocked → pending ──────────────────────────────────


class TestRequeueTasks:
    """Test the ``POST /sessions/{id}/tasks/requeue`` batch endpoint.

    Requeue resets ``failed`` and/or ``blocked`` tasks back to ``pending`` so
    the dispatcher will pick them up on the next run.  Optionally filtered by
    SQL ``LIKE`` pattern on ``error_message`` (e.g. only rate-limit failures).
    """

    async def _make_client(self):  # type: ignore[return]
        from httpx import ASGITransport, AsyncClient

        from claw_forge.state.service import AgentStateService

        svc = AgentStateService("sqlite+aiosqlite:///:memory:")
        await svc.init_db()
        app = svc.create_app()

        class _CleanupClient(AsyncClient):
            async def aclose(self) -> None:
                await super().aclose()
                await svc.dispose()

        return _CleanupClient(transport=ASGITransport(app=app), base_url="http://test")

    async def _create_task(
        self, client, session_id: str, *, status: str = "pending",
        error_message: str | None = None, description: str = "task",
    ) -> str:
        resp = await client.post(
            f"/sessions/{session_id}/tasks",
            json={"plugin_name": "coding", "description": description},
        )
        task_id = resp.json()["id"]
        patch = {"status": status}
        if error_message is not None:
            patch["error_message"] = error_message
        await client.patch(f"/tasks/{task_id}", json=patch)
        return task_id

    @pytest.mark.asyncio
    async def test_requeue_failed_tasks_resets_to_pending(self) -> None:
        client = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]
            t1 = await self._create_task(client, session_id, status="failed")
            t2 = await self._create_task(client, session_id, status="failed")
            t_completed = await self._create_task(client, session_id, status="completed")

            resp = await client.post(
                f"/sessions/{session_id}/tasks/requeue",
                json={"statuses": ["failed"]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert set(data["requeued"]) == {t1, t2}
            assert data["count"] == 2

            tasks = (await client.get(f"/sessions/{session_id}/tasks")).json()
            by_id = {t["id"]: t for t in tasks}
            assert by_id[t1]["status"] == "pending"
            assert by_id[t2]["status"] == "pending"
            # completed task is untouched
            assert by_id[t_completed]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_requeue_blocked_tasks_resets_to_pending(self) -> None:
        client = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]
            t = await self._create_task(client, session_id, status="blocked")

            resp = await client.post(
                f"/sessions/{session_id}/tasks/requeue",
                json={"statuses": ["blocked"]},
            )
            assert resp.status_code == 200
            assert resp.json()["count"] == 1

            tasks = (await client.get(f"/sessions/{session_id}/tasks")).json()
            assert {t_["id"]: t_["status"] for t_ in tasks}[t] == "pending"

    @pytest.mark.asyncio
    async def test_requeue_clears_error_message(self) -> None:
        client = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]
            t = await self._create_task(
                client, session_id, status="failed",
                error_message="Agent error: rate_limit",
            )

            await client.post(
                f"/sessions/{session_id}/tasks/requeue",
                json={"statuses": ["failed"]},
            )
            row = (await client.get(f"/tasks/{t}")).json()
            assert row["status"] == "pending"
            assert (row.get("error_message") in (None, "")), (
                f"requeue must clear error_message; got {row.get('error_message')!r}"
            )

    @pytest.mark.asyncio
    async def test_requeue_with_error_pattern_filters_by_message(self) -> None:
        """``error_pattern`` (SQL LIKE) lets the caller scope the requeue —
        only rate-limit failures are reset, real failures stay failed."""
        client = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]
            rate_limited = await self._create_task(
                client, session_id, status="failed",
                error_message="Agent error: rate_limit — check claude login",
            )
            real_failure = await self._create_task(
                client, session_id, status="failed",
                error_message="Agent error: merge conflict in foo.py",
            )

            resp = await client.post(
                f"/sessions/{session_id}/tasks/requeue",
                json={"statuses": ["failed"], "error_pattern": "%rate_limit%"},
            )
            assert resp.json()["count"] == 1
            assert resp.json()["requeued"] == [rate_limited]

            by_id = {t["id"]: t["status"] for t in (
                await client.get(f"/sessions/{session_id}/tasks")
            ).json()}
            assert by_id[rate_limited] == "pending"
            assert by_id[real_failure] == "failed"

    @pytest.mark.asyncio
    async def test_requeue_default_statuses_is_failed_and_blocked(self) -> None:
        """When no ``statuses`` are passed, defaults to resetting both
        failed AND blocked — the common 'reset everything stuck' case."""
        client = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]
            t_failed = await self._create_task(client, session_id, status="failed")
            t_blocked = await self._create_task(client, session_id, status="blocked")
            t_pending = await self._create_task(client, session_id, status="pending")

            resp = await client.post(
                f"/sessions/{session_id}/tasks/requeue",
                json={},
            )
            assert set(resp.json()["requeued"]) == {t_failed, t_blocked}
            assert resp.json()["count"] == 2

            by_id = {t["id"]: t["status"] for t in (
                await client.get(f"/sessions/{session_id}/tasks")
            ).json()}
            assert by_id[t_failed] == "pending"
            assert by_id[t_blocked] == "pending"
            assert by_id[t_pending] == "pending"  # already was pending

    @pytest.mark.asyncio
    async def test_requeue_empty_set_returns_count_zero(self) -> None:
        """No matching tasks → count 0, no error."""
        client = await self._make_client()
        async with client:
            resp = await client.post("/sessions", json={"project_path": "/tmp/test"})
            session_id = resp.json()["id"]
            await self._create_task(client, session_id, status="completed")

            resp = await client.post(
                f"/sessions/{session_id}/tasks/requeue",
                json={"statuses": ["failed"]},
            )
            assert resp.json()["count"] == 0
            assert resp.json()["requeued"] == []
