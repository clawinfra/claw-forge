"""Tests for Anthropic harness improvements.

Covers:
- Context reset manager and HANDOFF.md schema
- Adversarial evaluator with weighted grading dimensions
- Pivot decision tracker with declining streak detection
- Reviewer plugin adversarial mode integration
"""

from __future__ import annotations

import json
from pathlib import Path

from claw_forge.harness.adversarial_evaluator import (
    APPROVAL_THRESHOLD,
    AdversarialEvaluator,
    DimensionScore,
    EvaluationResult,
    GradingDimension,
)
from claw_forge.harness.context_reset import (
    ContextResetManager,
    HandoffArtifact,
)
from claw_forge.harness.pivot_decision import (
    PivotAction,
    PivotDecision,
    PivotTracker,
)

# ══════════════════════════════════════════════════════════════════════════
# Context Reset Tests
# ══════════════════════════════════════════════════════════════════════════


class TestHandoffArtifact:
    """Tests for the HandoffArtifact dataclass."""

    def test_empty_artifact_to_markdown(self) -> None:
        artifact = HandoffArtifact()
        md = artifact.to_markdown()
        assert "# HANDOFF.md" in md
        assert "(none yet)" in md
        assert "(initial state)" in md
        assert "Not yet evaluated" in md

    def test_populated_artifact_to_markdown(self) -> None:
        artifact = HandoffArtifact(
            completed=["feat: auth module (abc123)", "feat: database schema (def456)"],
            state=["src/auth.py — 150 lines", "tests/test_auth.py — 95% coverage"],
            next_steps=["Implement rate limiting", "Add API docs"],
            decisions_made=["Using SQLite over Postgres for simplicity"],
            quality_bar="Score: 6.5/10 — needs rate limiting and error handling",
            iteration_number=3,
            total_tool_calls=240,
        )
        md = artifact.to_markdown()
        assert "abc123" in md
        assert "Iteration:** 3" in md
        assert "240" in md
        assert "rate limiting" in md.lower()
        assert "SQLite over Postgres" in md

    def test_roundtrip_markdown(self) -> None:
        """to_markdown → from_markdown preserves content."""
        original = HandoffArtifact(
            completed=["item one", "item two"],
            state=["file A exists", "file B modified"],
            next_steps=["step 1", "step 2", "step 3"],
            decisions_made=["decision alpha"],
            quality_bar="7/10 — solid",
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

    def test_from_markdown_empty(self) -> None:
        artifact = HandoffArtifact.from_markdown("")
        assert artifact.completed == []
        assert artifact.state == []
        assert artifact.next_steps == []

    def test_from_markdown_malformed(self) -> None:
        """Handles malformed markdown gracefully."""
        artifact = HandoffArtifact.from_markdown("just some random text\nno sections here\n")
        assert artifact.completed == []
        assert artifact.iteration_number == 0


class TestContextResetManager:
    """Tests for the ContextResetManager."""

    def test_init_defaults(self, tmp_path: Path) -> None:
        mgr = ContextResetManager(tmp_path)
        assert mgr.threshold == 80
        assert mgr.tool_call_count == 0
        assert mgr.total_tool_calls == 0
        assert mgr.iteration == 0

    def test_threshold_clamped(self, tmp_path: Path) -> None:
        mgr = ContextResetManager(tmp_path, threshold=5)
        assert mgr.threshold == 10  # minimum 10

    def test_record_tool_calls(self, tmp_path: Path) -> None:
        mgr = ContextResetManager(tmp_path, threshold=3)
        # threshold is clamped to 10 minimum
        assert mgr.threshold == 10
        for _ in range(9):
            assert mgr.record_tool_call() is False
        assert mgr.record_tool_call() is True  # 10th call triggers
        assert mgr.tool_call_count == 10

    def test_save_and_load_handoff(self, tmp_path: Path) -> None:
        mgr = ContextResetManager(tmp_path, threshold=10)
        handoff = HandoffArtifact(
            completed=["feature A done"],
            next_steps=["implement feature B"],
        )

        path = mgr.save_handoff(handoff)
        assert path.exists()
        assert path.name == "HANDOFF.md"
        assert mgr.iteration == 1
        assert mgr.tool_call_count == 0  # reset after save

        # Load in a fresh manager
        mgr2 = ContextResetManager(tmp_path)
        loaded = mgr2.load_handoff()
        assert loaded is not None
        assert loaded.completed == ["feature A done"]
        assert loaded.next_steps == ["implement feature B"]
        assert loaded.iteration_number == 1

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        mgr = ContextResetManager(tmp_path)
        assert mgr.load_handoff() is None

    def test_build_reset_prompt(self, tmp_path: Path) -> None:
        mgr = ContextResetManager(tmp_path)
        handoff = HandoffArtifact(
            completed=["task 1"],
            next_steps=["task 2"],
            iteration_number=1,
            total_tool_calls=80,
        )
        prompt = mgr.build_reset_prompt(handoff)
        assert "context reset" in prompt.lower()
        assert "Do NOT revisit decisions" in prompt
        assert "HANDOFF.md" in prompt

    def test_get_status(self, tmp_path: Path) -> None:
        mgr = ContextResetManager(tmp_path, threshold=50)
        mgr.record_tool_call()
        status = mgr.get_status()
        assert status["iteration"] == 0
        assert status["tool_calls_current"] == 1
        assert status["threshold"] == 50
        assert status["needs_reset"] is False
        assert status["handoff_exists"] is False

    def test_handoff_path(self, tmp_path: Path) -> None:
        mgr = ContextResetManager(tmp_path)
        assert mgr.handoff_path == tmp_path / "HANDOFF.md"

    def test_multiple_iterations(self, tmp_path: Path) -> None:
        """Simulate two context resets."""
        mgr = ContextResetManager(tmp_path, threshold=10)

        # First iteration
        for _ in range(10):
            mgr.record_tool_call()
        mgr.save_handoff(HandoffArtifact(completed=["A"]))
        assert mgr.iteration == 1
        assert mgr.total_tool_calls == 10

        # Second iteration
        for _ in range(10):
            mgr.record_tool_call()
        mgr.save_handoff(HandoffArtifact(completed=["A", "B"]))
        assert mgr.iteration == 2
        assert mgr.total_tool_calls == 20


# ══════════════════════════════════════════════════════════════════════════
# Adversarial Evaluator Tests
# ══════════════════════════════════════════════════════════════════════════


class TestGradingDimension:
    """Tests for the GradingDimension enum."""

    def test_all_dimensions(self) -> None:
        dims = list(GradingDimension)
        assert len(dims) == 4
        labels = [d.label for d in dims]
        assert "correctness" in labels
        assert "completeness" in labels
        assert "quality" in labels
        assert "originality" in labels

    def test_weights(self) -> None:
        assert GradingDimension.CORRECTNESS.weight == 3
        assert GradingDimension.COMPLETENESS.weight == 3
        assert GradingDimension.QUALITY.weight == 2
        assert GradingDimension.ORIGINALITY.weight == 1

    def test_total_weight(self) -> None:
        assert GradingDimension.total_weight() == 9


class TestDimensionScore:
    """Tests for the DimensionScore dataclass."""

    def test_weighted_score(self) -> None:
        ds = DimensionScore(dimension="correctness", score=8.0, weight=3)
        assert ds.weighted_score == 24.0

    def test_weighted_score_with_reasoning(self) -> None:
        ds = DimensionScore(
            dimension="quality", score=6.5, weight=2,
            reasoning="Good structure but some duplication"
        )
        assert ds.weighted_score == 13.0


class TestEvaluationResult:
    """Tests for the EvaluationResult dataclass."""

    def test_empty_overall_score(self) -> None:
        result = EvaluationResult()
        assert result.overall_score == 0.0

    def test_overall_score_calculation(self) -> None:
        result = EvaluationResult(
            dimension_scores=[
                DimensionScore("correctness", 8.0, 3),
                DimensionScore("completeness", 6.0, 3),
                DimensionScore("quality", 7.0, 2),
                DimensionScore("originality", 5.0, 1),
            ]
        )
        # (8*3 + 6*3 + 7*2 + 5*1) / (3+3+2+1) = (24+18+14+5)/9 = 61/9 ≈ 6.78
        assert abs(result.overall_score - 6.78) < 0.1

    def test_to_dict(self) -> None:
        result = EvaluationResult(
            dimension_scores=[
                DimensionScore("correctness", 9.0, 3),
            ],
            findings=["🔴 BLOCKING: test failure"],
            verdict="request_changes",
            summary="Needs fixes",
            iteration=2,
        )
        d = result.to_dict()
        assert d["overall_score"] == 9.0
        assert d["verdict"] == "request_changes"
        assert d["iteration"] == 2
        assert len(d["dimensions"]) == 1
        assert len(d["findings"]) == 1

    def test_to_markdown(self) -> None:
        result = EvaluationResult(
            dimension_scores=[
                DimensionScore("correctness", 7.0, 3, "Mostly correct"),
                DimensionScore("quality", 8.0, 2, "Clean code"),
            ],
            findings=["🟡 Minor issue found"],
            verdict="approve",
            summary="Good work overall",
            iteration=5,
        )
        md = result.to_markdown()
        assert "Iteration 5" in md
        assert "APPROVE" in md
        assert "Correctness" in md
        assert "Quality" in md
        assert "Minor issue" in md


class TestAdversarialEvaluator:
    """Tests for the AdversarialEvaluator class."""

    def test_default_init(self) -> None:
        ev = AdversarialEvaluator()
        assert ev.approval_threshold == APPROVAL_THRESHOLD
        assert len(ev.dimensions) == 4

    def test_custom_threshold(self) -> None:
        ev = AdversarialEvaluator(approval_threshold=8.0)
        assert ev.approval_threshold == 8.0

    def test_get_system_prompt(self) -> None:
        ev = AdversarialEvaluator()
        prompt = ev.get_system_prompt()
        assert "adversarial" in prompt.lower()
        assert "optimism bias" in prompt.lower()
        assert "GOOD" in prompt
        assert "BAD" in prompt
        assert "correctness" in prompt.lower()
        assert "JSON" in prompt

    def test_evaluate_from_scores_approve(self) -> None:
        ev = AdversarialEvaluator(approval_threshold=7.0)
        result = ev.evaluate_from_scores(
            scores={"correctness": 8, "completeness": 8, "quality": 7, "originality": 6},
            findings=["✅ Well tested"],
            summary="Solid implementation",
        )
        assert result.verdict == "approve"
        assert result.overall_score >= 7.0
        assert len(result.dimension_scores) == 4

    def test_evaluate_from_scores_reject(self) -> None:
        ev = AdversarialEvaluator(approval_threshold=7.0)
        result = ev.evaluate_from_scores(
            scores={"correctness": 4, "completeness": 3, "quality": 5, "originality": 2},
        )
        assert result.verdict == "request_changes"
        assert result.overall_score < 7.0

    def test_score_clamping(self) -> None:
        ev = AdversarialEvaluator()
        result = ev.evaluate_from_scores(
            scores={"correctness": 15, "quality": -5},  # out of range
        )
        for ds in result.dimension_scores:
            assert 1.0 <= ds.score <= 10.0

    def test_missing_dimensions_default_to_5(self) -> None:
        ev = AdversarialEvaluator()
        result = ev.evaluate_from_scores(scores={"correctness": 9})
        # Other dimensions should default to 5.0
        scores_by_dim = {ds.dimension: ds.score for ds in result.dimension_scores}
        assert scores_by_dim["correctness"] == 9.0
        assert scores_by_dim["completeness"] == 5.0
        assert scores_by_dim["quality"] == 5.0
        assert scores_by_dim["originality"] == 5.0

    def test_parse_llm_response_valid_json(self) -> None:
        ev = AdversarialEvaluator()
        response = json.dumps({
            "dimensions": [
                {"dimension": "correctness", "score": 7, "reasoning": "Good"},
                {"dimension": "completeness", "score": 6, "reasoning": "Missing auth"},
                {"dimension": "quality", "score": 8, "reasoning": "Clean"},
                {"dimension": "originality", "score": 5, "reasoning": "Standard"},
            ],
            "findings": ["🔴 Missing auth flow"],
            "summary": "Needs auth implementation",
        })
        result = ev.parse_llm_response(response, iteration=3)
        assert result.iteration == 3
        assert len(result.dimension_scores) == 4
        assert "Missing auth" in result.findings[0]

    def test_parse_llm_response_with_markdown_fences(self) -> None:
        ev = AdversarialEvaluator()
        response = '```json\n{"dimensions": [], "findings": [], "summary": "ok"}\n```'
        result = ev.parse_llm_response(response)
        assert result.summary == "ok"

    def test_parse_llm_response_invalid_json(self) -> None:
        ev = AdversarialEvaluator()
        result = ev.parse_llm_response("this is not json at all")
        assert "parse error" in result.findings[0].lower()

    def test_should_approve(self) -> None:
        ev = AdversarialEvaluator(approval_threshold=7.0)
        good = EvaluationResult(
            dimension_scores=[DimensionScore("correctness", 9.0, 3)]
        )
        bad = EvaluationResult(
            dimension_scores=[DimensionScore("correctness", 4.0, 3)]
        )
        assert ev.should_approve(good) is True
        assert ev.should_approve(bad) is False


# ══════════════════════════════════════════════════════════════════════════
# Pivot Decision Tests
# ══════════════════════════════════════════════════════════════════════════


class TestPivotDecision:
    """Tests for the PivotDecision dataclass."""

    def test_to_dict(self) -> None:
        d = PivotDecision(
            action=PivotAction.PIVOT,
            iteration=3,
            score=5.5,
            score_trend=[7.0, 6.0, 5.5],
            reasoning="Declining scores",
        )
        result = d.to_dict()
        assert result["action"] == "pivot"
        assert result["iteration"] == 3
        assert result["score"] == 5.5
        assert len(result["score_trend"]) == 3

    def test_to_plan_entry(self) -> None:
        d = PivotDecision(
            action=PivotAction.REFINE,
            iteration=2,
            score=6.0,
            score_trend=[5.0, 6.0],
            reasoning="Improving",
        )
        entry = d.to_plan_entry()
        assert "Iteration 2" in entry
        assert "REFINE" in entry
        assert "6.0" in entry
        assert "5.0 → 6.0" in entry

    def test_auto_timestamp(self) -> None:
        d = PivotDecision(
            action=PivotAction.APPROVE, iteration=1, score=8.0,
        )
        assert d.timestamp  # auto-set

    def test_custom_timestamp(self) -> None:
        d = PivotDecision(
            action=PivotAction.APPROVE, iteration=1, score=8.0,
            timestamp="2026-03-28T00:00:00Z",
        )
        assert d.timestamp == "2026-03-28T00:00:00Z"


class TestPivotTracker:
    """Tests for the PivotTracker class."""

    def test_default_init(self) -> None:
        tracker = PivotTracker()
        assert tracker.score_history == []
        assert tracker.decisions == []
        assert tracker.latest_decision is None
        assert tracker.pivot_count == 0

    def test_approve_on_high_score(self) -> None:
        tracker = PivotTracker(approval_threshold=7.0)
        decision = tracker.decide(8.0, iteration=1)
        assert decision.action == PivotAction.APPROVE
        assert "meets approval threshold" in decision.reasoning

    def test_refine_on_improving(self) -> None:
        tracker = PivotTracker(approval_threshold=7.0)
        tracker.decide(4.0, iteration=1)  # first score
        decision = tracker.decide(5.0, iteration=2)  # improving
        assert decision.action == PivotAction.REFINE
        assert "improving" in decision.reasoning.lower() or "refine" in decision.reasoning.lower()

    def test_forced_pivot_on_declining_streak(self) -> None:
        tracker = PivotTracker(forced_pivot_streak=2, approval_threshold=7.0)
        tracker.decide(6.0, iteration=1)
        tracker.decide(5.0, iteration=2)  # declining
        decision = tracker.decide(4.0, iteration=3)  # 2 consecutive declines
        assert decision.action == PivotAction.PIVOT
        assert "declining" in decision.reasoning.lower()

    def test_no_forced_pivot_if_streak_broken(self) -> None:
        tracker = PivotTracker(forced_pivot_streak=2, approval_threshold=7.0)
        tracker.decide(6.0, iteration=1)
        tracker.decide(5.0, iteration=2)  # decline
        tracker.decide(5.5, iteration=3)  # improvement breaks streak
        decision = tracker.decide(5.0, iteration=4)  # decline but only 1 consecutive
        assert decision.action == PivotAction.REFINE

    def test_pivot_count(self) -> None:
        tracker = PivotTracker(forced_pivot_streak=2, approval_threshold=9.0)
        tracker.decide(6.0, iteration=1)
        tracker.decide(5.0, iteration=2)
        tracker.decide(4.0, iteration=3)  # first pivot
        assert tracker.pivot_count == 1

    def test_score_history(self) -> None:
        tracker = PivotTracker()
        tracker.decide(5.0)
        tracker.decide(6.0)
        tracker.decide(7.0)
        assert tracker.score_history == [5.0, 6.0, 7.0]

    def test_record_score(self) -> None:
        tracker = PivotTracker()
        tracker.record_score(5.5)
        tracker.record_score(6.5)
        assert tracker.score_history == [5.5, 6.5]

    def test_decisions_list(self) -> None:
        tracker = PivotTracker(approval_threshold=7.0)
        tracker.decide(5.0, iteration=1)
        tracker.decide(8.0, iteration=2)
        assert len(tracker.decisions) == 2
        assert tracker.decisions[0].action == PivotAction.REFINE
        assert tracker.decisions[1].action == PivotAction.APPROVE

    def test_latest_decision(self) -> None:
        tracker = PivotTracker()
        assert tracker.latest_decision is None
        tracker.decide(5.0, iteration=1)
        assert tracker.latest_decision is not None
        assert tracker.latest_decision.iteration == 1

    def test_flat_score_refines(self) -> None:
        tracker = PivotTracker(approval_threshold=7.0)
        tracker.decide(5.0, iteration=1)
        decision = tracker.decide(5.0, iteration=2)  # flat
        assert decision.action == PivotAction.REFINE
        assert "flat" in decision.reasoning.lower()

    def test_log_to_plan_creates_file(self, tmp_path: Path) -> None:
        tracker = PivotTracker()
        tracker.decide(5.0, iteration=1)
        tracker.decide(4.0, iteration=2)

        plan_path = tmp_path / "PLAN.md"
        tracker.log_to_plan(plan_path)

        assert plan_path.exists()
        content = plan_path.read_text()
        assert "Pivot Decision Log" in content
        assert "Iteration 1" in content
        assert "Iteration 2" in content

    def test_log_to_plan_appends(self, tmp_path: Path) -> None:
        plan_path = tmp_path / "PLAN.md"
        plan_path.write_text("# PLAN.md\n\nExisting content\n")

        tracker = PivotTracker()
        tracker.decide(6.0, iteration=1)
        tracker.log_to_plan(plan_path)

        content = plan_path.read_text()
        assert "Existing content" in content
        assert "Iteration 1" in content

    def test_log_to_plan_no_duplicates(self, tmp_path: Path) -> None:
        plan_path = tmp_path / "PLAN.md"
        tracker = PivotTracker()
        tracker.decide(5.0, iteration=1)

        tracker.log_to_plan(plan_path)
        tracker.log_to_plan(plan_path)  # second call should not duplicate

        content = plan_path.read_text()
        assert content.count("Iteration 1") == 1

    def test_get_status(self) -> None:
        tracker = PivotTracker(forced_pivot_streak=3, approval_threshold=8.0)
        tracker.decide(5.0, iteration=1)
        status = tracker.get_status()
        assert status["total_iterations"] == 1
        assert status["score_history"] == [5.0]
        assert status["pivot_count"] == 0
        assert status["forced_pivot_streak"] == 3
        assert status["approval_threshold"] == 8.0
        assert status["latest_decision"]["action"] == "refine"

    def test_forced_pivot_streak_clamped(self) -> None:
        tracker = PivotTracker(forced_pivot_streak=0)
        assert tracker._forced_pivot_streak == 1

    def test_declining_streak_insufficient_history(self) -> None:
        """Not enough history for a streak → should REFINE, not PIVOT."""
        tracker = PivotTracker(forced_pivot_streak=3, approval_threshold=9.0)
        decision = tracker.decide(5.0, iteration=1)  # only 1 score
        assert decision.action == PivotAction.REFINE

    def test_single_decline_not_pivot(self) -> None:
        """One declining score is not a streak."""
        tracker = PivotTracker(forced_pivot_streak=2, approval_threshold=9.0)
        tracker.decide(6.0, iteration=1)
        decision = tracker.decide(5.0, iteration=2)  # one decline
        assert decision.action == PivotAction.REFINE


# ══════════════════════════════════════════════════════════════════════════
# Reviewer Plugin Adversarial Mode Tests
# ══════════════════════════════════════════════════════════════════════════


class TestReviewerAdversarialMode:
    """Tests for the reviewer plugin's adversarial mode."""

    def test_standard_mode_prompt(self) -> None:
        from claw_forge.plugins.base import PluginContext
        from claw_forge.plugins.reviewer import ReviewerPlugin

        plugin = ReviewerPlugin()
        ctx = PluginContext(
            project_path="/tmp/test",
            session_id="s1",
            task_id="t1",
        )
        prompt = plugin.get_system_prompt(ctx)
        assert "senior software engineer" in prompt
        assert "adversarial" not in prompt.lower()

    def test_adversarial_mode_prompt(self) -> None:
        from claw_forge.plugins.base import PluginContext
        from claw_forge.plugins.reviewer import ReviewerPlugin

        plugin = ReviewerPlugin()
        ctx = PluginContext(
            project_path="/tmp/test",
            session_id="s1",
            task_id="t1",
            config={"adversarial": True},
        )
        prompt = plugin.get_system_prompt(ctx)
        assert "adversarial" in prompt.lower()
        assert "optimism bias" in prompt.lower()

    def test_is_adversarial_false_by_default(self) -> None:
        from claw_forge.plugins.base import PluginContext
        from claw_forge.plugins.reviewer import ReviewerPlugin

        plugin = ReviewerPlugin()
        ctx = PluginContext(
            project_path="/tmp", session_id="s1", task_id="t1",
        )
        assert plugin._is_adversarial(ctx) is False

    def test_is_adversarial_true_when_set(self) -> None:
        from claw_forge.plugins.base import PluginContext
        from claw_forge.plugins.reviewer import ReviewerPlugin

        plugin = ReviewerPlugin()
        ctx = PluginContext(
            project_path="/tmp", session_id="s1", task_id="t1",
            config={"adversarial": True},
        )
        assert plugin._is_adversarial(ctx) is True


# ══════════════════════════════════════════════════════════════════════════
# Coding Plugin Context Reset Integration Tests
# ══════════════════════════════════════════════════════════════════════════


class TestCodingPluginContextReset:
    """Tests for context reset integration in the coding plugin."""

    def test_coding_plugin_loads_handoff(self, tmp_path: Path) -> None:
        """CodingPlugin loads HANDOFF.md when it exists."""
        # Write a HANDOFF.md
        handoff = HandoffArtifact(
            completed=["feat: setup"],
            next_steps=["implement core logic"],
            iteration_number=1,
            total_tool_calls=80,
        )
        (tmp_path / "HANDOFF.md").write_text(handoff.to_markdown())

        from claw_forge.plugins.base import PluginContext
        from claw_forge.plugins.coding import CodingPlugin

        plugin = CodingPlugin()
        ctx = PluginContext(
            project_path=str(tmp_path),
            session_id="s1",
            task_id="t1",
        )
        # Just verify the prompt building works (actual execution needs mocking)
        prompt = plugin._build_prompt(ctx)
        assert str(tmp_path) in prompt


# ══════════════════════════════════════════════════════════════════════════
# Integration: Full Evaluator → Pivot loop
# ══════════════════════════════════════════════════════════════════════════


class TestEvaluatorPivotIntegration:
    """Integration test: adversarial evaluator feeds into pivot tracker."""

    def test_evaluation_to_pivot_approve_flow(self) -> None:
        evaluator = AdversarialEvaluator(approval_threshold=7.0)
        tracker = PivotTracker(approval_threshold=7.0)

        # Simulate an evaluation
        result = evaluator.evaluate_from_scores(
            scores={"correctness": 8, "completeness": 7, "quality": 8, "originality": 6},
            iteration=1,
        )
        assert result.verdict == "approve"

        # Feed score to pivot tracker
        decision = tracker.decide(result.overall_score, iteration=1)
        assert decision.action == PivotAction.APPROVE

    def test_evaluation_to_pivot_refine_flow(self) -> None:
        evaluator = AdversarialEvaluator(approval_threshold=7.0)
        tracker = PivotTracker(approval_threshold=7.0)

        result = evaluator.evaluate_from_scores(
            scores={"correctness": 5, "completeness": 4, "quality": 5, "originality": 3},
            iteration=1,
        )
        assert result.verdict == "request_changes"

        decision = tracker.decide(result.overall_score, iteration=1)
        assert decision.action == PivotAction.REFINE

    def test_evaluation_to_pivot_forced_pivot_flow(self, tmp_path: Path) -> None:
        evaluator = AdversarialEvaluator(approval_threshold=7.0)
        tracker = PivotTracker(forced_pivot_streak=2, approval_threshold=7.0)

        # Three declining scores
        for i, scores in enumerate([
            {"correctness": 6, "completeness": 6, "quality": 6, "originality": 6},
            {"correctness": 5, "completeness": 5, "quality": 5, "originality": 5},
            {"correctness": 4, "completeness": 4, "quality": 4, "originality": 4},
        ]):
            result = evaluator.evaluate_from_scores(scores=scores, iteration=i + 1)
            decision = tracker.decide(result.overall_score, iteration=i + 1)

        assert decision.action == PivotAction.PIVOT

        # Log to PLAN.md
        plan_path = tmp_path / "PLAN.md"
        tracker.log_to_plan(plan_path)
        content = plan_path.read_text()
        assert "PIVOT" in content
        assert "declining" in content.lower()


# ══════════════════════════════════════════════════════════════════════════
# Module import tests
# ══════════════════════════════════════════════════════════════════════════


class TestHarnessModuleImports:
    """Verify the harness module exports are accessible."""

    def test_import_from_harness(self) -> None:
        from claw_forge.harness import (
            AdversarialEvaluator,
            ContextResetManager,
            EvaluationResult,
            GradingDimension,
            HandoffArtifact,
            PivotDecision,
            PivotTracker,
        )
        assert AdversarialEvaluator is not None
        assert ContextResetManager is not None
        assert EvaluationResult is not None
        assert GradingDimension is not None
        assert HandoffArtifact is not None
        assert PivotDecision is not None
        assert PivotTracker is not None
