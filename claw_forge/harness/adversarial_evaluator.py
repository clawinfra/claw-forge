"""Adversarial evaluator for code review and quality assessment.

Implements the Generator/Evaluator separation pattern from Anthropic's
harness design research.  Key findings:

1. Self-evaluation is unreliable — agents confidently praise their own
   mediocre work, even when quality is obviously poor.
2. Separating generator from evaluator creates a feedback loop that
   drives quality improvement.
3. Tuning a standalone evaluator to be skeptical is far more tractable
   than making a generator critical of its own work.
4. The evaluator should use explicit grading criteria with weighted
   dimensions and few-shot calibration examples.
5. The evaluator should actively exercise the work (not just read code)
   before scoring.

This module provides:
- ``GradingDimension``: A weighted scoring dimension.
- ``EvaluationResult``: Structured output from an adversarial review.
- ``AdversarialEvaluator``: The evaluator that produces adversarial
  reviews using explicit criteria and few-shot examples.
"""

from __future__ import annotations

import json
import logging
import textwrap
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# Score threshold: below this → request changes; at or above → approve
APPROVAL_THRESHOLD = 7.0


class GradingDimension(Enum):
    """Grading dimensions with weights.

    Weights are inspired by Anthropic's frontend design experiment:
    - Correctness and Completeness are weighted highest (×3) because
      code that doesn't work or is missing features is a hard failure.
    - Quality is weighted moderately (×2) because maintainability and
      architecture matter but are secondary to correctness.
    - Originality is weighted lowest (×1) because novel approaches
      are nice but not required for production code.

    The weights sum to 9, so a perfect score of 10 on all dimensions
    produces a weighted average of 10.0.
    """

    CORRECTNESS = ("correctness", 3)
    COMPLETENESS = ("completeness", 3)
    QUALITY = ("quality", 2)
    ORIGINALITY = ("originality", 1)

    def __init__(self, label: str, weight: int) -> None:
        self.label = label
        self.weight = weight

    @classmethod
    def total_weight(cls) -> int:
        """Sum of all dimension weights."""
        return sum(d.weight for d in cls)


@dataclass
class DimensionScore:
    """Score for a single grading dimension."""

    dimension: str
    score: float  # 1-10
    weight: int
    reasoning: str = ""

    @property
    def weighted_score(self) -> float:
        """Score multiplied by weight."""
        return self.score * self.weight


@dataclass
class EvaluationResult:
    """Structured output from an adversarial evaluation.

    Contains per-dimension scores, an overall weighted score,
    a verdict (approve/request_changes), and detailed findings.
    """

    dimension_scores: list[DimensionScore] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    verdict: str = "request_changes"  # "approve" or "request_changes"
    summary: str = ""
    iteration: int = 0

    @property
    def overall_score(self) -> float:
        """Weighted average score across all dimensions.

        Returns 0.0 if no scores are present.
        """
        if not self.dimension_scores:
            return 0.0
        total_weighted = sum(s.weighted_score for s in self.dimension_scores)
        total_weight = sum(s.weight for s in self.dimension_scores)
        if total_weight == 0:
            return 0.0
        return total_weighted / total_weight

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-friendly dictionary."""
        return {
            "overall_score": round(self.overall_score, 2),
            "verdict": self.verdict,
            "summary": self.summary,
            "iteration": self.iteration,
            "dimensions": [
                {
                    "dimension": s.dimension,
                    "score": s.score,
                    "weight": s.weight,
                    "weighted_score": round(s.weighted_score, 2),
                    "reasoning": s.reasoning,
                }
                for s in self.dimension_scores
            ],
            "findings": self.findings,
        }

    def to_markdown(self) -> str:
        """Render the evaluation as a markdown review."""
        lines: list[str] = [
            f"# Adversarial Review — Iteration {self.iteration}\n",
            f"**Overall Score:** {self.overall_score:.1f}/10",
            f"**Verdict:** {self.verdict.upper()}\n",
        ]

        if self.summary:
            lines.append(f"## Summary\n{self.summary}\n")

        lines.append("## Dimension Scores\n")
        lines.append("| Dimension | Score | Weight | Weighted |")
        lines.append("|-----------|-------|--------|----------|")
        for s in self.dimension_scores:
            lines.append(
                f"| {s.dimension.capitalize()} | {s.score:.1f} | ×{s.weight} | "
                f"{s.weighted_score:.1f} |"
            )

        if self.findings:
            lines.append("\n## Findings\n")
            for i, finding in enumerate(self.findings, 1):
                lines.append(f"{i}. {finding}")

        for s in self.dimension_scores:
            if s.reasoning:
                lines.append(f"\n### {s.dimension.capitalize()}")
                lines.append(s.reasoning)

        return "\n".join(lines) + "\n"


# ── Few-shot calibration examples ────────────────────────────────────────

# These examples teach the evaluator what GOOD and BAD reviews look like.
# Inspired by Anthropic's approach of calibrating evaluators with detailed
# score breakdowns to ensure judgment aligns with preferences and reduces
# score drift across iterations.

FEW_SHOT_GOOD_REVIEW = textwrap.dedent("""\
    ## Example of a GOOD adversarial review

    **Correctness (8/10, ×3):** The core logic handles all specified
    edge cases. However, the error handler at line 142 catches
    `Exception` instead of the specific `ConnectionError` and
    `TimeoutError` — this could mask bugs. The retry logic correctly
    implements exponential backoff but doesn't cap the maximum wait
    time, which could cause 30+ minute waits on the 10th retry.

    **Completeness (6/10, ×3):** Three of seven specified features are
    implemented and tested. The authentication flow is missing entirely
    — the spec requires OAuth2 PKCE but only basic API key auth exists.
    Rate limiting is documented but not implemented. Pagination is
    present but untested for the edge case of exactly `page_size` items.

    **Quality (7/10, ×2):** Code is well-structured with clear
    separation of concerns. Type annotations are thorough. However,
    there are three instances of copy-pasted validation logic that
    should be extracted into a shared validator. The `process_batch`
    function is 89 lines — consider decomposing.

    **Originality (7/10, ×1):** The caching strategy using content
    hashes for invalidation is a good design choice. The circuit
    breaker pattern for external API calls shows thoughtful
    architecture.

    **Findings:**
    1. 🔴 BLOCKING: OAuth2 PKCE auth flow missing (spec requirement)
    2. 🔴 BLOCKING: Bare `except Exception` at line 142 masks errors
    3. 🟡 Rate limiting documented but not implemented
    4. 🟡 Three instances of duplicated validation logic
    5. 💭 `process_batch` function length (89 lines)
""")

FEW_SHOT_BAD_REVIEW = textwrap.dedent("""\
    ## Example of a BAD review (too lenient, vague, no evidence)

    **Correctness (9/10):** The code looks correct and handles most
    cases well. There might be some edge cases to consider but overall
    it's solid work.

    **Completeness (8/10):** Most features are implemented. A few
    things could be added but the core functionality is there.

    **Quality (9/10):** Clean code with good structure. Well done!

    **Originality (8/10):** Some nice design choices throughout.

    ❌ WHY THIS IS BAD:
    - No specific line numbers, file references, or code examples
    - Scores are inflated — "looks correct" without verification
    - "There might be edge cases" — which ones? Be specific!
    - No mention of what's actually missing for completeness
    - "Clean code" without citing specific patterns or anti-patterns
    - No actionable findings — the generator can't improve from this
""")


class AdversarialEvaluator:
    """Adversarial evaluator that produces skeptical, evidence-based reviews.

    The evaluator is designed to counter the generator's natural optimism
    bias.  It uses explicit grading criteria with weighted dimensions and
    includes few-shot examples to calibrate its judgment.

    Parameters
    ----------
    approval_threshold:
        Minimum weighted average score for approval.
    dimensions:
        List of grading dimensions to evaluate.  Defaults to all four
        standard dimensions (Correctness, Completeness, Quality, Originality).
    """

    def __init__(
        self,
        approval_threshold: float = APPROVAL_THRESHOLD,
        dimensions: list[GradingDimension] | None = None,
    ) -> None:
        self._threshold = approval_threshold
        self._dimensions = dimensions or list(GradingDimension)

    @property
    def approval_threshold(self) -> float:
        """Minimum score for approval."""
        return self._threshold

    @property
    def dimensions(self) -> list[GradingDimension]:
        """Grading dimensions in use."""
        return list(self._dimensions)

    def get_system_prompt(self) -> str:
        """Build the adversarial evaluator system prompt.

        This prompt is designed to:
        1. Counter the generator's optimism bias
        2. Require evidence-based scoring with specific references
        3. Calibrate judgment via few-shot examples
        4. Enforce weighted scoring across explicit dimensions
        """
        dimension_desc = "\n".join(
            f"- **{d.label.capitalize()}** (weight ×{d.weight}): " for d in self._dimensions
        )

        return textwrap.dedent(f"""\
            You are an adversarial code reviewer. Your job is to find
            problems, not praise. Counter the generator's optimism bias.

            ## Your Mindset
            - Assume the code has bugs until proven otherwise
            - Look for what's MISSING, not just what's present
            - Test claims by examining evidence, not taking them at face value
            - Score conservatively — a 7/10 means genuinely good work
            - A 5/10 is average, not failing — calibrate accordingly

            ## Grading Dimensions
            {dimension_desc}

            ## Scoring Rules
            - Each dimension scored 1-10
            - Scores are weighted and averaged for the overall score
            - Overall score < {self._threshold} → REQUEST CHANGES
            - Overall score >= {self._threshold} → APPROVE
            - Every score MUST include specific evidence (file names, line
              numbers, test names, error messages)
            - Generic praise ("looks good", "well done") is not acceptable
            - If you can't find specific evidence for a high score, lower it

            ## What GOOD Reviews Look Like
            {FEW_SHOT_GOOD_REVIEW}

            ## What BAD Reviews Look Like
            {FEW_SHOT_BAD_REVIEW}

            ## Output Format
            Respond with a JSON object containing:
            {{
                "dimensions": [
                    {{
                        "dimension": "correctness",
                        "score": 7.0,
                        "reasoning": "Specific evidence..."
                    }},
                    ...
                ],
                "findings": [
                    "🔴 BLOCKING: specific issue with evidence",
                    "🟡 SUGGESTION: specific improvement",
                    ...
                ],
                "summary": "One paragraph overall assessment"
            }}
        """)

    def evaluate_from_scores(
        self,
        scores: dict[str, float],
        findings: list[str] | None = None,
        summary: str = "",
        reasoning: dict[str, str] | None = None,
        iteration: int = 0,
    ) -> EvaluationResult:
        """Create an EvaluationResult from raw dimension scores.

        This is the synchronous evaluation path — useful when scores
        come from a structured LLM output or from programmatic checks.

        Parameters
        ----------
        scores:
            Dict mapping dimension labels to scores (1-10).
        findings:
            List of specific findings/issues.
        summary:
            Overall assessment summary.
        reasoning:
            Dict mapping dimension labels to reasoning text.
        iteration:
            Current iteration number.
        """
        reasoning = reasoning or {}
        dimension_scores: list[DimensionScore] = []

        for dim in self._dimensions:
            score = scores.get(dim.label, 5.0)
            score = max(1.0, min(10.0, float(score)))
            dimension_scores.append(
                DimensionScore(
                    dimension=dim.label,
                    score=score,
                    weight=dim.weight,
                    reasoning=reasoning.get(dim.label, ""),
                )
            )

        result = EvaluationResult(
            dimension_scores=dimension_scores,
            findings=findings or [],
            summary=summary,
            iteration=iteration,
        )

        # Set verdict based on threshold
        result.verdict = "approve" if result.overall_score >= self._threshold else "request_changes"

        return result

    def parse_llm_response(self, response_text: str, iteration: int = 0) -> EvaluationResult:
        """Parse an LLM's JSON response into an EvaluationResult.

        Handles common LLM output quirks: markdown code fences,
        trailing commas, etc.

        Parameters
        ----------
        response_text:
            The raw text response from the evaluator LLM.
        iteration:
            Current iteration number.
        """
        # Strip markdown code fences if present
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (```json and ```)
            lines = [line for line in lines if not line.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse evaluator response as JSON")
            return EvaluationResult(
                summary="Failed to parse evaluator response",
                findings=["Parse error — raw response needs manual review"],
                iteration=iteration,
            )

        # Extract scores and reasoning
        scores: dict[str, float] = {}
        reasoning: dict[str, str] = {}

        for dim_data in data.get("dimensions", []):
            label = dim_data.get("dimension", "").lower()
            scores[label] = float(dim_data.get("score", 5.0))
            reasoning[label] = dim_data.get("reasoning", "")

        return self.evaluate_from_scores(
            scores=scores,
            findings=data.get("findings", []),
            summary=data.get("summary", ""),
            reasoning=reasoning,
            iteration=iteration,
        )

    def should_approve(self, result: EvaluationResult) -> bool:
        """Check if the evaluation result meets the approval threshold."""
        return result.overall_score >= self._threshold
