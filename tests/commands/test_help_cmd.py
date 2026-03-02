"""Tests for the status (help_cmd) command."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import yaml

from claw_forge.commands.help_cmd import (
    _format_runtime,
    _phase_emoji,
    _progress_bar,
    _truncate,
    run_help,
)

# ── Helpers ──────────────────────────────────────────────────────────────


def _write_config(
    tmp: str,
    *,
    project: str = "TaskFlow API",
    spec: str | None = "app_spec.xml",
    model: str | None = "claude-sonnet-4-6",
    budget: float | None = 5.00,
    budget_used: float | None = 1.23,
    port: int = 8888,
) -> str:
    """Write a claw-forge.yaml and return its path."""
    cfg: dict = {"port": port}
    if project:
        cfg["project"] = project
    if spec:
        cfg["spec"] = spec
    if model:
        cfg["model"] = model
    if budget is not None:
        cfg["budget"] = budget
    if budget_used is not None:
        cfg["budget_used"] = budget_used
    path = os.path.join(tmp, "claw-forge.yaml")
    Path(path).write_text(yaml.dump(cfg))
    return path


def _make_features(
    phase_map: dict[str, dict[str, int]],
) -> list[dict]:
    """Build feature list from {phase: {status: count}}."""
    features: list[dict] = []
    idx = 0
    for phase, statuses in phase_map.items():
        for status, count in statuses.items():
            for _ in range(count):
                feat: dict = {
                    "id": idx,
                    "name": f"feat-{idx}",
                    "status": status,
                    "phase": phase,
                }
                features.append(feat)
                idx += 1
    return features


def _mock_get_factory(
    features: list[dict] | None = None,
    agent: dict | None = None,
    port: int = 8888,
):
    """Return a side_effect callable for httpx.get."""
    def _side_effect(url: str, **kwargs):  # type: ignore[no-untyped-def]
        if url == f"http://localhost:{port}/features":
            resp = httpx.Response(200, json=features or [])
            return resp
        if url == f"http://localhost:{port}/agent/status":
            if agent is None:
                return httpx.Response(404, json={})
            return httpx.Response(200, json=agent)
        return httpx.Response(404, json={})
    return _side_effect


# ── Unit tests for helper functions ──────────────────────────────────────


class TestProgressBar:
    def test_empty(self) -> None:
        assert _progress_bar(0, 10) == "░░░░░░░░░░░░"

    def test_half(self) -> None:
        bar = _progress_bar(6, 12)
        assert bar == "██████░░░░░░"

    def test_full(self) -> None:
        assert _progress_bar(12, 12) == "████████████"

    def test_zero_total(self) -> None:
        assert _progress_bar(0, 0) == "░░░░░░░░░░░░"

    def test_custom_width(self) -> None:
        bar = _progress_bar(5, 10, width=10)
        assert len(bar) == 10
        assert bar.count("█") == 5
        assert bar.count("░") == 5


class TestPhaseEmoji:
    def test_complete(self) -> None:
        assert "✅" in _phase_emoji(10, 10, 0)

    def test_building(self) -> None:
        assert "🔨" in _phase_emoji(5, 10, 0)

    def test_queued(self) -> None:
        assert "⏳" in _phase_emoji(0, 10, 0)

    def test_failed(self) -> None:
        assert "❌" in _phase_emoji(5, 10, 2)


class TestFormatRuntime:
    def test_minutes_and_seconds(self) -> None:
        assert _format_runtime(272) == "4m 32s"

    def test_hours(self) -> None:
        assert _format_runtime(3720) == "1h 2m"

    def test_zero(self) -> None:
        assert _format_runtime(0) == "0m 00s"

    def test_negative_clamped(self) -> None:
        assert _format_runtime(-5) == "0m 00s"


class TestTruncate:
    def test_short_padded(self) -> None:
        result = _truncate("Auth", 20)
        assert result.startswith("Auth")
        assert len(result) == 20

    def test_long_truncated(self) -> None:
        result = _truncate("A" * 30, 20)
        assert len(result) == 20
        assert result.endswith("…")

    def test_exact_length(self) -> None:
        result = _truncate("A" * 20, 20)
        assert len(result) == 20
        assert "…" not in result


# ── Integration tests for run_help ───────────────────────────────────────


class TestHappyPath:
    """State service online, 3 phases, mixed statuses."""

    def test_renders_full_card(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        features = _make_features({
            "Phase 1 · Auth": {"done": 12},
            "Phase 2 · Projects": {"done": 8, "building": 4},
            "Phase 3 · Collab": {"queued": 15},
        })
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _write_config(tmp)
            with patch(
                "claw_forge.commands.help_cmd.httpx.get",
                side_effect=_mock_get_factory(
                    features=features,
                    agent={
                        "status": "ACTIVE",
                        "feature": "User can invite collaborators",
                        "runtime_seconds": 272,
                    },
                ),
            ):
                run_help(config_path=cfg_path)

        out = capsys.readouterr().out
        assert "claw-forge · Project Status" in out
        assert "TaskFlow API" in out
        assert "app_spec.xml" in out
        assert "claude-sonnet-4-6" in out
        assert "$1.23 / $5.00" in out
        assert "Phase 1 · Auth" in out
        assert "12/12" in out
        assert "✅ complete" in out
        assert "Phase 2 · Projects" in out
        assert "🔨 building" in out
        assert "Phase 3 · Collab" in out
        assert "⏳ queued" in out
        assert "ACTIVE" in out
        assert "User can invite collaborators" in out
        assert "4m 32s" in out
        assert "claw-forge pause" in out


class TestNoPhasesAllUnphased:
    """All features unphased → renders '(no phase)' group."""

    def test_unphased(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        features = _make_features({"": {"done": 3, "queued": 6}})
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _write_config(tmp)
            with patch(
                "claw_forge.commands.help_cmd.httpx.get",
                side_effect=_mock_get_factory(features=features),
            ):
                run_help(config_path=cfg_path)

        out = capsys.readouterr().out
        assert "(no phase)" in out
        assert "3/9" in out


class TestStateServiceOffline:
    """State service offline → graceful message, exit 0."""

    def test_offline_message(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _write_config(tmp)
            with patch(
                "claw_forge.commands.help_cmd.httpx.get",
                side_effect=httpx.ConnectError("refused"),
            ):
                run_help(config_path=cfg_path)

        out = capsys.readouterr().out
        assert "State service offline" in out
        assert "claw-forge serve" in out


class TestAllFeaturesDone:
    """All features done → shows completion message."""

    def test_completion(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        features = _make_features({
            "Phase 1": {"done": 10},
            "Phase 2": {"done": 5},
        })
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _write_config(tmp)
            with patch(
                "claw_forge.commands.help_cmd.httpx.get",
                side_effect=_mock_get_factory(features=features),
            ):
                run_help(config_path=cfg_path)

        out = capsys.readouterr().out
        assert "🎉 All features complete!" in out
        assert "claw-forge build --summary" in out


class TestFailedFeatures:
    """Failed features → shows retry recommendation."""

    def test_retry_recommendation(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        features = _make_features({
            "Phase 1": {"done": 8, "failed": 2},
        })
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _write_config(tmp)
            with patch(
                "claw_forge.commands.help_cmd.httpx.get",
                side_effect=_mock_get_factory(features=features),
            ):
                run_help(config_path=cfg_path)

        out = capsys.readouterr().out
        assert "2 features failed" in out
        assert "claw-forge retry --failed" in out


class TestAgentActive:
    """Agent active → shows runtime and working feature."""

    def test_agent_runtime(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        features = _make_features({
            "Phase 1": {"done": 2, "building": 3},
        })
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _write_config(tmp)
            with patch(
                "claw_forge.commands.help_cmd.httpx.get",
                side_effect=_mock_get_factory(
                    features=features,
                    agent={
                        "status": "ACTIVE",
                        "feature": "OAuth integration",
                        "runtime_seconds": 120,
                    },
                ),
            ):
                run_help(config_path=cfg_path)

        out = capsys.readouterr().out
        assert "ACTIVE" in out
        assert "OAuth integration" in out
        assert "2m 00s" in out


class TestAgentIdle:
    """Agent idle → shows 'run claw-forge run'."""

    def test_idle_with_queued(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        features = _make_features({"Phase 1": {"queued": 10}})
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _write_config(tmp)
            with patch(
                "claw_forge.commands.help_cmd.httpx.get",
                side_effect=_mock_get_factory(
                    features=features,
                    agent={"status": "IDLE"},
                ),
            ):
                run_help(config_path=cfg_path)

        out = capsys.readouterr().out
        assert "Agent idle with 10 features queued" in out
        assert "claw-forge run" in out


class TestBudgetOmitted:
    """No budget configured → omit budget line."""

    def test_no_budget_line(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        features = _make_features({"Phase 1": {"queued": 5}})
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _write_config(
                tmp, budget=None, budget_used=None,
            )
            with patch(
                "claw_forge.commands.help_cmd.httpx.get",
                side_effect=_mock_get_factory(features=features),
            ):
                run_help(config_path=cfg_path)

        out = capsys.readouterr().out
        assert "Budget" not in out


class TestSpecOmitted:
    """Spec file missing from config → omit spec line."""

    def test_no_spec_line(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        features = _make_features({"Phase 1": {"queued": 5}})
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _write_config(tmp, spec=None)
            with patch(
                "claw_forge.commands.help_cmd.httpx.get",
                side_effect=_mock_get_factory(features=features),
            ):
                run_help(config_path=cfg_path)

        out = capsys.readouterr().out
        assert "Spec" not in out


class TestCustomPort:
    """Port from config is respected in HTTP calls."""

    def test_port_9999(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        features = _make_features({"Phase 1": {"done": 3}})
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _write_config(tmp, port=9999)
            with patch(
                "claw_forge.commands.help_cmd.httpx.get",
                side_effect=_mock_get_factory(
                    features=features, port=9999,
                ),
            ):
                run_help(config_path=cfg_path)

        out = capsys.readouterr().out
        assert "Phase 1" in out


class TestConfigNotFound:
    """Config file not found → sys.exit(1)."""

    def test_missing_config_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            run_help(
                config_path="/nonexistent/claw-forge.yaml",
            )
        assert exc_info.value.code == 1


class TestNoFeaturesLoaded:
    """Empty features list → 'No features loaded' hint."""

    def test_empty_features(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _write_config(tmp)
            with patch(
                "claw_forge.commands.help_cmd.httpx.get",
                side_effect=_mock_get_factory(features=[]),
            ):
                run_help(config_path=cfg_path)

        out = capsys.readouterr().out
        assert "No features loaded" in out


class TestAgentEndpoint404:
    """Agent endpoint returns 404 → shows IDLE."""

    def test_agent_not_found(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        features = _make_features({"Phase 1": {"queued": 3}})
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _write_config(tmp)
            with patch(
                "claw_forge.commands.help_cmd.httpx.get",
                side_effect=_mock_get_factory(
                    features=features, agent=None,
                ),
            ):
                run_help(config_path=cfg_path)

        out = capsys.readouterr().out
        assert "IDLE" in out


class TestFeaturesEndpointError:
    """Features endpoint returns non-200 → offline message."""

    def test_features_500(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        def _side_effect(url: str, **kwargs):  # type: ignore[no-untyped-def]
            if "/features" in url:
                return httpx.Response(
                    500, json={"error": "oops"},
                )
            return httpx.Response(404, json={})

        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _write_config(tmp)
            with patch(
                "claw_forge.commands.help_cmd.httpx.get",
                side_effect=_side_effect,
            ):
                run_help(config_path=cfg_path)

        out = capsys.readouterr().out
        assert "State service offline" in out


class TestConnectTimeout:
    """Connection timeout → offline message."""

    def test_timeout_offline(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _write_config(tmp)
            with patch(
                "claw_forge.commands.help_cmd.httpx.get",
                side_effect=httpx.ConnectTimeout(
                    "timed out",
                ),
            ):
                run_help(config_path=cfg_path)

        out = capsys.readouterr().out
        assert "State service offline" in out
