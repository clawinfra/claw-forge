"""Tests for claw_forge.importer.converter — all Claude calls are mocked."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from claw_forge.importer.extractors.base import Epic, ExtractedSpec, Story

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mock_response(text: str) -> MagicMock:
    response = MagicMock()
    response.content = [MagicMock(text=text)]
    return response


def _make_spec(epics: list[Epic] | None = None) -> ExtractedSpec:
    if epics is None:
        epics = [
            Epic(
                name="Authentication",
                stories=[
                    Story(
                        title="User login",
                        acceptance_criteria="Given email+password, returns JWT",
                        phase_hint="Authentication",
                    )
                ],
            ),
            Epic(
                name="Dashboard",
                stories=[
                    Story(
                        title="View stats",
                        acceptance_criteria="Shows active sessions count",
                        phase_hint="Dashboard",
                    )
                ],
            ),
        ]
    return ExtractedSpec(
        project_name="TestApp",
        overview="A test application for unit testing.",
        epics=epics,
        tech_stack_raw="Python + FastAPI + React",
        database_tables_raw="users, sessions",
        api_endpoints_raw="POST /api/auth/login",
        existing_context={},
        integration_points=[],
        constraints=[],
        source_format="bmad",
        source_path=Path("fake.md"),
        epic_count=len(epics),
        story_count=sum(len(e.stories) for e in epics),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestConvertCallCount:
    """Verify exactly 4 + len(epics) calls for a 2-epic spec (= 6 total)."""

    def test_convert_calls_anthropic_four_times(self) -> None:
        spec = _make_spec()  # 2 epics

        call_responses = [
            make_mock_response("<overview>ov</overview><technology_stack>ts</technology_stack><prerequisites>pr</prerequisites>"),
            make_mock_response("<category name=\"Authentication\">• auth bullet</category>"),
            make_mock_response("<category name=\"Dashboard\">• dash bullet</category>"),
            make_mock_response("<database_schema>db</database_schema><api_endpoints_summary>api</api_endpoints_summary>"),
            make_mock_response("<implementation_steps>steps</implementation_steps><success_criteria>sc</success_criteria><ui_layout>ui</ui_layout>"),
        ]

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = call_responses

        with patch("claw_forge.importer.converter.anthropic.Anthropic", return_value=mock_client):
            from claw_forge.importer.converter import convert
            convert(spec, api_key="test-key")

        # 1 (overview+tech) + 2 (epics) + 1 (db+api) + 1 (steps+ui) = 5 calls
        assert mock_client.messages.create.call_count == 5


class TestConvertReturnsSections:
    """Verify all 9 fields of ConvertedSections are non-empty strings."""

    def test_convert_returns_all_sections(self) -> None:
        spec = _make_spec()

        call_responses = [
            make_mock_response(
                "<overview>Overview text</overview>"
                "<technology_stack>Python + FastAPI</technology_stack>"
                "<prerequisites>Docker, Python 3.11</prerequisites>"
            ),
            make_mock_response('<category name="Authentication">• User can login</category>'),
            make_mock_response('<category name="Dashboard">• User can view stats</category>'),
            make_mock_response(
                "<database_schema>users table</database_schema>"
                "<api_endpoints_summary>POST /login</api_endpoints_summary>"
            ),
            make_mock_response(
                "<implementation_steps>Step 1: setup</implementation_steps>"
                "<success_criteria>All tests pass</success_criteria>"
                "<ui_layout>Single page app</ui_layout>"
            ),
        ]

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = call_responses

        with patch("claw_forge.importer.converter.anthropic.Anthropic", return_value=mock_client):
            from claw_forge.importer.converter import ConvertedSections, convert
            result = convert(spec, api_key="test-key")

        assert isinstance(result, ConvertedSections)
        assert result.overview
        assert result.technology_stack
        assert result.prerequisites
        assert result.core_features
        assert result.database_schema
        assert result.api_endpoints
        assert result.implementation_steps
        assert result.success_criteria
        assert result.ui_layout


class TestConvertRetryOnFailure:
    """First call raises APIError; second call succeeds — verify retry once."""

    def test_convert_retries_on_failure(self) -> None:
        spec = _make_spec(epics=[])  # no epics — only 3 calls needed

        success_response = make_mock_response(
            "<overview>ov</overview>"
            "<technology_stack>ts</technology_stack>"
            "<prerequisites>pr</prerequisites>"
        )

        import anthropic as _anthropic

        mock_client = MagicMock()
        # First call raises, second succeeds (for call 1)
        mock_client.messages.create.side_effect = [
            _anthropic.APIError(message="Rate limited", request=MagicMock(), body=None),
            success_response,
            make_mock_response("<database_schema>db</database_schema><api_endpoints_summary>api</api_endpoints_summary>"),
            make_mock_response("<implementation_steps>steps</implementation_steps><success_criteria>sc</success_criteria><ui_layout>ui</ui_layout>"),
        ]

        with patch("claw_forge.importer.converter.anthropic.Anthropic", return_value=mock_client):
            from claw_forge.importer.converter import convert
            result = convert(spec, api_key="test-key")

        # 2 calls for call-1 (retry) + 1 for db/api + 1 for steps = 4 total
        assert mock_client.messages.create.call_count == 4
        assert result.overview


class TestCoreFeaturesAccumulation:
    """2 epics → core_features contains both category blocks."""

    def test_core_features_accumulates_all_epics(self) -> None:
        spec = _make_spec()  # 2 epics: Authentication + Dashboard

        call_responses = [
            make_mock_response("<overview>ov</overview><technology_stack>ts</technology_stack><prerequisites>pr</prerequisites>"),
            make_mock_response('<category name="Authentication">• auth bullet</category>'),
            make_mock_response('<category name="Dashboard">• dash bullet</category>'),
            make_mock_response("<database_schema>db</database_schema><api_endpoints_summary>api</api_endpoints_summary>"),
            make_mock_response("<implementation_steps>steps</implementation_steps><success_criteria>sc</success_criteria><ui_layout>ui</ui_layout>"),
        ]

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = call_responses

        with patch("claw_forge.importer.converter.anthropic.Anthropic", return_value=mock_client):
            from claw_forge.importer.converter import convert
            result = convert(spec, api_key="test-key")

        assert "Authentication" in result.core_features
        assert "Dashboard" in result.core_features


class TestConvertEmptyEpics:
    """Spec with no epics → core_features == ''; other sections still populated."""

    def test_convert_with_empty_epics(self) -> None:
        spec = _make_spec(epics=[])  # no epics

        call_responses = [
            make_mock_response("<overview>ov</overview><technology_stack>ts</technology_stack><prerequisites>pr</prerequisites>"),
            make_mock_response("<database_schema>db</database_schema><api_endpoints_summary>api</api_endpoints_summary>"),
            make_mock_response("<implementation_steps>steps</implementation_steps><success_criteria>sc</success_criteria><ui_layout>ui</ui_layout>"),
        ]

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = call_responses

        with patch("claw_forge.importer.converter.anthropic.Anthropic", return_value=mock_client):
            from claw_forge.importer.converter import convert
            result = convert(spec, api_key="test-key")

        assert result.core_features == ""
        assert result.overview
        assert result.database_schema
        assert result.implementation_steps
        # total calls: 3 (no epic calls)
        assert mock_client.messages.create.call_count == 3
