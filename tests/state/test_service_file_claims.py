"""Tests for the file-claims HTTP API."""
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


async def _create_session_and_tasks(
    cl: AsyncClient, project: str
) -> tuple[str, str, str]:
    r = await cl.post("/sessions", json={"project_path": project})
    sid = r.json()["id"]
    r = await cl.post(f"/sessions/{sid}/tasks", json={"plugin_name": "coding"})
    t1 = r.json()["id"]
    r = await cl.post(f"/sessions/{sid}/tasks", json={"plugin_name": "coding"})
    t2 = r.json()["id"]
    return sid, t1, t2


@pytest.mark.asyncio
async def test_post_file_claim_succeeds_and_returns_claimed_paths(
    svc: AgentStateService, tmp_path: Path
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=svc.create_app()), base_url="http://test"
    ) as cl:
        sid, t1, _ = await _create_session_and_tasks(cl, str(tmp_path))
        r = await cl.post(
            f"/sessions/{sid}/file-claims",
            json={"task_id": t1, "file_paths": ["a.py", "b.py"]},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["claimed"] is True
        assert body["conflicts"] == []


@pytest.mark.asyncio
async def test_post_file_claim_returns_409_on_conflict(
    svc: AgentStateService, tmp_path: Path
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=svc.create_app()), base_url="http://test"
    ) as cl:
        sid, t1, t2 = await _create_session_and_tasks(cl, str(tmp_path))
        await cl.post(
            f"/sessions/{sid}/file-claims",
            json={"task_id": t1, "file_paths": ["a.py"]},
        )
        r = await cl.post(
            f"/sessions/{sid}/file-claims",
            json={"task_id": t2, "file_paths": ["a.py", "b.py"]},
        )
        assert r.status_code == 409
        body = r.json()
        assert body["claimed"] is False
        assert body["conflicts"] == ["a.py"]


@pytest.mark.asyncio
async def test_delete_file_claims_releases_task(
    svc: AgentStateService, tmp_path: Path
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=svc.create_app()), base_url="http://test"
    ) as cl:
        sid, t1, _ = await _create_session_and_tasks(cl, str(tmp_path))
        await cl.post(
            f"/sessions/{sid}/file-claims",
            json={"task_id": t1, "file_paths": ["a.py", "b.py"]},
        )
        r = await cl.delete(f"/sessions/{sid}/file-claims/{t1}")
        assert r.status_code == 200
        assert r.json()["released"] == 2
        r = await cl.get(f"/sessions/{sid}/file-claims")
        assert r.json()["claims"] == []


@pytest.mark.asyncio
async def test_get_file_claims_lists_current(
    svc: AgentStateService, tmp_path: Path
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=svc.create_app()), base_url="http://test"
    ) as cl:
        sid, t1, t2 = await _create_session_and_tasks(cl, str(tmp_path))
        await cl.post(
            f"/sessions/{sid}/file-claims",
            json={"task_id": t1, "file_paths": ["a.py"]},
        )
        await cl.post(
            f"/sessions/{sid}/file-claims",
            json={"task_id": t2, "file_paths": ["b.py"]},
        )
        r = await cl.get(f"/sessions/{sid}/file-claims")
        assert r.status_code == 200
        rows = r.json()["claims"]
        assert sorted((c["task_id"], c["file_path"]) for c in rows) == sorted(
            [(t1, "a.py"), (t2, "b.py")]
        )


@pytest.mark.asyncio
async def test_patch_task_status_completed_releases_claims(
    svc: AgentStateService, tmp_path: Path
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=svc.create_app()), base_url="http://test"
    ) as cl:
        sid, t1, _ = await _create_session_and_tasks(cl, str(tmp_path))
        await cl.post(
            f"/sessions/{sid}/file-claims",
            json={"task_id": t1, "file_paths": ["a.py"]},
        )
        await cl.patch(f"/tasks/{t1}", json={"status": "completed"})
        r = await cl.get(f"/sessions/{sid}/file-claims")
        assert r.json()["claims"] == []


@pytest.mark.asyncio
async def test_patch_task_status_failed_releases_claims(
    svc: AgentStateService, tmp_path: Path
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=svc.create_app()), base_url="http://test"
    ) as cl:
        sid, t1, _ = await _create_session_and_tasks(cl, str(tmp_path))
        await cl.post(
            f"/sessions/{sid}/file-claims",
            json={"task_id": t1, "file_paths": ["a.py"]},
        )
        await cl.patch(f"/tasks/{t1}", json={"status": "failed"})
        r = await cl.get(f"/sessions/{sid}/file-claims")
        assert r.json()["claims"] == []


@pytest.mark.asyncio
async def test_patch_task_status_running_does_not_release_claims(
    svc: AgentStateService, tmp_path: Path
) -> None:
    """Status flip to running keeps claims held."""
    async with AsyncClient(
        transport=ASGITransport(app=svc.create_app()), base_url="http://test"
    ) as cl:
        sid, t1, _ = await _create_session_and_tasks(cl, str(tmp_path))
        await cl.post(
            f"/sessions/{sid}/file-claims",
            json={"task_id": t1, "file_paths": ["a.py"]},
        )
        await cl.patch(f"/tasks/{t1}", json={"status": "running"})
        r = await cl.get(f"/sessions/{sid}/file-claims")
        assert len(r.json()["claims"]) == 1
