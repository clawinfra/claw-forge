"""Layer 1 spec validator: deterministic structural checks on feature bullets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

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
    "run_structural_checks",
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


def _check_category(check: object) -> str:
    """Return the canonical category label for a check function.

    Uses the explicit ``_CHECK_CATEGORIES`` mapping so that keys in
    ``ValidationReport.category_scores`` always match ``ValidationIssue.category``
    values emitted by the same check.
    """
    name = getattr(check, "__name__", str(check))
    return _CHECK_CATEGORIES.get(name, name)
