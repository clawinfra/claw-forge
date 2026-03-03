"""claw-forge status command — zero-friction project re-entry."""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx
import yaml

_BAR_WIDTH = 12
_PHASE_MAX = 20
_DEFAULT_PORT = 8888
_TIMEOUT = 2.0


def _load_config(config_path: str) -> dict[str, Any]:
    """Load YAML config file, returning raw dict."""
    path = Path(config_path)
    if not path.exists():
        print(f"Config not found: {path}")
        sys.exit(1)
    raw: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    return raw


def _progress_bar(done: int, total: int, width: int = _BAR_WIDTH) -> str:
    """Return a fixed-width progress bar using block chars."""
    if total == 0:
        return "\u2591" * width
    filled = round(width * done / total)
    filled = min(filled, width)
    return "\u2588" * filled + "\u2591" * (width - filled)


def _phase_emoji(done: int, total: int, failed: int) -> str:
    """Pick the status emoji string for a phase row."""
    if failed > 0:
        return "\u274c failed"
    if done == total and total > 0:
        return "\u2705 complete"
    if done > 0:
        return "\U0001f528 building"
    return "\u23f3 queued"


def _format_runtime(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 0:
        seconds = 0
    total_secs = int(seconds)
    minutes = total_secs // 60
    secs = total_secs % 60
    if minutes >= 60:
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}h {mins}m"
    return f"{minutes}m {secs:02d}s"


def _truncate(text: str, max_len: int = _PHASE_MAX) -> str:
    """Truncate text to max_len, pad with spaces."""
    if len(text) > max_len:
        return text[: max_len - 1] + "\u2026"
    return text.ljust(max_len)


def _get(url: str) -> httpx.Response | None:
    """GET with timeout; returns None on connection error."""
    try:
        return httpx.get(url, timeout=_TIMEOUT)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return None


def _print_offline() -> None:
    """Print the offline message."""
    print(
        "State service offline \u2014 "
        "run `claw-forge serve` to start it"
    )


def run_help(  # noqa: C901, PLR0912, PLR0915
    config_path: str = "claw-forge.yaml",
) -> None:
    """Render the claw-forge project status card to stdout."""
    cfg = _load_config(config_path)
    port: int = cfg.get("port", _DEFAULT_PORT)
    base = f"http://localhost:{port}"

    resp = _get(f"{base}/features")
    if resp is None or resp.status_code != 200:
        _print_offline()
        return

    features: list[dict[str, Any]] = resp.json()

    phases: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for feat in features:
        phase_key = feat.get("phase") or ""
        phases[phase_key].append(feat)

    total_features = len(features)
    total_done = sum(
        1 for f in features if f.get("status") == "done"
    )
    total_failed = sum(
        1 for f in features if f.get("status") == "failed"
    )
    total_queued = sum(
        1 for f in features if f.get("status") == "queued"
    )
    phase_count = sum(1 for k in phases if k)

    agent_resp = _get(f"{base}/agent/status")
    agent: dict[str, Any] | None = None
    if agent_resp is not None and agent_resp.status_code == 200:
        agent = agent_resp.json()

    # Header
    print(
        "\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
        "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
        "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
        "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
        "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
        "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
        "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
        "\u2557"
    )
    print(
        "\u2551  claw-forge \u00b7 Project Status"
        "                         \u2551"
    )
    print(
        "\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
        "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
        "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
        "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
        "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
        "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
        "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
        "\u255d"
    )
    print()

    project_name = cfg.get("project", cfg.get("name", ""))
    if project_name:
        print(f"\U0001f4cb Project : {project_name}")

    spec = cfg.get("spec")
    if spec:
        parts = f"{spec}"
        if total_features > 0:
            parts += (
                f" ({total_features} features,"
                f" {phase_count} phases)"
            )
        print(f"\U0001f4c4 Spec    : {parts}")

    model = cfg.get("model")
    if model:
        print(f"\U0001f916 Model   : {model}")

    budget_limit = cfg.get("budget")
    budget_used = cfg.get("budget_used", 0.0)
    if budget_limit is not None:
        print(
            f"\U0001f4b0 Budget  : ${float(budget_used):.2f}"
            f" / ${float(budget_limit):.2f} used"
        )

    print()
    print("Progress")
    print("\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")

    sorted_phases = sorted(
        phases.keys(), key=lambda k: (k == "", k),
    )

    for phase_key in sorted_phases:
        feats = phases[phase_key]
        done = sum(
            1 for f in feats if f.get("status") == "done"
        )
        failed = sum(
            1 for f in feats if f.get("status") == "failed"
        )
        total = len(feats)
        bar = _progress_bar(done, total)
        emoji = _phase_emoji(done, total, failed)
        label = phase_key if phase_key else "(no phase)"
        label_str = _truncate(label)
        count_str = f"{done}/{total}".rjust(7)
        print(f"  {label_str} {bar} {count_str}  {emoji}")

    print()
    print("Agent")
    print("\u2500\u2500\u2500\u2500\u2500")

    if agent is not None:
        status = agent.get("status", "IDLE").upper()
        print(f"  Status  : {status}")
        if status == "ACTIVE":
            working = agent.get(
                "feature", agent.get("working", ""),
            )
            if working:
                print(f'  Working : "{working}"')
            runtime = agent.get("runtime_seconds")
            if runtime is not None:
                print(
                    "  Runtime : "
                    f"{_format_runtime(float(runtime))}"
                )
    else:
        print("  Status  : IDLE")

    print()
    print("Next")
    print("\u2500\u2500\u2500\u2500")
    _print_next_action(
        agent=agent,
        total_features=total_features,
        total_done=total_done,
        total_failed=total_failed,
        total_queued=total_queued,
        phases=phases,
    )


def _find_active_phase(
    phases: dict[str, list[dict[str, Any]]],
) -> tuple[str, int]:
    """Find the in-progress phase and remaining count."""
    sorted_keys = sorted(
        phases.keys(), key=lambda k: (k == "", k),
    )
    for key in sorted_keys:
        feats = phases[key]
        done = sum(
            1 for f in feats if f.get("status") == "done"
        )
        if 0 < done < len(feats):
            remaining = len(feats) - done
            label = key if key else "(no phase)"
            return label, remaining
    for key in sorted_keys:
        feats = phases[key]
        done = sum(
            1 for f in feats if f.get("status") == "done"
        )
        if done < len(feats):
            remaining = len(feats) - done
            label = key if key else "(no phase)"
            return label, remaining
    return "", 0


def _print_next_action(
    *,
    agent: dict[str, Any] | None,
    total_features: int,
    total_done: int,
    total_failed: int,
    total_queued: int,
    phases: dict[str, list[dict[str, Any]]],
) -> None:
    """Print the recommended next action."""
    agent_status = "IDLE"
    if agent is not None:
        agent_status = agent.get("status", "IDLE").upper()

    if agent_status == "ACTIVE":
        phase_label, remaining = _find_active_phase(phases)
        if phase_label:
            print(
                f"  {phase_label} in progress"
                f" \u2014 {remaining} features remaining."
            )
        print(
            "  Run `claw-forge pause` to intervene"
            " or `claw-forge logs` to follow along."
        )
    elif total_failed > 0:
        print(
            f"  {total_failed} features failed."
            " Run `claw-forge retry --failed`"
            " to retry them."
        )
    elif total_done == total_features and total_features > 0:
        print(
            "  \U0001f389 All features complete!"
            " Run `claw-forge build --summary`"
            " for a full report."
        )
    elif total_queued > 0:
        print(
            f"  Agent idle with {total_queued}"
            " features queued."
            " Run `claw-forge run` to start."
        )
    else:
        print(
            "  No features loaded."
            " Run `claw-forge init` first."
        )
