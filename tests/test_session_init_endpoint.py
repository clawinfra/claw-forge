"""Tests for POST /sessions/init endpoint."""

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
class TestSessionInit:
    async def test_creates_new_session_when_none_exists(
        self, app_client: AsyncClient,
    ) -> None:
        resp = await app_client.post(
            "/sessions/init", json={"project_path": "/my/project"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"]
        assert data["tasks"] == []

    async def test_reuses_existing_session(
        self, app_client: AsyncClient,
    ) -> None:
        sess = await app_client.post(
            "/sessions", json={"project_path": "/my/project"}
        )
        sid = sess.json()["id"]
        await app_client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "coding", "description": "Task A"},
        )

        resp = await app_client.post(
            "/sessions/init", json={"project_path": "/my/project"}
        )
        data = resp.json()
        assert data["session_id"] == sid
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["description"] == "Task A"

    async def test_resets_orphaned_running_tasks(
        self, app_client: AsyncClient,
    ) -> None:
        sess = await app_client.post(
            "/sessions", json={"project_path": "/my/project"}
        )
        sid = sess.json()["id"]
        t = await app_client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "coding", "description": "Orphan"},
        )
        tid = t.json()["id"]
        await app_client.patch(f"/tasks/{tid}", json={"status": "running"})

        resp = await app_client.post(
            "/sessions/init", json={"project_path": "/my/project"}
        )
        data = resp.json()
        orphan = [t for t in data["tasks"] if t["id"] == tid][0]
        assert orphan["status"] == "pending"
        assert data.get("orphans_reset", 0) == 1

    async def test_excludes_completed_tasks(
        self, app_client: AsyncClient,
    ) -> None:
        sess = await app_client.post(
            "/sessions", json={"project_path": "/my/project"}
        )
        sid = sess.json()["id"]
        t1 = await app_client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "coding", "description": "Done"},
        )
        await app_client.patch(
            f"/tasks/{t1.json()['id']}", json={"status": "completed"}
        )
        await app_client.post(
            f"/sessions/{sid}/tasks",
            json={"plugin_name": "coding", "description": "Pending"},
        )

        resp = await app_client.post(
            "/sessions/init", json={"project_path": "/my/project"}
        )
        data = resp.json()
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["description"] == "Pending"
