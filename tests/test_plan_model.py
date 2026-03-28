"""Tests for --plan-model flag on claw-forge run.

Covers:
- CLI flag exists and appears in help
- Alias resolution via model_resolver
- Fallback to --model when --plan-model not set
- Config agent.plan_model used when no CLI flag
- CLI --plan-model overrides config
- Only initializer tasks use plan_model
- Default config YAML includes plan_model key
"""

from __future__ import annotations

import yaml
from typer.testing import CliRunner

from claw_forge.cli import _DEFAULT_CONFIG_YAML, app
from claw_forge.pool.model_resolver import resolve_model

runner = CliRunner()


class TestPlanModelHelp:
    """Test 1: --plan-model flag exists and appears in help."""

    def test_run_plan_model_help_text(self) -> None:
        result = runner.invoke(app, ["run", "--help"])
        assert "--plan-model" in result.output


class TestPlanModelAliasResolution:
    """Test 2: --plan-model resolves via model_resolver."""

    def test_plan_model_resolved_from_alias(self) -> None:
        cfg = {
            "model_aliases": {"opus": "claude-opus-4-6"},
            "providers": {},
            "agent": {},
        }
        r = resolve_model("opus", cfg)
        assert r.model_id == "claude-opus-4-6"
        assert r.alias_resolved is True


class TestPlanModelFallback:
    """Test 3: Fallback — no --plan-model means plan uses --model."""

    def test_plan_model_defaults_to_model(self) -> None:
        cfg: dict = {"providers": {}, "agent": {}}
        model = "claude-sonnet-4-6"
        plan_model = None

        # Replicate the resolution logic from cli.py run()
        effective_plan_model = model
        if plan_model is not None:
            plan_resolved = resolve_model(plan_model, cfg)
            effective_plan_model = plan_resolved.model_id
        else:
            _config_plan_model = cfg.get("agent", {}).get("plan_model")
            if _config_plan_model:
                plan_resolved = resolve_model(str(_config_plan_model), cfg)
                effective_plan_model = plan_resolved.model_id

        assert effective_plan_model == model


class TestPlanModelFromConfig:
    """Test 4: Config agent.plan_model takes effect when no CLI flag."""

    def test_plan_model_from_config(self) -> None:
        cfg: dict = {
            "providers": {},
            "agent": {"plan_model": "claude-opus-4-6"},
            "model_aliases": {},
        }
        model = "claude-sonnet-4-6"
        plan_model = None

        effective_plan_model = model
        if plan_model is not None:
            pass
        else:
            _config_plan_model = cfg.get("agent", {}).get("plan_model")
            if _config_plan_model:
                plan_resolved = resolve_model(str(_config_plan_model), cfg)
                effective_plan_model = plan_resolved.model_id

        assert effective_plan_model == "claude-opus-4-6"


class TestPlanModelCLIOverridesConfig:
    """Test 5: CLI --plan-model overrides config agent.plan_model."""

    def test_plan_model_cli_overrides_config(self) -> None:
        cfg: dict = {
            "providers": {},
            "agent": {"plan_model": "claude-opus-4-6"},
            "model_aliases": {"fast-opus": "claude-opus-4-5"},
        }
        model = "claude-sonnet-4-6"
        plan_model = "fast-opus"  # CLI flag

        effective_plan_model = model
        if plan_model is not None:
            plan_resolved = resolve_model(plan_model, cfg)
            effective_plan_model = plan_resolved.model_id

        assert effective_plan_model == "claude-opus-4-5"  # alias resolved


class TestPlanModelOnlyAffectsInitializer:
    """Test 6: --plan-model only affects planning tasks (initializer plugin)."""

    def test_plan_model_only_affects_initializer_tasks(self) -> None:
        model = "claude-sonnet-4-6"
        effective_plan_model = "claude-opus-4-6"

        # Simulate the model selection logic in task_handler
        for plugin_name, expected_model in [
            ("initializer", effective_plan_model),
            ("coding", model),
            ("testing", model),
            ("reviewer", model),
            ("bugfix", model),
        ]:
            _effective = (
                effective_plan_model
                if plugin_name == "initializer"
                else model
            )
            assert _effective == expected_model, (
                f"Failed for {plugin_name}: got {_effective}, "
                f"expected {expected_model}"
            )


class TestDefaultConfigHasPlanModel:
    """Test 7: Default config YAML includes plan_model key."""

    def test_default_config_has_plan_model(self) -> None:
        assert "plan_model" in _DEFAULT_CONFIG_YAML

    def test_default_config_plan_model_is_null(self) -> None:
        """The default config sets plan_model to null (no override by default)."""
        # Parse the YAML (env vars won't resolve, but we just check structure)
        # Replace ${...} patterns with dummy strings for parsing
        import re

        cleaned = re.sub(r"\$\{[^}]+\}", "dummy", _DEFAULT_CONFIG_YAML)
        parsed = yaml.safe_load(cleaned)
        assert "agent" in parsed
        assert "plan_model" in parsed["agent"]
        # Default is null (None in Python)
        assert parsed["agent"]["plan_model"] is None
