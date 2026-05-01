"""Tests for the merged_to_target_branch field on the PATCH /tasks/{id} endpoint."""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from claw_forge.state.service import AgentStateService


@pytest.mark.asyncio
async def test_patch_task_persists_merged_to_target_branch(tmp_path: Path) -> None:
    """PATCH /tasks/{id} with merged_to_target_branch=False persists the field."""
    db_path = tmp_path / "state.db"
    svc = AgentStateService(
        database_url=f"sqlite+aiosqlite:///{db_path}",
        project_path=tmp_path,
    )
    async with svc:
        app = svc.create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as cl:
            # Create a session + task
            r = await cl.post("/sessions", json={"project_path": str(tmp_path)})
            session_id = r.json()["id"]
            r = await cl.post(
                f"/sessions/{session_id}/tasks",
                json={"plugin_name": "coding", "description": "X"},
            )
            task_id = r.json()["id"]
            # Default should be True
            r = await cl.get(f"/tasks/{task_id}")
            assert r.json()["merged_to_target_branch"] is True
            # PATCH to False
            r = await cl.patch(
                f"/tasks/{task_id}", json={"merged_to_target_branch": False}
            )
            assert r.status_code == 200
            r = await cl.get(f"/tasks/{task_id}")
            assert r.json()["merged_to_target_branch"] is False
            # PATCH back to True
            r = await cl.patch(
                f"/tasks/{task_id}", json={"merged_to_target_branch": True}
            )
            r = await cl.get(f"/tasks/{task_id}")
            assert r.json()["merged_to_target_branch"] is True
