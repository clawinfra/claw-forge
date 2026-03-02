"""Tests for structured output schemas and thinking config."""
from __future__ import annotations

import pytest

from claw_forge.agent.output import (
    ALL_SCHEMAS,
    CODE_REVIEW_SCHEMA,
    FEATURE_SUMMARY_SCHEMA,
    PLAN_SCHEMA,
)
from claw_forge.agent.thinking import (
    ADAPTIVE_THINKING,
    DEEP_THINKING,
    NO_THINKING,
    thinking_for_task,
)


# ---------------------------------------------------------------------------
# Structured output schemas
# ---------------------------------------------------------------------------


class TestFeatureSummarySchema:
    def test_type_is_json_schema(self):
        assert FEATURE_SUMMARY_SCHEMA["type"] == "json_schema"

    def test_has_required_fields(self):
        required = FEATURE_SUMMARY_SCHEMA["schema"]["required"]
        assert "features_implemented" in required
        assert "tests_passing" in required
        assert "files_modified" in required
        assert "blockers" in required

    def test_properties_exist(self):
        props = FEATURE_SUMMARY_SCHEMA["schema"]["properties"]
        assert "features_implemented" in props
        assert "tests_passing" in props
        assert "files_modified" in props
        assert "blockers" in props

    def test_features_implemented_is_array(self):
        props = FEATURE_SUMMARY_SCHEMA["schema"]["properties"]
        assert props["features_implemented"]["type"] == "array"

    def test_tests_passing_is_integer(self):
        props = FEATURE_SUMMARY_SCHEMA["schema"]["properties"]
        assert props["tests_passing"]["type"] == "integer"


class TestCodeReviewSchema:
    def test_type_is_json_schema(self):
        assert CODE_REVIEW_SCHEMA["type"] == "json_schema"

    def test_has_required_fields(self):
        required = CODE_REVIEW_SCHEMA["schema"]["required"]
        assert "verdict" in required
        assert "blockers" in required
        assert "suggestions" in required
        assert "security_issues" in required

    def test_verdict_is_enum(self):
        verdict = CODE_REVIEW_SCHEMA["schema"]["properties"]["verdict"]
        assert verdict["type"] == "string"
        assert set(verdict["enum"]) == {"approve", "request_changes", "block"}

    def test_all_arrays_have_string_items(self):
        props = CODE_REVIEW_SCHEMA["schema"]["properties"]
        for key in ("blockers", "suggestions", "security_issues"):
            assert props[key]["type"] == "array"
            assert props[key]["items"]["type"] == "string"


class TestPlanSchema:
    def test_type_is_json_schema(self):
        assert PLAN_SCHEMA["type"] == "json_schema"

    def test_has_required_fields(self):
        required = PLAN_SCHEMA["schema"]["required"]
        assert "steps" in required
        assert "estimated_complexity" in required
        assert "risks" in required

    def test_estimated_complexity_is_enum(self):
        ec = PLAN_SCHEMA["schema"]["properties"]["estimated_complexity"]
        assert set(ec["enum"]) == {"low", "medium", "high"}

    def test_steps_items_have_required_fields(self):
        step_schema = PLAN_SCHEMA["schema"]["properties"]["steps"]["items"]
        assert "order" in step_schema["properties"]
        assert "description" in step_schema["properties"]
        assert "files" in step_schema["properties"]


class TestAllSchemas:
    def test_contains_all_three(self):
        assert "feature_summary" in ALL_SCHEMAS
        assert "code_review" in ALL_SCHEMAS
        assert "plan" in ALL_SCHEMAS

    def test_all_have_json_schema_type(self):
        for name, schema in ALL_SCHEMAS.items():
            assert schema["type"] == "json_schema", f"{name} missing json_schema type"


# ---------------------------------------------------------------------------
# Thinking config presets (TypedDicts — dict access)
# ---------------------------------------------------------------------------


class TestThinkingPresets:
    def test_deep_thinking_is_enabled(self):
        assert DEEP_THINKING["type"] == "enabled"
        assert DEEP_THINKING["budget_tokens"] == 20_000

    def test_adaptive_thinking_is_adaptive(self):
        assert ADAPTIVE_THINKING["type"] == "adaptive"

    def test_no_thinking_is_disabled(self):
        assert NO_THINKING["type"] == "disabled"


class TestThinkingForTask:
    def test_planning_returns_deep(self):
        assert thinking_for_task("planning") is DEEP_THINKING

    def test_architecture_returns_deep(self):
        assert thinking_for_task("architecture") is DEEP_THINKING

    def test_review_returns_adaptive(self):
        assert thinking_for_task("review") is ADAPTIVE_THINKING

    def test_coding_returns_adaptive(self):
        assert thinking_for_task("coding") is ADAPTIVE_THINKING

    def test_testing_returns_no_thinking(self):
        assert thinking_for_task("testing") is NO_THINKING

    def test_monitoring_returns_no_thinking(self):
        assert thinking_for_task("monitoring") is NO_THINKING

    def test_unknown_returns_adaptive(self):
        assert thinking_for_task("random-type") is ADAPTIVE_THINKING

    def test_empty_string_returns_adaptive(self):
        assert thinking_for_task("") is ADAPTIVE_THINKING
