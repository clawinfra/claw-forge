"""Strategic pivot decision support for builder agents.

After each evaluator feedback cycle, the builder must explicitly decide
whether to REFINE the current approach or PIVOT to a different one.

Key insight from Anthropic's research: the generator was instructed to
"make a strategic decision after each evaluation: refine the current
direction if scores were trending well, or pivot to an entirely different
aesthetic if the approach wasn't working."

Rules:
- Score trending down for 2+ consecutive iterations → force PIVOT
- Score trending up → REFINE (continue current direction)
- Score flat but below threshold → REFINE with specific changes
- Score flat and above threshold → APPROVE (done)

Pivot decisions are logged to PLAN.md for traceability.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PivotAction(Enum):
    """Strategic decision after evaluator feedback."""

    REFINE = "refine"   # Continue current direction with improvements
    PIVOT = "pivot"     # Abandon current approach, try something different
    APPROVE = "approve" # Work meets quality bar, no changes needed


@dataclass
class PivotDecision:
    """Record of a strategic pivot/refine decision.

    Attributes
    ----------
    action:
        The strategic decision (REFINE, PIVOT, or APPROVE).
    iteration:
        The iteration number when this decision was made.
    score:
        The evaluator's overall score at decision time.
    score_trend:
        List of recent scores (most recent last).
    reasoning:
        Why this decision was made.
    timestamp:
        When the decision was made.
    """

    action: PivotAction
    iteration: int
    score: float
    score_trend: list[float] = field(default_factory=list)
    reasoning: str = ""
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-friendly dictionary."""
        return {
            "action": self.action.value,
            "iteration": self.iteration,
            "score": round(self.score, 2),
            "score_trend": [round(s, 2) for s in self.score_trend],
            "reasoning": self.reasoning,
            "timestamp": self.timestamp,
        }

    def to_plan_entry(self) -> str:
        """Format as a PLAN.md log entry."""
        trend_str = " → ".join(f"{s:.1f}" for s in self.score_trend)
        return (
            f"### Iteration {self.iteration} — "
            f"{self.action.value.upper()}\n"
            f"- **Score:** {self.score:.1f}/10\n"
            f"- **Trend:** {trend_str}\n"
            f"- **Reasoning:** {self.reasoning}\n"
            f"- **Time:** {self.timestamp}\n"
        )


class PivotTracker:
    """Track evaluator scores and make strategic pivot decisions.

    Parameters
    ----------
    forced_pivot_streak:
        Number of consecutive declining scores before forcing a PIVOT.
        Default is 2 (matching Anthropic's recommendation).
    approval_threshold:
        Score at or above which APPROVE is recommended.
    """

    def __init__(
        self,
        forced_pivot_streak: int = 2,
        approval_threshold: float = 7.0,
    ) -> None:
        self._forced_pivot_streak = max(1, forced_pivot_streak)
        self._approval_threshold = approval_threshold
        self._score_history: list[float] = []
        self._decisions: list[PivotDecision] = []

    @property
    def score_history(self) -> list[float]:
        """All recorded scores (chronological order)."""
        return list(self._score_history)

    @property
    def decisions(self) -> list[PivotDecision]:
        """All recorded decisions (chronological order)."""
        return list(self._decisions)

    @property
    def latest_decision(self) -> PivotDecision | None:
        """Most recent decision, or None if no decisions made yet."""
        return self._decisions[-1] if self._decisions else None

    @property
    def pivot_count(self) -> int:
        """Number of PIVOT decisions made so far."""
        return sum(1 for d in self._decisions if d.action == PivotAction.PIVOT)

    def record_score(self, score: float) -> None:
        """Record a new evaluator score."""
        self._score_history.append(score)

    def decide(self, score: float, iteration: int = 0) -> PivotDecision:
        """Make a strategic decision based on the current score and history.

        Records the score, analyzes the trend, and returns a PivotDecision.

        Decision logic:
        1. Score >= approval_threshold → APPROVE
        2. Consecutive declining scores >= forced_pivot_streak → forced PIVOT
        3. Otherwise → REFINE
        """
        self.record_score(score)

        # Build recent trend (last N+1 scores for N-streak detection)
        window = self._forced_pivot_streak + 1
        recent = self._score_history[-window:]

        # Check for approval
        if score >= self._approval_threshold:
            decision = PivotDecision(
                action=PivotAction.APPROVE,
                iteration=iteration,
                score=score,
                score_trend=list(recent),
                reasoning=(
                    f"Score {score:.1f} meets approval threshold "
                    f"({self._approval_threshold:.1f})"
                ),
            )
            self._decisions.append(decision)
            logger.info(
                "Pivot decision: APPROVE (score %.1f >= %.1f)",
                score, self._approval_threshold,
            )
            return decision

        # Check for forced pivot (declining streak)
        if self._is_declining_streak(recent):
            decision = PivotDecision(
                action=PivotAction.PIVOT,
                iteration=iteration,
                score=score,
                score_trend=list(recent),
                reasoning=(
                    f"Score declining for {self._forced_pivot_streak}+ "
                    f"consecutive iterations ({' → '.join(f'{s:.1f}' for s in recent)}). "
                    f"Current approach is not converging — pivot to a different strategy."
                ),
            )
            self._decisions.append(decision)
            logger.warning(
                "Pivot decision: FORCED PIVOT (declining streak: %s)",
                " → ".join(f"{s:.1f}" for s in recent),
            )
            return decision

        # Default: refine
        if len(recent) >= 2 and recent[-1] > recent[-2]:
            trend_desc = "improving"
        elif len(recent) >= 2 and recent[-1] == recent[-2]:
            trend_desc = "flat"
        else:
            trend_desc = "slightly declining (not yet at forced pivot threshold)"

        decision = PivotDecision(
            action=PivotAction.REFINE,
            iteration=iteration,
            score=score,
            score_trend=list(recent),
            reasoning=(
                f"Score {score:.1f} is below threshold "
                f"({self._approval_threshold:.1f}) but trend is {trend_desc}. "
                f"Continue refining current approach with evaluator feedback."
            ),
        )
        self._decisions.append(decision)
        logger.info(
            "Pivot decision: REFINE (score %.1f, trend: %s)",
            score, trend_desc,
        )
        return decision

    def _is_declining_streak(self, recent: list[float]) -> bool:
        """Check if the most recent scores form a declining streak.

        Returns True if the last ``forced_pivot_streak`` transitions
        are all strictly declining.
        """
        if len(recent) < self._forced_pivot_streak + 1:
            return False

        # Check the last N transitions (N = forced_pivot_streak)
        tail = recent[-(self._forced_pivot_streak + 1):]
        for i in range(len(tail) - 1):
            if tail[i + 1] >= tail[i]:
                return False
        return True

    def log_to_plan(self, plan_path: str | Path) -> None:
        """Append all unlogged decisions to PLAN.md.

        Creates the file if it doesn't exist.  Appends a
        "## Pivot Decision Log" section if not present.
        """
        path = Path(plan_path)

        # Read existing content
        if path.exists():
            existing = path.read_text(encoding="utf-8")
        else:
            existing = "# PLAN.md\n\n"

        # Add header section if missing
        header = "## Pivot Decision Log"
        if header not in existing:
            existing = existing.rstrip() + f"\n\n{header}\n\n"

        # Append new decisions
        new_entries = []
        for decision in self._decisions:
            entry = decision.to_plan_entry()
            # Avoid duplicates by checking if iteration is already logged
            marker = f"### Iteration {decision.iteration}"
            if marker not in existing:
                new_entries.append(entry)

        if new_entries:
            content = existing.rstrip() + "\n\n" + "\n".join(new_entries)
            path.write_text(content + "\n", encoding="utf-8")
            logger.info(
                "Logged %d pivot decision(s) to %s",
                len(new_entries), path,
            )

    def get_status(self) -> dict[str, Any]:
        """Return current pivot tracking status."""
        return {
            "total_iterations": len(self._score_history),
            "score_history": [round(s, 2) for s in self._score_history],
            "pivot_count": self.pivot_count,
            "latest_decision": (
                self.latest_decision.to_dict()
                if self.latest_decision
                else None
            ),
            "forced_pivot_streak": self._forced_pivot_streak,
            "approval_threshold": self._approval_threshold,
        }
