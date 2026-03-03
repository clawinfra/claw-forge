"""Tests for the human input request system.

Tests cover:
- Feature moves to needs_human on POST /features/{id}/human-input
- GET /features/needs-human lists pending questions
- Answer moves feature back to pending (POST /features/{id}/human-answer)
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from claw_forge.state.service import AgentStateService

# ── Helpers ───────────────────────────────────────────────────────────────────


async def _make_client() -> tuple[AsyncClient, AgentStateService]:
    """Create an in-memory AgentStateService with DB initialised.

    The returned client disposes the engine on close (BUG-10 fix).
    """
    svc = AgentStateService("sqlite+aiosqlite:///:memory:")
    await svc.init_db()
    app = svc.create_app()

    class _CleanupClient(AsyncClient):
        async def aclose(self) -> None:
            await super().aclose()
            await svc.dispose()

    client = _CleanupClient(transport=ASGITransport(app=app), base_url="http://test")
    return client, svc


async def _make_session(client: AsyncClient, path: str = "/tmp/test") -> str:
    resp = await client.post("/sessions", json={"project_path": path})
    assert resp.status_code == 201
    return resp.json()["id"]


async def _make_task(client: AsyncClient, session_id: str, plugin: str = "coding") -> str:
    resp = await client.post(
        f"/sessions/{session_id}/tasks",
        json={"plugin_name": plugin, "description": "Do the thing"},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


# ── needs_human status transition ─────────────────────────────────────────────


class TestHumanInputStatus:
    @pytest.mark.asyncio
    async def test_post_human_input_moves_to_needs_human(self) -> None:
        """POSTing a question to /features/{id}/human-input should set status=needs_human."""
        client, _ = await _make_client()
        async with client:
            session_id = await _make_session(client)
            task_id = await _make_task(client, session_id)

            resp = await client.post(
                f"/features/{task_id}/human-input",
                json={"question": "What database should I use?"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["task_id"] == task_id
            assert data["status"] == "needs_human"
            assert data["question"] == "What database should I use?"

    @pytest.mark.asyncio
    async def test_human_input_stores_question(self) -> None:
        """The question text should be persisted in the task record."""
        client, _ = await _make_client()
        async with client:
            session_id = await _make_session(client)
            task_id = await _make_task(client, session_id)
            question = "Should I use Redis or Postgres for the queue?"

            await client.post(
                f"/features/{task_id}/human-input",
                json={"question": question},
            )

            # Verify via the needs-human listing
            resp = await client.get(f"/features/needs-human?session_id={session_id}")
            assert resp.status_code == 200
            items = resp.json()
            assert len(items) == 1
            assert items[0]["question"] == question
            assert items[0]["task_id"] == task_id

    @pytest.mark.asyncio
    async def test_human_input_unknown_task_returns_404(self) -> None:
        client, _ = await _make_client()
        async with client:
            resp = await client.post(
                "/features/nonexistent-id/human-input",
                json={"question": "Hello?"},
            )
            assert resp.status_code == 404


# ── List pending questions (GET /features/needs-human) ────────────────────────


class TestListNeedsHuman:
    @pytest.mark.asyncio
    async def test_list_empty_when_no_pending(self) -> None:
        client, _ = await _make_client()
        async with client:
            session_id = await _make_session(client)
            resp = await client.get(f"/features/needs-human?session_id={session_id}")
            assert resp.status_code == 200
            assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_shows_multiple_pending_questions(self) -> None:
        client, _ = await _make_client()
        async with client:
            session_id = await _make_session(client)
            task1_id = await _make_task(client, session_id, "coding")
            task2_id = await _make_task(client, session_id, "testing")

            await client.post(f"/features/{task1_id}/human-input", json={"question": "Q1"})
            await client.post(f"/features/{task2_id}/human-input", json={"question": "Q2"})

            resp = await client.get(f"/features/needs-human?session_id={session_id}")
            items = resp.json()
            assert len(items) == 2
            questions = {i["question"] for i in items}
            assert questions == {"Q1", "Q2"}

    @pytest.mark.asyncio
    async def test_list_without_session_filter_returns_all(self) -> None:
        client, _ = await _make_client()
        async with client:
            sid1 = await _make_session(client, "/tmp/proj1")
            sid2 = await _make_session(client, "/tmp/proj2")

            t1 = await _make_task(client, sid1)
            t2 = await _make_task(client, sid2)

            await client.post(f"/features/{t1}/human-input", json={"question": "QA"})
            await client.post(f"/features/{t2}/human-input", json={"question": "QB"})

            resp = await client.get("/features/needs-human")
            items = resp.json()
            assert len(items) == 2


# ── Answer moves feature back to pending ─────────────────────────────────────


class TestHumanAnswer:
    @pytest.mark.asyncio
    async def test_answer_moves_task_to_pending(self) -> None:
        """After submitting an answer, the task status should be 'pending' again."""
        client, _ = await _make_client()
        async with client:
            session_id = await _make_session(client)
            task_id = await _make_task(client, session_id)

            # Put task into needs_human
            await client.post(
                f"/features/{task_id}/human-input",
                json={"question": "Which auth strategy?"},
            )

            # Submit answer
            resp = await client.post(
                f"/features/{task_id}/human-answer",
                json={"answer": "Use JWT with RS256"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["task_id"] == task_id
            assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_answer_not_in_needs_human_returns_400(self) -> None:
        """Answering a task that is NOT in needs_human should return 400."""
        client, _ = await _make_client()
        async with client:
            session_id = await _make_session(client)
            task_id = await _make_task(client, session_id)

            # Task is still "pending" — not needs_human
            resp = await client.post(
                f"/features/{task_id}/human-answer",
                json={"answer": "whatever"},
            )
            assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_answered_task_removed_from_needs_human_list(self) -> None:
        """After answering, the task should NOT appear in /features/needs-human."""
        client, _ = await _make_client()
        async with client:
            session_id = await _make_session(client)
            task_id = await _make_task(client, session_id)

            await client.post(f"/features/{task_id}/human-input", json={"question": "Q?"})
            # Verify it appears
            items = (await client.get(f"/features/needs-human?session_id={session_id}")).json()
            assert len(items) == 1

            # Submit answer
            await client.post(f"/features/{task_id}/human-answer", json={"answer": "A!"})

            # Should be gone now
            items = (await client.get(f"/features/needs-human?session_id={session_id}")).json()
            assert len(items) == 0

    @pytest.mark.asyncio
    async def test_answer_unknown_task_returns_404(self) -> None:
        client, _ = await _make_client()
        async with client:
            resp = await client.post(
                "/features/ghost-id/human-answer",
                json={"answer": "whatever"},
            )
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_answer_clears_previous_question(self) -> None:
        """Posting a new question after an answer should work correctly."""
        client, _ = await _make_client()
        async with client:
            session_id = await _make_session(client)
            task_id = await _make_task(client, session_id)

            # First question/answer cycle
            await client.post(f"/features/{task_id}/human-input", json={"question": "Q1"})
            await client.post(f"/features/{task_id}/human-answer", json={"answer": "A1"})

            # Second question
            resp = await client.post(f"/features/{task_id}/human-input", json={"question": "Q2"})
            assert resp.status_code == 200
            assert resp.json()["question"] == "Q2"

            # human_answer should be cleared (new question pending)
            items = (await client.get(f"/features/needs-human?session_id={session_id}")).json()
            assert len(items) == 1
            assert items[0]["question"] == "Q2"
