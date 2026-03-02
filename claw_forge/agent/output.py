"""Structured output helpers for claw-forge agent sessions.

Provides pre-built JSON Schema output format configs for common coding-agent
response types. Pass these as ``output_format`` to ``run_agent()`` or
``ClaudeAgentOptions`` to get structured, machine-parseable responses.

Usage::

    from claw_forge.agent.output import FEATURE_SUMMARY_SCHEMA, CODE_REVIEW_SCHEMA
    from claw_forge.agent import run_agent

    result = await collect_structured_result(
        prompt="Review the code in src/",
        output_format=CODE_REVIEW_SCHEMA,
    )
    # result is a dict with keys: verdict, blockers, suggestions, security_issues
"""
from __future__ import annotations

from typing import Any


# ── Output schemas ────────────────────────────────────────────────────────────

FEATURE_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "features_implemented": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Names/IDs of features implemented this session",
            },
            "tests_passing": {
                "type": "integer",
                "description": "Number of tests currently passing",
            },
            "files_modified": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Relative paths of files created or modified",
            },
            "blockers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Issues blocking completion",
            },
        },
        "required": ["features_implemented", "tests_passing", "files_modified", "blockers"],
        "additionalProperties": False,
    },
}

CODE_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["approve", "request_changes", "block"],
                "description": "Overall review verdict",
            },
            "blockers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Issues that must be fixed before merge",
            },
            "suggestions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Non-blocking improvement suggestions",
            },
            "security_issues": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Security vulnerabilities found",
            },
        },
        "required": ["verdict", "blockers", "suggestions", "security_issues"],
        "additionalProperties": False,
    },
}

PLAN_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "order": {"type": "integer"},
                        "description": {"type": "string"},
                        "files": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["order", "description", "files"],
                },
                "description": "Ordered implementation steps",
            },
            "estimated_complexity": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "Overall task complexity estimate",
            },
            "risks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Identified risks that may affect the plan",
            },
        },
        "required": ["steps", "estimated_complexity", "risks"],
        "additionalProperties": False,
    },
}

# All schemas in one place for easy enumeration / testing
ALL_SCHEMAS: dict[str, dict[str, Any]] = {
    "feature_summary": FEATURE_SUMMARY_SCHEMA,
    "code_review": CODE_REVIEW_SCHEMA,
    "plan": PLAN_SCHEMA,
}
