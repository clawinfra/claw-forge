"""Tests for shape + plugin round-trip through the tasks HTTP API."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from claw_forge.state.service import AgentStateService


@pytest.fixture()
async def svc(tmp_path: Path) -> AsyncGenerator[AgentStateService, None]:
    s = AgentStateService(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/state.db",
        project_path=tmp_path,
    )
    async with s:
        yield s


class TestTaskShapeAndPlugin:
    """Round-trip shape/plugin through POST /sessions/{id}/tasks → GET /tasks/{id}."""

    @pytest.mark.asyncio
    async def test_create_task_round_trips_shape_and_plugin(
        self, svc: AgentStateService, tmp_path: Path
    ) -> None:
        """POST a task with shape='plugin' plugin='auth'; verify it survives the GET round-trip."""
        async with AsyncClient(
            transport=ASGITransport(app=svc.create_app()), base_url="http://test"
        ) as cl:
            # 1. Create a session
            r = await cl.post("/sessions", json={"project_path": str(tmp_path)})
            assert r.status_code == 201
            sid = r.json()["id"]

            # 2. POST a task with shape='plugin', plugin='auth', touches_files
            r = await cl.post(
                f"/sessions/{sid}/tasks",
                json={
                    "plugin_name": "coding",
                    "shape": "plugin",
                    "plugin": "auth",
                    "touches_files": ["src/plugins/auth/**"],
                },
            )
            assert r.status_code == 201, r.text
            tid = r.json()["id"]

            # 3. GET the task
            r = await cl.get(f"/tasks/{tid}")
            assert r.status_code == 200

            # 4. Assert shape and plugin survived the round-trip
            body = r.json()
            assert body["shape"] == "plugin"
            assert body["plugin"] == "auth"

    @pytest.mark.asyncio
    async def test_create_task_shape_core_round_trips(
        self, svc: AgentStateService, tmp_path: Path
    ) -> None:
        """shape='core' with no plugin should also round-trip correctly."""
        async with AsyncClient(
            transport=ASGITransport(app=svc.create_app()), base_url="http://test"
        ) as cl:
            r = await cl.post("/sessions", json={"project_path": str(tmp_path)})
            sid = r.json()["id"]

            r = await cl.post(
                f"/sessions/{sid}/tasks",
                json={"plugin_name": "coding", "shape": "core"},
            )
            assert r.status_code == 201, r.text
            tid = r.json()["id"]

            r = await cl.get(f"/tasks/{tid}")
            assert r.status_code == 200
            body = r.json()
            assert body["shape"] == "core"
            assert body["plugin"] is None

    @pytest.mark.asyncio
    async def test_create_task_without_shape_defaults_none(
        self, svc: AgentStateService, tmp_path: Path
    ) -> None:
        """Tasks without shape/plugin default to None for both fields."""
        async with AsyncClient(
            transport=ASGITransport(app=svc.create_app()), base_url="http://test"
        ) as cl:
            r = await cl.post("/sessions", json={"project_path": str(tmp_path)})
            sid = r.json()["id"]

            r = await cl.post(
                f"/sessions/{sid}/tasks", json={"plugin_name": "coding"}
            )
            assert r.status_code == 201, r.text
            tid = r.json()["id"]

            r = await cl.get(f"/tasks/{tid}")
            assert r.status_code == 200
            body = r.json()
            assert body["shape"] is None
            assert body["plugin"] is None
