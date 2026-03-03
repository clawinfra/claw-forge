"""claw-forge status command — zero-friction project re-entry."""

from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

_BAR_WIDTH = 20
_DEFAULT_PORT = 8420


def _load_config(config_path: str) -> dict[str, Any]:
    """Load YAML config file, returning raw dict."""
    path = Path(config_path)
    if not path.exists():
        return {}
    raw: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    return raw


def _progress_bar(done: int, total: int, width: int = _BAR_WIDTH) -> str:
    if total == 0:
        return "░" * width
    filled = min(round(width * done / total), width)
    return "█" * filled + "░" * (width - filled)


def _read_db(project_path: Path) -> list[dict[str, Any]] | None:
    """Read tasks directly from .claw-forge/state.db. Returns None if no DB."""
    db_path = project_path / ".claw-forge" / "state.db"
    if not db_path.exists():
        return None

    async def _fetch() -> list[dict[str, Any]]:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from claw_forge.state.models import Session as DbSession
        from claw_forge.state.models import Task

        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}", echo=False
        )
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        rows: list[dict[str, Any]] = []
        async with maker() as sess:
            # Get most recent session for this project
            stmt_sess = (
                select(DbSession)
                .where(DbSession.project_path == str(project_path.resolve()))
                .order_by(DbSession.created_at.desc())
                .limit(1)
            )
            db_sess = (await sess.execute(stmt_sess)).scalar_one_or_none()
            if db_sess is None:
                await engine.dispose()
                return []
            stmt_tasks = select(Task).where(Task.session_id == db_sess.id)
            tasks = (await sess.execute(stmt_tasks)).scalars().all()
            for t in tasks:
                rows.append({
                    "id": t.id,
                    "description": t.description or "",
                    "status": t.status,
                    "plugin_name": t.plugin_name,
                    "error_message": t.error_message,
                    "started_at": str(t.started_at) if t.started_at else None,
                    "completed_at": str(t.completed_at) if t.completed_at else None,
                    "cost_usd": t.cost_usd or 0.0,
                })
        await engine.dispose()
        return rows

    try:
        return asyncio.run(_fetch())
    except Exception:
        return None


def run_help(  # noqa: C901
    config_path: str = "claw-forge.yaml",
    project_path: str = ".",
) -> None:
    """Render the claw-forge project status card to stdout."""
    project = Path(project_path).resolve()
    cfg = _load_config(config_path)

    tasks = _read_db(project)

    # ── No DB yet ──────────────────────────────────────────────────────────────
    if tasks is None:
        print("No plan found — run `claw-forge plan <spec>` to get started.")
        return

    # ── Counts ─────────────────────────────────────────────────────────────────
    status_counts: Counter[str] = Counter(t["status"] for t in tasks)
    total = len(tasks)
    done = status_counts["completed"]
    failed = status_counts["failed"]
    running = status_counts["running"]
    pending = status_counts["pending"]
    pct = int(100 * done / total) if total else 0

    # ── Header ─────────────────────────────────────────────────────────────────
    print("╔══════════════════════════════════════════════════════╗")
    print("║  claw-forge · Project Status                        ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()
    print(f"  📋 Project : {project.name}")
    model = cfg.get("model", "claude-sonnet-4-20250514")
    print(f"  🤖 Model   : {model}")
    print()

    # ── Progress bar ───────────────────────────────────────────────────────────
    bar = _progress_bar(done, total)
    print(f"  Progress  [{bar}] {pct}%")
    print()
    print(f"  ✅ Completed : {done}")
    print(f"  🔄 Running   : {running}")
    print(f"  ⏳ Pending   : {pending}")
    print(f"  ❌ Failed    : {failed}")
    print(f"  📦 Total     : {total}")

    # ── Cost ───────────────────────────────────────────────────────────────────
    total_cost = sum(t.get("cost_usd", 0.0) or 0.0 for t in tasks)
    if total_cost > 0:
        print(f"\n  💰 Cost so far: ${total_cost:.4f}")

    # ── Failed task details ────────────────────────────────────────────────────
    failed_tasks = [t for t in tasks if t["status"] == "failed"]
    if failed_tasks:
        print("\n  Failed tasks:")
        for t in failed_tasks[:5]:
            desc = (t["description"] or t["plugin_name"])[:60]
            err = (t.get("error_message") or "")[:60]
            print(f"    • {desc}")
            if err:
                print(f"      ↳ {err}")
        if len(failed_tasks) > 5:
            print(f"    … and {len(failed_tasks) - 5} more")

    # ── Next action ────────────────────────────────────────────────────────────
    print()
    if total == 0:
        print("  ➡  Next: claw-forge plan <spec>")
    elif done == total:
        print("  🎉 All tasks completed!")
    elif failed > 0 and pending == 0 and running == 0:
        print("  ➡  Next: claw-forge run   (retry failed tasks)")
    elif running > 0:
        print("  ⚡  Agents are running — check back soon")
        print(f"     claw-forge state   (start REST API on :{_DEFAULT_PORT})")
    else:
        print("  ➡  Next: claw-forge run --concurrency 5")
