"""Layer 1 spec validator: deterministic structural checks on feature bullets."""

from __future__ import annotations

import contextlib
import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from claw_forge.spec.parser import FeatureItem, ProjectSpec

__all__ = [
    "IssueSeverity",
    "ValidationIssue",
    "ValidationReport",
    "check_has_measurable_outcome",
    "check_is_atomic",
    "check_not_too_vague",
    "check_starts_with_action_verb",
    "run_coverage_checks",
    "run_structural_checks",
    "SpecEvaluator",
    "SPEC_DIMENSIONS",
    "run_llm_evaluation",
]


class IssueSeverity(Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class ValidationIssue:
    severity: IssueSeverity
    layer: int
    category: str
    bullet: str
    message: str
    suggestion: str = ""


@dataclass
class ValidationReport:
    issues: list[ValidationIssue]
    category_scores: dict[str, float]

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.WARNING)

    @property
    def total_issues(self) -> int:
        return len(self.issues)

    @property
    def passed(self) -> bool:
        return self.error_count == 0

    def layer_issues(self, layer: int) -> list[ValidationIssue]:
        return [i for i in self.issues if i.layer == layer]


# ---------------------------------------------------------------------------
# Structural rule helpers
# ---------------------------------------------------------------------------

_ACTION_VERB_PREFIXES = (
    "user can ",
    "user cannot ",
    "system ",
    "api ",
    "ui ",
    "app ",
    "admin ",
    "service ",
    "backend ",
    "frontend ",
    "database ",
    "agent ",
    "webhook ",
    "background ",
)

_MEASURABLE_PATTERNS = [
    re.compile(r"returns?\s+\d{3}", re.IGNORECASE),
    re.compile(r"\(returns?\s", re.IGNORECASE),
    re.compile(r"displays?\s+", re.IGNORECASE),
    re.compile(r"shows?\s+", re.IGNORECASE),
    re.compile(r"redirects?\s+to\s+", re.IGNORECASE),
    re.compile(r"saves?\s+to\s+", re.IGNORECASE),
    re.compile(r"emits?\s+", re.IGNORECASE),
    re.compile(r"sends?\s+", re.IGNORECASE),
    re.compile(r"creates?\s+", re.IGNORECASE),
    re.compile(r"with\s+\w+_\w+", re.IGNORECASE),
    re.compile(r"HTTP\s+\d{3}"),
    re.compile(r"\d{3}\s+error", re.IGNORECASE),
    re.compile(r"error\s+message", re.IGNORECASE),
    re.compile(r"toast\s+notification", re.IGNORECASE),
    re.compile(r"persists?\s+", re.IGNORECASE),
]

_COMPOUND_CONNECTORS = [
    "and then",
    "and also",
    "and after",
    "then login",
    "then register",
    "and receive",
    "and redirect",
    "and create",
    "and send",
    "and return",
]

_VAGUE_WORDS = re.compile(
    r"\b(etc|various|multiple|some|things|stuff|items)\b", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Public check functions
# ---------------------------------------------------------------------------


def check_starts_with_action_verb(feat: FeatureItem) -> ValidationIssue | None:
    """Return WARNING if bullet does not start with a recognised subject prefix."""
    text = feat.description.lower()
    for prefix in _ACTION_VERB_PREFIXES:
        if text.startswith(prefix):
            return None
    return ValidationIssue(
        severity=IssueSeverity.WARNING,
        layer=1,
        category="action_verb",
        bullet=feat.description,
        message=(
            "Bullet does not start with a recognised subject/action prefix "
            f"(e.g. 'User can', 'System ', 'API '). Got: {feat.description[:40]!r}"
        ),
        suggestion="Rewrite to start with a subject prefix such as 'User can …' or 'System …'.",
    )


def check_has_measurable_outcome(feat: FeatureItem) -> ValidationIssue | None:
    """Return WARNING if bullet contains no measurable/observable outcome."""
    text = feat.description
    for pattern in _MEASURABLE_PATTERNS:
        if pattern.search(text):
            return None
    return ValidationIssue(
        severity=IssueSeverity.WARNING,
        layer=1,
        category="measurable_outcome",
        bullet=feat.description,
        message=(
            "Bullet has no detectable measurable outcome "
            "(e.g. HTTP status code, 'displays', 'saves to', 'error message')."
        ),
        suggestion=(
            "Add an observable result, e.g. '(returns 200 with JWT)'"
            " or 'displays an error message'."
        ),
    )


def check_is_atomic(feat: FeatureItem) -> ValidationIssue | None:
    """Return ERROR if bullet contains a compound connector implying multiple actions."""
    text = feat.description.lower()
    for phrase in _COMPOUND_CONNECTORS:
        if phrase in text:
            return ValidationIssue(
                severity=IssueSeverity.ERROR,
                layer=1,
                category="atomic",
                bullet=feat.description,
                message=(
                    "Bullet appears to describe multiple actions "
                    f"(found compound connector: {phrase!r}). "
                    "Split into separate atomic bullets."
                ),
                suggestion=f"Remove '{phrase}' and split into two separate feature bullets.",
            )
    return None


def check_not_too_vague(feat: FeatureItem) -> ValidationIssue | None:
    """Return WARNING if bullet is too short or contains vague filler words."""
    text = feat.description
    word_count = len(text.split())
    if word_count < 6:
        return ValidationIssue(
            severity=IssueSeverity.WARNING,
            layer=1,
            category="vague",
            bullet=text,
            message=(
                f"Bullet is too short ({word_count} words)."
                " Bullets should be at least 6 words."
            ),
            suggestion="Expand the bullet to include subject, action, and expected outcome.",
        )
    match = _VAGUE_WORDS.search(text)
    if match:
        word = match.group(0)
        return ValidationIssue(
            severity=IssueSeverity.WARNING,
            layer=1,
            category="vague",
            bullet=text,
            message=f"Bullet contains vague filler word {word!r}. Be specific.",
            suggestion=f"Replace {word!r} with concrete, enumerated terms.",
        )
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

_CHECKS = [
    check_starts_with_action_verb,
    check_has_measurable_outcome,
    check_is_atomic,
    check_not_too_vague,
]

# Maps each check function to the canonical category string used in ValidationIssue.category.
# Keeping this explicit avoids fragile name-mangling and ensures category_scores keys
# are always consistent with the issue categories reported.
_CHECK_CATEGORIES: dict[str, str] = {
    "check_starts_with_action_verb": "action_verb",
    "check_has_measurable_outcome": "measurable_outcome",
    "check_is_atomic": "atomic",
    "check_not_too_vague": "vague",
}


def run_structural_checks(spec: ProjectSpec) -> ValidationReport:
    """Run all Layer-1 structural checks on every feature in the spec."""
    issues: list[ValidationIssue] = []
    category_pass: dict[str, int] = {}
    category_total: dict[str, int] = {}

    for feat in spec.features:
        for check in _CHECKS:
            issue = check(feat)
            cat = _check_category(check)
            category_total[cat] = category_total.get(cat, 0) + 1
            if issue is not None:
                issues.append(issue)
            else:
                category_pass[cat] = category_pass.get(cat, 0) + 1

    category_scores: dict[str, float] = {}
    for cat, total in category_total.items():
        passed = category_pass.get(cat, 0)
        category_scores[cat] = passed / total if total > 0 else 1.0

    return ValidationReport(issues=issues, category_scores=category_scores)


def _endpoint_path(endpoint_line: str) -> str:
    """Extract the URL path from 'POST /api/auth/register - Register new user'.

    Strips query strings (``?…``) so that ``/api/users?active=true`` is
    normalised to ``/api/users`` before the coverage check.
    """
    parts = endpoint_line.strip().split()
    for part in parts:
        if part.startswith("/"):
            # Drop any query string (e.g. /api/users?active=true → /api/users)
            return part.split("?")[0]
    return endpoint_line.strip()


def _term_in_bullets(term: str, all_bullets: str) -> bool:
    """Return True if *term* appears as a whole token in *all_bullets*.

    Uses a word-boundary regex so that ``/api/user`` does **not** match a
    bullet that only mentions ``/api/users``, avoiding false-positive coverage.
    Non-word characters at the boundaries of the term (``/``, ``-``, ``_``)
    are treated as delimiters.
    """
    escaped = re.escape(term)
    return bool(re.search(r"(?<!\w)" + escaped + r"(?!\w)", all_bullets))


def run_coverage_checks(spec: ProjectSpec) -> ValidationReport:
    """Layer 3: cross-reference endpoints and tables against feature bullets.

    Every API endpoint in <api_endpoints_summary> must appear in at least one
    feature bullet (path match). Every table in <database_schema> must be
    referenced in at least one bullet. Missing coverage means the agent will
    never implement that endpoint or table.
    """
    issues: list[ValidationIssue] = []
    all_bullets = " ".join(feat.description.lower() for feat in spec.features)

    for domain, endpoint_lines in spec.api_endpoints.items():
        for endpoint_line in endpoint_lines:
            path = _endpoint_path(endpoint_line)
            path_lower = path.lower()
            path_clean = path.lstrip("/").replace("-", " ").replace("_", " ").lower()
            if not _term_in_bullets(path_lower, all_bullets) and not _term_in_bullets(
                path_clean, all_bullets
            ):
                issues.append(
                    ValidationIssue(
                        severity=IssueSeverity.WARNING,
                        layer=3,
                        category=domain,
                        bullet="",
                        message=f"No feature bullet references endpoint {path}",
                        suggestion=f"Add a bullet in '{domain}' covering {path}",
                    )
                )

    for table_name in spec.database_tables:
        table_lower = table_name.lower()
        table_clean = table_name.replace("_", " ").lower()
        if not _term_in_bullets(table_lower, all_bullets) and not _term_in_bullets(
            table_clean, all_bullets
        ):
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.WARNING,
                    layer=3,
                    category="Database",
                    bullet="",
                    message=f"No feature bullet references table '{table_name}'",
                    suggestion=f"Add CRUD bullets for the '{table_name}' table",
                )
            )

    return ValidationReport(issues=issues, category_scores={})


def _check_category(check: object) -> str:
    """Return the canonical category label for a check function.

    Uses the explicit ``_CHECK_CATEGORIES`` mapping so that keys in
    ``ValidationReport.category_scores`` always match ``ValidationIssue.category``
    values emitted by the same check.
    """
    name = getattr(check, "__name__", str(check))
    return _CHECK_CATEGORIES.get(name, name)


# ---------------------------------------------------------------------------
# Layer 2: adversarial LLM evaluation per category
# ---------------------------------------------------------------------------

SPEC_DIMENSIONS: list[tuple[str, int, str]] = [
    (
        "Testability",
        3,
        "Can you write a pass/fail test for every bullet?"
        " Each bullet must have a verifiable outcome.",
    ),
    (
        "Atomicity",
        3,
        "Is each bullet one implementable unit?"
        " No compound sequences. No 'and then' chains.",
    ),
    (
        "Specificity",
        2,
        "Does each bullet name concrete things:"
        " HTTP status, field names, UI elements, error messages?",
    ),
    (
        "ErrorCoverage",
        2,
        "Does the category cover error and edge cases, not just the happy path?",
    ),
]
_TOTAL_WEIGHT = sum(w for _, w, _ in SPEC_DIMENSIONS)

_STRONG_EXAMPLE = """\
Authentication bullets (score ≈8.5):
- User can login with email + password (POST /api/auth/login returns 200 with JWT)
- System returns 401 with {"error": "invalid_credentials"} on wrong password
- System returns 400 with field errors when email is malformed
- User can logout (DELETE /api/auth/session returns 204, clears HttpOnly cookie)
"""

_WEAK_EXAMPLE = """\
Core bullets (score ≈3.5):
- User can manage things
- System handles errors
- App does login stuff and then redirects user somewhere
"""


class SpecEvaluator:
    """Adversarial evaluator for spec category bullets."""

    def __init__(self, approve_threshold: float = 7.0) -> None:
        self.approve_threshold = approve_threshold

    def grade(
        self,
        bullets: str,
        category: str,
        dimension_scores: dict[str, float],
        feedback: str = "",
    ) -> dict[str, Any]:
        """Compute weighted score across SPEC_DIMENSIONS and return grading result."""
        total_weight = _TOTAL_WEIGHT
        weighted_sum = 0.0
        breakdown: dict[str, float] = {}
        for dim_name, weight, _ in SPEC_DIMENSIONS:
            score = float(dimension_scores.get(dim_name, 0.0))
            breakdown[dim_name] = score
            weighted_sum += score * weight

        score = (weighted_sum / (total_weight * 10)) * 10 if total_weight > 0 else 0.0
        verdict = "APPROVE" if score >= self.approve_threshold else "REQUEST_CHANGES"
        return {
            "score": score,
            "verdict": verdict,
            "breakdown": breakdown,
            "feedback": feedback,
            "category": category,
        }

    def build_evaluator_prompt(
        self,
        bullets: str,
        category: str,
        tech_stack: str = "",
    ) -> str:
        """Return adversarial evaluator prompt for the given bullets."""
        dimensions_block = "\n".join(
            f"- {name} (weight {weight}): {desc}"
            for name, weight, desc in SPEC_DIMENSIONS
        )
        tech_line = f"Tech stack: {tech_stack}\n" if tech_stack else ""
        prompt = f"""\
ADVERSARIAL SPEC EVALUATOR

You are an adversarial evaluator grading feature spec bullets for implementability.
Be strict. Real projects fail when specs are vague or non-testable.

{tech_line}Category: {category}

## Grading Dimensions
{dimensions_block}

Score each dimension 1-10 (10 = perfect).

## Calibration Examples

{_STRONG_EXAMPLE}
{_WEAK_EXAMPLE}

## Bullets to Evaluate

{bullets}

## Required Output Format
Output exactly these lines (no extra text before them):
Testability: <score>
Atomicity: <score>
Specificity: <score>
ErrorCoverage: <score>
Verdict: APPROVE or REQUEST_CHANGES
Feedback: <one or two sentences>
"""
        return prompt

    def parse_llm_response(self, text: str) -> tuple[dict[str, float], str]:
        """Parse dimension scores and feedback from LLM response text."""
        scores: dict[str, float] = {}
        feedback = ""
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.lower().startswith("feedback:"):
                feedback = line[len("feedback:"):].strip()
                continue
            for dim_name, _, _ in SPEC_DIMENSIONS:
                prefix = f"{dim_name}:"
                if line.startswith(prefix):
                    value_str = line[len(prefix):].strip().split()[0]
                    with contextlib.suppress(ValueError):
                        scores[dim_name] = float(value_str)
                    break
        return scores, feedback


def run_llm_evaluation(
    spec: ProjectSpec,
    approve_threshold: float = 7.0,
    model: str = "claude-haiku-4-5-20251001",
) -> ValidationReport:
    """Layer 2: adversarial LLM evaluation per category.

    Requires ANTHROPIC_API_KEY. If absent, returns empty report with one
    WARNING issue explaining the skip — never raises.
    Uses Haiku by default (structured prompt, cheap model sufficient).
    Groups features by category, calls API once per category.
    Scores stored in report.category_scores[category_name].
    Categories scoring < approve_threshold get a WARNING issue (layer=2).
    Any API error per category gets a WARNING issue (layer=2) and continues.
    """
    import anthropic  # optional dependency — imported inside function

    issues: list[ValidationIssue] = []
    category_scores: dict[str, float] = {}

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        issues.append(
            ValidationIssue(
                severity=IssueSeverity.WARNING,
                layer=2,
                category="llm_evaluation",
                bullet="",
                message=(
                    "Layer 2 LLM evaluation skipped: ANTHROPIC_API_KEY is not set."
                ),
                suggestion="Set ANTHROPIC_API_KEY to enable adversarial LLM evaluation.",
            )
        )
        return ValidationReport(issues=issues, category_scores=category_scores)

    # Group features by category
    categories: dict[str, list[str]] = {}
    for feat in spec.features:
        categories.setdefault(feat.category, []).append(feat.description)

    # Build tech_stack string
    ts = spec.tech_stack
    if hasattr(ts, "raw") and ts.raw:
        tech_stack = ts.raw
    else:
        parts = []
        if hasattr(ts, "frontend_framework") and ts.frontend_framework:
            parts.append(ts.frontend_framework)
        if hasattr(ts, "backend_runtime") and ts.backend_runtime:
            parts.append(ts.backend_runtime)
        tech_stack = " + ".join(parts) if parts else ""

    evaluator = SpecEvaluator(approve_threshold=approve_threshold)
    client = anthropic.Anthropic(api_key=api_key)

    for category, bullets in categories.items():
        bullet_block = "\n".join(f"- {b}" for b in bullets)
        prompt = evaluator.build_evaluator_prompt(bullet_block, category, tech_stack)
        try:
            response = client.messages.create(
                model=model,
                max_tokens=512,
                system="You are an adversarial spec evaluator. Grade ruthlessly.",
                messages=[{"role": "user", "content": prompt}],
            )
            response_text = response.content[0].text
            dimension_scores, feedback = evaluator.parse_llm_response(response_text)
            result = evaluator.grade(bullet_block, category, dimension_scores, feedback)
            score = result["score"]
            category_scores[category] = score
            if result["verdict"] == "REQUEST_CHANGES":
                issues.append(
                    ValidationIssue(
                        severity=IssueSeverity.WARNING,
                        layer=2,
                        category=category,
                        bullet="",
                        message=(
                            f"Category '{category}' scored {score:.1f}/10 "
                            f"(threshold {approve_threshold}). {feedback}"
                        ),
                        suggestion=(
                            "Improve bullet specificity, testability, atomicity, "
                            "and error coverage."
                        ),
                    )
                )
        except Exception as exc:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.WARNING,
                    layer=2,
                    category=category,
                    bullet="",
                    message=f"LLM evaluation failed for category '{category}': {exc}",
                    suggestion="Check API key and model name, then retry.",
                )
            )

    return ValidationReport(issues=issues, category_scores=category_scores)
