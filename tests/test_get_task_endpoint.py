"""Tests for GET /tasks/{task_id} endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from claw_forge.state.service import AgentStateService


@pytest.fixture()
async def app_client(tmp_path: Path):
    db_path = tmp_path / "test.db"
    svc = AgentStateService(f"sqlite+aiosqlite:///{db_path}")
    try:
        await svc.init_db()
        app = svc.create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c
    finally:
        await svc.dispose()


@pytest.mark.asyncio
class TestGetTask:
    async def test_get_existing_task(self, app_client: AsyncClient) -> None:
        sess = await app_client.post("/sessions", json={"project_path": "/p"})
        sid = sess.json()["id"]
        created = await app_client.post(
            f"/sessions/{sid}/tasks",
            json={
                "plugin_name": "coding",
                "description": "Implement auth",
                "steps": ["Create endpoint", "Add tests"],
                "category": "backend",
            },
        )
        task_id = created.json()["id"]

        resp = await app_client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == task_id
        assert data["description"] == "Implement auth"
        assert data["steps"] == ["Create endpoint", "Add tests"]
        assert data["plugin_name"] == "coding"
        assert data["status"] == "pending"

    async def test_get_nonexistent_task(self, app_client: AsyncClient) -> None:
        resp = await app_client.get("/tasks/nonexistent-id")
        assert resp.status_code == 404
