"""Tests for the HandoffArtifact standalone module."""

from __future__ import annotations

from pathlib import Path

from claw_forge.harness.handoff import HandoffArtifact


class TestHandoffArtifactEmpty:
    """Tests for empty/default HandoffArtifact."""

    def test_defaults(self) -> None:
        artifact = HandoffArtifact()
        assert artifact.completed == []
        assert artifact.state == []
        assert artifact.next_steps == []
        assert artifact.decisions_made == []
        assert artifact.quality_bar == ""
        assert artifact.iteration_number == 0
        assert artifact.total_tool_calls == 0

    def test_to_markdown_empty(self) -> None:
        artifact = HandoffArtifact()
        md = artifact.to_markdown()
        assert "# HANDOFF.md" in md
        assert "**Iteration:** 0" in md
        assert "**Total Tool Calls:** 0" in md
        assert "(none yet)" in md
        assert "(initial state)" in md
        assert "Not yet evaluated" in md

    def test_from_markdown_empty_string(self) -> None:
        artifact = HandoffArtifact.from_markdown("")
        assert artifact.completed == []
        assert artifact.state == []
        assert artifact.next_steps == []


class TestHandoffArtifactPopulated:
    """Tests for populated HandoffArtifact."""

    def test_populated_to_markdown(self) -> None:
        artifact = HandoffArtifact(
            completed=[
                "feat: auth module (abc123)",
                "feat: database schema (def456)",
            ],
            state=[
                "src/auth.py — 150 lines",
                "tests/test_auth.py — 95% coverage",
            ],
            next_steps=[
                "Implement rate limiting",
                "Add API docs",
            ],
            decisions_made=[
                "Using SQLite over Postgres for simplicity",
            ],
            quality_bar="Score: 6.5/10 — needs rate limiting and error handling",
            iteration_number=3,
            total_tool_calls=240,
        )
        md = artifact.to_markdown()
        assert "abc123" in md
        assert "def456" in md
        assert "**Iteration:** 3" in md
        assert "**Total Tool Calls:** 240" in md
        assert "rate limiting" in md.lower()
        assert "SQLite over Postgres" in md
        assert "6.5/10" in md

    def test_roundtrip_full(self) -> None:
        """Round-trip: to_markdown → from_markdown preserves all fields."""
        original = HandoffArtifact(
            completed=[
                "feat: auth flow",
                "feat: user CRUD",
            ],
            state=[
                "src/models/user.py exists",
                "src/auth.py — JWT implemented",
            ],
            next_steps=[
                "Add rate limiting",
                "Write integration tests",
            ],
            decisions_made=[
                "Use python-jose for JWT",
                "SQLite for local dev",
            ],
            quality_bar="7/10 — solid, needs tests",
            iteration_number=2,
            total_tool_calls=160,
        )
        md = original.to_markdown()
        parsed = HandoffArtifact.from_markdown(md)

        assert parsed.completed == original.completed
        assert parsed.state == original.state
        assert parsed.next_steps == original.next_steps
        assert parsed.decisions_made == original.decisions_made
        assert "7/10" in parsed.quality_bar
        assert parsed.iteration_number == 2
        assert parsed.total_tool_calls == 160


class TestHandoffArtifactParsing:
    """Tests for parsing HANDOFF.md format."""

    def test_parse_completed_section(self) -> None:
        md = """
        # HANDOFF.md — Builder Context Reset

        **Iteration:** 1
        **Total Tool Calls:** 80

        ## Completed
        - feat: auth module
        - feat: database setup

        ## State
        - src/ exists

        ## Next Steps
        1. Add tests
        2. Write docs

        ## Decisions Made
        - Using FastAPI

        ## Quality Bar
        - 8/10 — good work
        """
        artifact = HandoffArtifact.from_markdown(md)
        assert len(artifact.completed) == 2
        assert "feat: auth module" in artifact.completed
        assert "feat: database setup" in artifact.completed

    def test_parse_state_section(self) -> None:
        md = """
        ## State
        - src/auth.py — 100 lines
        - tests/ directory created
        """
        artifact = HandoffArtifact.from_markdown(md)
        assert len(artifact.state) == 2
        assert "src/auth.py" in artifact.state[0]

    def test_parse_next_steps_numbered(self) -> None:
        md = """
        ## Next Steps
        1. First step
        2. Second step
        3. Third step
        """
        artifact = HandoffArtifact.from_markdown(md)
        assert artifact.next_steps == ["First step", "Second step", "Third step"]

    def test_parse_next_steps_bullets(self) -> None:
        """Also handles bullet-style next steps."""
        md = """
        ## Next Steps
        - First step
        - Second step
        - Third step
        """
        artifact = HandoffArtifact.from_markdown(md)
        assert artifact.next_steps == ["First step", "Second step", "Third step"]

    def test_parse_decisions_made(self) -> None:
        md = """
        ## Decisions Made
        - Use SQLite
        - Adopt TDD
        """
        artifact = HandoffArtifact.from_markdown(md)
        assert len(artifact.decisions_made) == 2
        assert "Use SQLite" in artifact.decisions_made

    def test_parse_quality_bar(self) -> None:
        md = """
        ## Quality Bar
        7/10 — solid work, needs more tests
        """
        artifact = HandoffArtifact.from_markdown(md)
        assert "7/10" in artifact.quality_bar
        assert "solid work" in artifact.quality_bar

    def test_parse_quality_bar_multiline(self) -> None:
        """Quality bar with multiple lines is concatenated."""
        md = """
        ## Quality Bar
        Score: 7/10
        Coverage: 85%
        Needs: error handling
        """
        artifact = HandoffArtifact.from_markdown(md)
        assert "7/10" in artifact.quality_bar
        assert "85%" in artifact.quality_bar
        assert "error handling" in artifact.quality_bar

    def test_parse_iteration_metadata(self) -> None:
        md = """
        **Iteration:** 5
        **Total Tool Calls:** 420
        """
        artifact = HandoffArtifact.from_markdown(md)
        assert artifact.iteration_number == 5
        assert artifact.total_tool_calls == 420

    def test_ignore_placeholder_values(self) -> None:
        md = """
        ## Completed
        - (none yet)

        ## State
        - (initial state)

        ## Next Steps
        1. (review plan and begin implementation)

        ## Decisions Made
        - (no decisions recorded yet)

        ## Quality Bar
        - Not yet evaluated
        """
        artifact = HandoffArtifact.from_markdown(md)
        assert artifact.completed == []
        assert artifact.state == []
        assert artifact.next_steps == []
        assert artifact.decisions_made == []
        assert artifact.quality_bar == ""

    def test_malformed_graceful_handling(self) -> None:
        """Handles malformed markdown gracefully."""
        artifact = HandoffArtifact.from_markdown(
            "just some random text\nno sections here\n"
        )
        assert artifact.completed == []
        assert artifact.state == []
        assert artifact.iteration_number == 0

    def test_malformed_iteration_number(self) -> None:
        """Bad iteration number defaults to 0."""
        md = "**Iteration:** not_a_number\n"
        artifact = HandoffArtifact.from_markdown(md)
        assert artifact.iteration_number == 0

    def test_malformed_tool_calls(self) -> None:
        """Bad tool call count defaults to 0."""
        md = "**Total Tool Calls:** bad_value\n"
        artifact = HandoffArtifact.from_markdown(md)
        assert artifact.total_tool_calls == 0

    def test_strips_bullet_markers(self) -> None:
        """Strips leading `- ` and `* ` from list items."""
        md = """
        ## Completed
        - item one
        * item two
        """
        artifact = HandoffArtifact.from_markdown(md)
        assert artifact.completed == ["item one", "item two"]

    def test_strips_number_markers(self) -> None:
        """Strips leading `1. `, `2. ` from list items."""
        md = """
        ## Next Steps
        1. step one
        2. step two
        999. step with big number
        """
        artifact = HandoffArtifact.from_markdown(md)
        assert artifact.next_steps == ["step one", "step two", "step with big number"]

