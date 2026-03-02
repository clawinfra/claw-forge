"""claw-forge status command — zero-friction project re-entry."""

from __future__ import annotations

import sys
from typing import Any

import httpx

from claw_forge.config import ConfigError, load_config

_BAR_WIDTH = 12
_PHASE_MAX = 20
_DEFAULT_PORT = 8888


# ── Pure helpers ──────────────────────────────────────────────────────────────


def _progress_bar(done: int, total: int, width: int = _BAR_WIDTH) -> str:
    """Return a ``width``-char progress bar using █ / ░."""
    if total == 0:
        return "░" * width
    filled = round(width * done / total)
    return "█" * filled + "░" * (width - filled)


def _phase_emoji(done: int, total: int, failed: int) -> str:
    """Return a phase status emoji + label based on counts."""
    if failed:
        return "❌ failed"
    if total > 0 and done == total:
        return "✅ complete"
    if done > 0:
        return "🔨 building"
    return "⏳ queued"


def _format_runtime(seconds: int) -> str:
    """Format a duration (seconds) to a human-readable string.

    Negative → "0m 00s".  Hours → "Xh Ym".  Minutes → "Xm YYs".
    """
    if seconds < 0:
        seconds = 0
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m {s:02d}s"


def _truncate(text: str, width: int) -> str:
    """Return ``text`` padded to ``width``, or truncated with '…' if too long."""
    if len(text) > width:
        return text[: width - 1] + "…"
    return text.ljust(width)


# ── HTTP helpers ──────────────────────────────────────────────────────────────


def _fetch_features(port: int) -> list[dict[str, Any]] | None:
    """Return features list, or None if the service is offline / errored."""
    try:
        resp = httpx.get(f"http://localhost:{port}/features", timeout=2)
        if not resp.is_success:
            return None
        return resp.json()  # type: ignore[no-any-return]
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.TimeoutException):
        return None


def _fetch_agent_status(port: int) -> dict[str, Any]:
    """Return agent status dict; empty dict (→ IDLE) on 404 or any error."""
    try:
        resp = httpx.get(f"http://localhost:{port}/agent/status", timeout=2)
        if resp.status_code == 404:
            return {}
        if resp.is_success:
            return resp.json()  # type: ignore[no-any-return]
        return {}
    except Exception:  # noqa: BLE001
        return {}


# ── Main entry point ──────────────────────────────────────────────────────────


def run_help(config_path: str = "claw-forge.yaml") -> None:  # noqa: C901, PLR0912, PLR0915
    """Render the claw-forge project status card to stdout."""
    # ── 1. Load config ──────────────────────────────────────────────────────
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        print(f"❌ {exc}")
        sys.exit(1)

    port: int = int(cfg.get("port", _DEFAULT_PORT))

    # ── 2. Fetch features ───────────────────────────────────────────────────
    features = _fetch_features(port)
    if features is None:
        print("⚠️  State service offline — start it with `claw-forge serve`.")
        return

    # ── 3. Group by phase ───────────────────────────────────────────────────
    phase_order: list[str] = []
    phase_features: dict[str, list[dict[str, Any]]] = {}
    for f in features:
        raw_phase: str = f.get("phase") or ""
        phase = raw_phase if raw_phase else "(no phase)"
        if phase not in phase_features:
            phase_features[phase] = []
            phase_order.append(phase)
        phase_features[phase].append(f)

    # ── 4. Fetch agent status ───────────────────────────────────────────────
    agent = _fetch_agent_status(port)

    # ── 5. Render card ──────────────────────────────────────────────────────
    print("╔══════════════════════════════════════════════════════╗")
    print("║  claw-forge · Project Status                         ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()

    project_name: str = cfg.get("project", "")
    if project_name:
        print(f"📋 Project : {project_name}")

    spec_file: str = cfg.get("spec", "") or ""
    if spec_file:
        n_features = len(features)
        n_phases = len([p for p in phase_order if p != "(no phase)"])
        print(f"📄 Spec    : {spec_file} ({n_features} features, {n_phases} phases)")

    model: str = cfg.get("model", "")
    if model:
        print(f"🤖 Model   : {model}")

    budget_limit = cfg.get("budget")
    budget_used = cfg.get("budget_used")
    if budget_limit is not None and budget_used is not None:
        print(f"💰 Budget  : ${float(budget_used):.2f} / ${float(budget_limit):.2f} used")

    # ── Progress ─────────────────────────────────────────────────────────────
    print()
    print("Progress")
    print("────────")

    if not features:
        print("  No features loaded.")
    else:
        for phase in phase_order:
            feats = phase_features[phase]
            statuses = [f.get("status", "queued") for f in feats]
            n_done = sum(1 for s in statuses if s in ("done", "completed"))
            n_failed = sum(1 for s in statuses if s == "failed")
            total = len(feats)
            bar = _progress_bar(n_done, total)
            icon = _phase_emoji(n_done, total, n_failed)
            label = _truncate(phase, _PHASE_MAX)
            print(f"  {label}  {bar}  {n_done}/{total}  {icon}")

    # ── Agent ────────────────────────────────────────────────────────────────
    agent_status: str = agent.get("status", "IDLE")
    print()
    print("Agent")
    print("─────")
    print(f"  Status  : {agent_status}")
    working: str = agent.get("feature", "")
    if working:
        print(f'  Working : "{working}"')
    runtime_secs: int | None = agent.get("runtime_seconds")
    if runtime_secs is not None:
        print(f"  Runtime : {_format_runtime(int(runtime_secs))}")

    # ── Next ─────────────────────────────────────────────────────────────────
    print()
    print("Next")
    print("────")

    all_statuses = [f.get("status", "queued") for f in features]
    total_failed = sum(1 for s in all_statuses if s == "failed")
    total_done = sum(1 for s in all_statuses if s in ("done", "completed"))
    total_queued = sum(1 for s in all_statuses if s in ("queued", "pending"))
    total_building = sum(1 for s in all_statuses if s in ("building", "running"))

    agent_active = agent_status.upper() == "ACTIVE"

    if agent_active and (total_building or total_queued):
        # find active phase
        active_phase = ""
        remaining = 0
        for phase in phase_order:
            feats = phase_features[phase]
            ps = [f.get("status", "queued") for f in feats]
            if any(s in ("building", "running") for s in ps):
                active_phase = phase
                remaining = sum(1 for s in ps if s not in ("done", "completed", "failed"))
                break
        if active_phase and active_phase != "(no phase)":
            print(f"  {active_phase} in progress — {remaining} features remaining.")
        else:
            print(f"  {remaining} features in progress.")
        print("  Run `claw-forge pause` to intervene or `claw-forge logs` to follow along.")
    elif total_failed:
        print(f"  {total_failed} features failed. Run `claw-forge retry --failed` to retry them.")
    elif features and total_done == len(features):
        print("  🎉 All features complete! Run `claw-forge build --summary` for a full report.")
    elif not agent_active and total_queued:
        print(f"  Agent idle with {total_queued} features queued. Run `claw-forge run` to start.")
    else:
        print("  Nothing to do.")
