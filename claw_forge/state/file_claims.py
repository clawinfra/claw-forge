"""Pure helpers for file-claim CRUD.

Kept out of ``service.py`` so the atomic-claim semantics can be unit-tested
without spinning up FastAPI.
"""
from __future__ import annotations

from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from claw_forge.state.models import FileClaim


async def try_claim(
    db: AsyncSession, session_id: str, task_id: str, file_paths: list[str],
) -> dict[str, Any]:
    """Claim *file_paths* for *task_id* in *session_id*, atomically.

    Returns ``{"claimed": True, "conflicts": []}`` on success.  Returns
    ``{"claimed": False, "conflicts": [<paths held by other tasks>]}`` on
    conflict; no partial claims are committed in that case.

    Idempotent for the same task: re-claiming a path the same task already
    holds is a no-op success.
    """
    existing_q = await db.execute(
        select(FileClaim.file_path, FileClaim.task_id).where(
            FileClaim.session_id == session_id,
            FileClaim.file_path.in_(file_paths),
        )
    )
    existing = {row.file_path: row.task_id for row in existing_q}
    conflicts = [p for p, holder in existing.items() if holder != task_id]
    if conflicts:
        return {"claimed": False, "conflicts": sorted(conflicts)}
    new_paths = [p for p in file_paths if p not in existing]
    db.add_all([
        FileClaim(session_id=session_id, task_id=task_id, file_path=p)
        for p in new_paths
    ])
    await db.commit()
    return {"claimed": True, "conflicts": []}


async def release_for_task(db: AsyncSession, task_id: str) -> int:
    """Drop all claims held by *task_id*.  Returns the number of rows deleted."""
    result = cast(
        CursorResult[Any],
        await db.execute(delete(FileClaim).where(FileClaim.task_id == task_id)),
    )
    await db.commit()
    return result.rowcount or 0


async def claims_for_session(
    db: AsyncSession, session_id: str,
) -> list[FileClaim]:
    """Return all live claims for *session_id*, ordered by claimed_at."""
    q = await db.execute(
        select(FileClaim)
        .where(FileClaim.session_id == session_id)
        .order_by(FileClaim.claimed_at)
    )
    return list(q.scalars().all())
