# Spec Validator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 3-layer spec validator (`claw_forge/spec/validator.py`) and a `claw-forge validate-spec` CLI command that catches bad bullets before they become bad agent tasks.

**Architecture:** Layer 1 runs deterministic structural rules on every bullet (no LLM, no cost). Layer 2 runs an adversarial LLM evaluator per category using the `AdversarialEvaluator` pattern from agent-harness-skills, adapted inline with spec-specific grading dimensions. Layer 3 cross-references `<api_endpoints_summary>` and `<database_schema>` against `<core_features>` bullets to catch coverage gaps. All three layers produce typed `ValidationIssue` objects that the CLI renders into a human-readable report.

**Tech Stack:** Python 3.12, `anthropic` SDK (already a dependency), `typer` CLI (already used), `claw_forge.spec.parser.ProjectSpec` (existing).

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `claw_forge/spec/validator.py` | All 3 layers + `ValidationReport` dataclass |
| Create | `tests/spec/test_validator.py` | Full test coverage for all layers |
| Modify | `claw_forge/cli.py` | Add `validate-spec` Typer command |

---

## Task 1: Core data structures and Layer 1 structural rules

**Files:**
- Create: `claw_forge/spec/validator.py`
- Create: `tests/spec/test_validator.py`

- [ ] **Step 1: Write the failing tests for Layer 1**

```python
# tests/spec/test_validator.py
"""Tests for claw_forge.spec.validator — 3-layer spec bullet validation."""
from __future__ import annotations
import textwrap
import pytest
from claw_forge.spec.parser import FeatureItem, ProjectSpec, TechStack
from claw_forge.spec.validator import (
    IssueSeverity,
    ValidationIssue,
    ValidationReport,
    check_starts_with_action_verb,
    check_has_measurable_outcome,
    check_is_atomic,
    check_not_too_vague,
    run_structural_checks,
)

# ── Layer 1: structural rule unit tests ──────────────────────────────────────

def test_check_starts_with_action_verb_pass():
    f = FeatureItem(category="Auth", name="login", description="User can login and receive JWT")
    assert check_starts_with_action_verb(f) is None

def test_check_starts_with_action_verb_fail():
    f = FeatureItem(category="Auth", name="jwt", description="JWT token is issued on login")
    issue = check_starts_with_action_verb(f)
    assert issue is not None
    assert issue.severity == IssueSeverity.WARNING
    assert "action verb" in issue.message.lower()

def test_check_has_measurable_outcome_pass():
    f = FeatureItem(category="Auth", name="login", description="User can login (returns 200 with JWT)")
    assert check_has_measurable_outcome(f) is None

def test_check_has_measurable_outcome_fail():
    f = FeatureItem(category="Auth", name="login", description="User can login")
    issue = check_has_measurable_outcome(f)
    assert issue is not None
    assert issue.severity == IssueSeverity.WARNING

def test_check_is_atomic_pass():
    f = FeatureItem(category="Auth", name="login", description="User can login with email and password")
    assert check_is_atomic(f) is None

def test_check_is_atomic_fail():
    f = FeatureItem(
        category="Auth", name="combo",
        description="User can register and then login and receive a JWT token"
    )
    issue = check_is_atomic(f)
    assert issue is not None
    assert issue.severity == IssueSeverity.ERROR

def test_check_not_too_vague_pass():
    f = FeatureItem(category="Auth", name="ok", description="User can register with email and password (returns 201 with user_id)")
    assert check_not_too_vague(f) is None

def test_check_not_too_vague_fail_short():
    f = FeatureItem(category="Auth", name="short", description="User can do things")
    issue = check_not_too_vague(f)
    assert issue is not None
    assert issue.severity == IssueSeverity.WARNING

def test_check_not_too_vague_fail_etc():
    f = FeatureItem(category="Auth", name="etc", description="User can manage items, etc.")
    issue = check_not_too_vague(f)
    assert issue is not None

def _make_spec(bullets: list[str], category: str = "Auth") -> ProjectSpec:
    features = [
        FeatureItem(category=category, name=b[:30], description=b)
        for b in bullets
    ]
    return ProjectSpec(
        project_name="test", overview="", tech_stack=TechStack(),
        features=features, implementation_phases=[], success_criteria=[],
        design_system={}, api_endpoints={}, database_tables={}, raw_xml="",
    )

def test_run_structural_checks_all_pass():
    spec = _make_spec([
        "User can register with email and password (returns 201 with user_id)",
        "System returns 409 when email is already registered",
        "User can login and receive JWT access_token (returns 200)",
    ])
    report = run_structural_checks(spec)
    assert report.error_count == 0

def test_run_structural_checks_catches_violations():
    spec = _make_spec([
        "register and login and do everything",  # compound + vague
        "JWT stuff",                              # not action verb + vague
    ])
    report = run_structural_checks(spec)
    assert report.total_issues > 0
    assert report.error_count > 0 or report.warning_count > 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/bowenli/development/claw-forge
uv run pytest tests/spec/test_validator.py -v 2>&1 | head -30
```
Expected: `ModuleNotFoundError: No module named 'claw_forge.spec.validator'`

- [ ] **Step 3: Write `claw_forge/spec/validator.py` with Layer 1**

```python
"""3-layer spec bullet validator for claw-forge project specifications.

Layer 1 — Structural (deterministic, zero LLM cost):
    Checks each bullet for action-verb prefix, measurable outcome,
    atomicity, and non-vagueness.

Layer 2 — Adversarial LLM evaluation (per-category, optional):
    Uses the AdversarialEvaluator pattern from agent-harness-skills to
    grade each category's bullet set on testability, atomicity,
    specificity, and error coverage.  Requires ANTHROPIC_API_KEY.

Layer 3 — Coverage gap detection (deterministic):
    Cross-references <api_endpoints_summary> and <database_schema>
    against <core_features> bullets.  Flags endpoints and tables with
    no corresponding bullet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from claw_forge.spec.parser import FeatureItem, ProjectSpec


# ---------------------------------------------------------------------------
# Issue model
# ---------------------------------------------------------------------------

class IssueSeverity(str, Enum):
    ERROR = "error"    # blocks progress; must fix
    WARNING = "warning"  # degrades quality; should fix


@dataclass
class ValidationIssue:
    severity: IssueSeverity
    layer: int          # 1, 2, or 3
    category: str
    bullet: str         # the offending bullet text (empty for layer-3 gaps)
    message: str
    suggestion: str = ""


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)
    category_scores: dict[str, float] = field(default_factory=dict)  # layer 2

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
# Layer 1 — structural rules
# ---------------------------------------------------------------------------

# Prefixes that indicate a proper action-verb bullet
_ACTION_VERB_PREFIXES = (
    "user can", "user cannot", "system ", "api ", "ui ", "app ",
    "admin ", "service ", "backend ", "frontend ", "database ",
    "agent ", "webhook ", "background ",
)

# Patterns that suggest a measurable outcome is present
_OUTCOME_PATTERNS = [
    re.compile(r"returns?\s+\d{3}", re.I),         # "returns 200"
    re.compile(r"\(returns?\s", re.I),              # "(returns ..."
    re.compile(r"displays?\s+", re.I),              # "displays X"
    re.compile(r"shows?\s+", re.I),                 # "shows X"
    re.compile(r"redirects?\s+to\s+", re.I),        # "redirects to /dashboard"
    re.compile(r"saves?\s+to\s+", re.I),            # "saves to database"
    re.compile(r"emits?\s+", re.I),                 # "emits event"
    re.compile(r"sends?\s+", re.I),                 # "sends email"
    re.compile(r"creates?\s+", re.I),               # "creates record"
    re.compile(r"with\s+\w+_\w+", re.I),            # "with user_id" (snake_case field)
    re.compile(r"HTTP\s+\d{3}", re.I),              # "HTTP 404"
    re.compile(r"\d{3}\s+error", re.I),             # "400 error"
    re.compile(r"error\s+message", re.I),           # "error message"
    re.compile(r"toast\s+notification", re.I),      # UI feedback
    re.compile(r"persists?\s+", re.I),              # "persists to DB"
]

# Vagueness flags
_VAGUE_PHRASES = ("etc", "various", "multiple", "some", "things", "stuff", "items")
_MIN_BULLET_WORDS = 6


def check_starts_with_action_verb(feat: FeatureItem) -> ValidationIssue | None:
    """Bullet must start with a recognised action-verb prefix."""
    text = feat.description.lower().strip()
    if any(text.startswith(p) for p in _ACTION_VERB_PREFIXES):
        return None
    return ValidationIssue(
        severity=IssueSeverity.WARNING,
        layer=1,
        category=feat.category,
        bullet=feat.description,
        message="Bullet does not start with a recognised action verb.",
        suggestion=(
            f'Rewrite as: "User can ...", "System returns ...", '
            f'"API validates ...", or "UI displays ..."'
        ),
    )


def check_has_measurable_outcome(feat: FeatureItem) -> ValidationIssue | None:
    """Bullet should contain a concrete, observable outcome."""
    text = feat.description
    if any(p.search(text) for p in _OUTCOME_PATTERNS):
        return None
    return ValidationIssue(
        severity=IssueSeverity.WARNING,
        layer=1,
        category=feat.category,
        bullet=feat.description,
        message="Bullet has no measurable outcome.",
        suggestion=(
            "Add a concrete result: HTTP status code, UI element name, "
            "field name, redirect target, or event name. "
            'Example: "User can login (returns 200 with access_token)"'
        ),
    )


def check_is_atomic(feat: FeatureItem) -> ValidationIssue | None:
    """Bullet must describe a single behavior, not a compound sequence."""
    text = feat.description.lower()
    # Look for compound connectors that join two *distinct* subject-verb clauses.
    # Simple "email and password" is fine — we want to catch "register and login".
    compound = re.search(
        r"\b(and then|and also|and after|then login|then register|"
        r"and receive|and redirect|and create|and send|and return)\b",
        text,
    )
    if compound:
        return ValidationIssue(
            severity=IssueSeverity.ERROR,
            layer=1,
            category=feat.category,
            bullet=feat.description,
            message=f"Compound bullet detected ('{compound.group()}'). Split into two bullets.",
            suggestion=(
                "Each bullet must be one atomic behavior. "
                "Split at the compound connector into separate lines."
            ),
        )
    return None


def check_not_too_vague(feat: FeatureItem) -> ValidationIssue | None:
    """Bullet must be specific enough for an agent to implement."""
    text = feat.description

    # Too short
    word_count = len(text.split())
    if word_count < _MIN_BULLET_WORDS:
        return ValidationIssue(
            severity=IssueSeverity.WARNING,
            layer=1,
            category=feat.category,
            bullet=text,
            message=f"Bullet is too short ({word_count} words). Minimum is {_MIN_BULLET_WORDS}.",
            suggestion="Add specifics: which field, which endpoint, which error code, which UI element.",
        )

    # Vague filler words
    lower = text.lower()
    found = [p for p in _VAGUE_PHRASES if re.search(rf"\b{p}\b", lower)]
    if found:
        return ValidationIssue(
            severity=IssueSeverity.WARNING,
            layer=1,
            category=feat.category,
            bullet=text,
            message=f"Bullet contains vague filler: {found!r}.",
            suggestion="Replace vague words with concrete specifics.",
        )

    return None


_LAYER1_RULES = [
    check_starts_with_action_verb,
    check_has_measurable_outcome,
    check_is_atomic,
    check_not_too_vague,
]


def run_structural_checks(spec: ProjectSpec) -> ValidationReport:
    """Run all Layer 1 structural rules against every bullet in the spec."""
    report = ValidationReport()
    for feat in spec.features:
        for rule in _LAYER1_RULES:
            issue = rule(feat)
            if issue:
                report.issues.append(issue)
    return report
```

- [ ] **Step 4: Run Layer 1 tests**

```bash
uv run pytest tests/spec/test_validator.py -v 2>&1 | tail -20
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/spec/validator.py tests/spec/test_validator.py
git commit -m "feat(spec): add validator Layer 1 — structural bullet rules"
```

---

## Task 2: Layer 3 — Coverage gap detection

**Files:**
- Modify: `claw_forge/spec/validator.py` (append functions)
- Modify: `tests/spec/test_validator.py` (append tests)

- [ ] **Step 1: Write failing tests for Layer 3**

Append to `tests/spec/test_validator.py`:

```python
from claw_forge.spec.validator import run_coverage_checks

def test_run_coverage_checks_no_gaps():
    spec = _make_spec([
        "User can POST /api/auth/register with email",
        "User can view users table records",
    ])
    spec.api_endpoints = {"Auth": ["POST /api/auth/register - Register"]}
    spec.database_tables = {"users": ["id UUID PRIMARY KEY"]}
    report = run_coverage_checks(spec)
    assert report.error_count == 0

def test_run_coverage_checks_missing_endpoint():
    spec = _make_spec(["User can login (returns 200)"])
    spec.api_endpoints = {"Payments": ["POST /api/payments/charge - Charge card"]}
    spec.database_tables = {}
    report = run_coverage_checks(spec)
    layer3 = [i for i in report.issues if i.layer == 3]
    assert len(layer3) >= 1
    assert "/api/payments/charge" in layer3[0].message

def test_run_coverage_checks_missing_table():
    spec = _make_spec(["User can login (returns 200)"])
    spec.api_endpoints = {}
    spec.database_tables = {"invoices": ["id UUID PRIMARY KEY", "amount NUMERIC NOT NULL"]}
    report = run_coverage_checks(spec)
    layer3 = [i for i in report.issues if i.layer == 3]
    assert len(layer3) >= 1
    assert "invoices" in layer3[0].message
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/spec/test_validator.py::test_run_coverage_checks_no_gaps -v
```
Expected: `ImportError: cannot import name 'run_coverage_checks'`

- [ ] **Step 3: Add Layer 3 to `validator.py`**

Append to `claw_forge/spec/validator.py` after `run_structural_checks`:

```python
# ---------------------------------------------------------------------------
# Layer 3 — coverage gap detection
# ---------------------------------------------------------------------------

def _endpoint_path(endpoint_line: str) -> str:
    """Extract the URL path from a line like 'POST /api/auth/register - Register'."""
    parts = endpoint_line.strip().split()
    for part in parts:
        if part.startswith("/"):
            return part
    return endpoint_line.strip()


def run_coverage_checks(spec: ProjectSpec) -> ValidationReport:
    """Layer 3: cross-reference endpoints and tables against feature bullets.

    Every API endpoint listed in <api_endpoints_summary> must appear in at
    least one feature bullet.  Every table in <database_schema> must be
    referenced in at least one bullet.  Missing coverage = the agent will
    never implement that endpoint or table.
    """
    report = ValidationReport()
    all_bullets = " ".join(f.description.lower() for f in spec.features)

    # Check API endpoints
    for domain, endpoints in spec.api_endpoints.items():
        for endpoint_line in endpoints:
            path = _endpoint_path(str(endpoint_line))
            # Normalise: strip leading slash, replace hyphens/underscores
            path_clean = path.lstrip("/").replace("-", " ").replace("_", " ").lower()
            # Also check the raw path
            if path.lower() not in all_bullets and path_clean not in all_bullets:
                report.issues.append(ValidationIssue(
                    severity=IssueSeverity.WARNING,
                    layer=3,
                    category=domain,
                    bullet="",
                    message=f"No feature bullet references endpoint {path}",
                    suggestion=(
                        f"Add a bullet in the '{domain}' category that covers {path}. "
                        f'Example: "User can call {path} to ..."'
                    ),
                ))

    # Check database tables
    for table_name in spec.database_tables:
        table_clean = table_name.replace("_", " ").lower()
        if table_name.lower() not in all_bullets and table_clean not in all_bullets:
            report.issues.append(ValidationIssue(
                severity=IssueSeverity.WARNING,
                layer=3,
                category="Database",
                bullet="",
                message=f"No feature bullet references table '{table_name}'",
                suggestion=(
                    f"Add bullets that describe creating, reading, updating, and deleting "
                    f"records in the '{table_name}' table."
                ),
            ))

    return report
```

- [ ] **Step 4: Run Layer 3 tests**

```bash
uv run pytest tests/spec/test_validator.py -k "coverage" -v
```
Expected: all 3 coverage tests pass.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/spec/validator.py tests/spec/test_validator.py
git commit -m "feat(spec): add validator Layer 3 — coverage gap detection"
```

---

## Task 3: Layer 2 — Adversarial LLM evaluator (per-category)

**Files:**
- Modify: `claw_forge/spec/validator.py` (append LLM evaluator)
- Modify: `tests/spec/test_validator.py` (append tests)

- [ ] **Step 1: Write failing tests for Layer 2**

Append to `tests/spec/test_validator.py`:

```python
from unittest.mock import patch, MagicMock
from claw_forge.spec.validator import (
    SpecEvaluator,
    SPEC_DIMENSIONS,
    run_llm_evaluation,
)

def test_spec_evaluator_approve():
    ev = SpecEvaluator(approve_threshold=7.0)
    result = ev.grade(
        bullets="User can login (returns 200 with JWT)\nSystem returns 401 on bad credentials",
        category="Authentication",
        dimension_scores={"Testability": 9, "Atomicity": 9, "Specificity": 8, "ErrorCoverage": 8},
        feedback="Strong category.",
    )
    assert result["verdict"] == "APPROVE"
    assert result["score"] >= 7.0

def test_spec_evaluator_request_changes():
    ev = SpecEvaluator(approve_threshold=7.0)
    result = ev.grade(
        bullets="User can manage things",
        category="Core",
        dimension_scores={"Testability": 3, "Atomicity": 5, "Specificity": 2, "ErrorCoverage": 2},
        feedback="Too vague.",
    )
    assert result["verdict"] == "REQUEST_CHANGES"
    assert result["score"] < 7.0

def test_spec_evaluator_builds_prompt():
    ev = SpecEvaluator()
    prompt = ev.build_evaluator_prompt(
        bullets="User can login (returns 200)\nSystem returns 401 on failure",
        category="Authentication",
        tech_stack="FastAPI + React",
    )
    assert "ADVERSARIAL" in prompt
    assert "Authentication" in prompt
    assert "Testability" in prompt
    assert "FastAPI" in prompt

def test_run_llm_evaluation_skips_without_key():
    spec = _make_spec(["User can login (returns 200)"])
    # With no API key, should return empty report with a note, not raise
    with patch.dict("os.environ", {}, clear=True):
        report = run_llm_evaluation(spec)
    assert isinstance(report, ValidationReport)

def test_run_llm_evaluation_calls_api_per_category():
    spec = _make_spec([
        "User can login (returns 200 with JWT)",
        "System returns 401 on invalid credentials",
    ], category="Authentication")
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=(
        "Testability: 9\nAtomicity: 9\nSpecificity: 8\nErrorCoverage: 8\n"
        "Verdict: APPROVE\nFeedback: Good category."
    ))]
    with patch("anthropic.Anthropic") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create.return_value = mock_response
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            report = run_llm_evaluation(spec)
    assert isinstance(report, ValidationReport)
    assert "Authentication" in report.category_scores
    assert report.category_scores["Authentication"] >= 7.0
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/spec/test_validator.py -k "llm or evaluator" -v 2>&1 | head -20
```
Expected: `ImportError: cannot import name 'SpecEvaluator'`

- [ ] **Step 3: Add Layer 2 to `validator.py`**

Append to `claw_forge/spec/validator.py` after `run_coverage_checks`:

```python
# ---------------------------------------------------------------------------
# Layer 2 — adversarial LLM evaluation (per-category)
# ---------------------------------------------------------------------------

import os
import re as _re

# Spec-specific grading dimensions (replaces code-oriented DIMENSIONS)
SPEC_DIMENSIONS = [
    # (name, weight, description)
    ("Testability",   3, "Can you write a pass/fail test for every bullet? "
                         "Each bullet must have a verifiable outcome."),
    ("Atomicity",     3, "Is each bullet one implementable unit? "
                         "No compound sequences. No 'and then' chains."),
    ("Specificity",   2, "Does each bullet name concrete things: HTTP status, "
                         "field names, UI elements, error messages?"),
    ("ErrorCoverage", 2, "Does the category cover error and edge cases, "
                         "not just the happy path?"),
]

_TOTAL_WEIGHT = sum(w for _, w, _ in SPEC_DIMENSIONS)


class SpecEvaluator:
    """Adversarial evaluator tuned for spec bullets (not code output).

    Adapted from the AdversarialEvaluator pattern in agent-harness-skills
    with spec-specific grading dimensions.

    Parameters
    ----------
    approve_threshold:
        Minimum weighted score (0-10) to APPROVE a category. Default: 7.0.
    """

    def __init__(self, approve_threshold: float = 7.0) -> None:
        self.approve_threshold = approve_threshold

    def grade(
        self,
        bullets: str,
        category: str,
        dimension_scores: dict[str, float],
        feedback: str = "",
    ) -> dict[str, Any]:
        """Compute weighted score and verdict from pre-parsed LLM dimension scores."""
        weighted_sum = 0.0
        breakdown: dict[str, float] = {}
        for name, weight, _ in SPEC_DIMENSIONS:
            raw = max(0.0, min(10.0, float(dimension_scores.get(name, 0.0))))
            contribution = raw * weight / _TOTAL_WEIGHT
            breakdown[name] = round(contribution, 2)
            weighted_sum += raw * weight
        score = round(weighted_sum / _TOTAL_WEIGHT, 2)
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
        """Build the adversarial evaluator prompt to send to a separate LLM call."""
        dim_block = "\n".join(
            f"- **{name}** (weight ×{weight}): {desc}"
            for name, weight, desc in SPEC_DIMENSIONS
        )
        stack_line = f"\nTech stack: {tech_stack}" if tech_stack else ""
        return f"""\
You are an ADVERSARIAL SPEC EVALUATOR. Your job is to find bullets that will
cause agent failures downstream. You are evaluating work by a DIFFERENT agent.
Be skeptical. Grade harshly. A bullet that seems "good enough" is not good enough
if an agent could implement it incorrectly and have no way to know.

## Context
Category: {category}{stack_line}

## Grading Dimensions (score each 0-10)

{dim_block}

## Calibration

### Strong category (score ≈ 8.5)
Bullets:
  - User can login with email and password (returns 200 with access_token and refresh_token)
  - System returns 401 with "Invalid credentials" when password is wrong
  - System returns 401 with "Account not found" when email does not exist
  - User can logout and system invalidates the refresh_token in the database
Scores: Testability 9, Atomicity 9, Specificity 8, ErrorCoverage 9
Feedback: Excellent. Every bullet is testable, atomic, specific. Error cases present.

### Weak category (score ≈ 3.5)
Bullets:
  - User can manage their account
  - System handles auth stuff
Scores: Testability 2, Atomicity 5, Specificity 2, ErrorCoverage 1
Feedback: Untestable and vague. "manage" and "stuff" give agents no direction.
Missing all error cases.

## Bullets to Evaluate

Category: {category}
```
{bullets}
```

Score each dimension 0-10. Be adversarial.
Approval threshold: {self.approve_threshold}/10.

Respond in EXACTLY this format (no extra text):
Testability: <score>
Atomicity: <score>
Specificity: <score>
ErrorCoverage: <score>
Verdict: APPROVE | REQUEST_CHANGES
Feedback: <specific actionable critique, cite actual bullets>
"""

    def parse_llm_response(self, text: str) -> tuple[dict[str, float], str]:
        """Parse dimension scores and feedback from LLM evaluator response."""
        scores: dict[str, float] = {}
        feedback = ""
        for name, _, _ in SPEC_DIMENSIONS:
            m = _re.search(rf"^{name}:\s*(\d+(?:\.\d+)?)", text, _re.MULTILINE | _re.IGNORECASE)
            if m:
                scores[name] = float(m.group(1))
        m_fb = _re.search(r"^Feedback:\s*(.+)", text, _re.MULTILINE | _re.DOTALL)
        if m_fb:
            feedback = m_fb.group(1).strip()
        return scores, feedback


def run_llm_evaluation(
    spec: ProjectSpec,
    approve_threshold: float = 7.0,
    model: str = "claude-haiku-4-5-20251001",
) -> ValidationReport:
    """Layer 2: adversarial LLM evaluation per category.

    Requires ANTHROPIC_API_KEY to be set.  If the key is absent, returns
    an empty report with a warning issue so the caller can proceed gracefully.

    Uses Haiku by default — the evaluation prompt is structured enough that
    the cheaper model is sufficient; Opus/Sonnet are wasteful here.
    """
    report = ValidationReport()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        report.issues.append(ValidationIssue(
            severity=IssueSeverity.WARNING,
            layer=2,
            category="",
            bullet="",
            message="ANTHROPIC_API_KEY not set — Layer 2 LLM evaluation skipped.",
            suggestion="Set ANTHROPIC_API_KEY to enable adversarial per-category evaluation.",
        ))
        return report

    try:
        import anthropic as _anthropic
    except ImportError:
        return report

    client = _anthropic.Anthropic(api_key=api_key)
    evaluator = SpecEvaluator(approve_threshold=approve_threshold)

    # Group features by category
    categories: dict[str, list[str]] = {}
    for feat in spec.features:
        categories.setdefault(feat.category, []).append(feat.description)

    tech_stack = spec.tech_stack.raw or (
        f"{spec.tech_stack.frontend_framework} + {spec.tech_stack.backend_runtime}"
    ).strip(" +")

    for category, bullets in categories.items():
        bullet_block = "\n".join(f"  - {b}" for b in bullets)
        prompt = evaluator.build_evaluator_prompt(bullet_block, category, tech_stack)

        try:
            response = client.messages.create(
                model=model,
                max_tokens=512,
                system="You are an adversarial spec evaluator. Follow the output format exactly.",
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = response.content[0].text
        except Exception as exc:
            report.issues.append(ValidationIssue(
                severity=IssueSeverity.WARNING,
                layer=2,
                category=category,
                bullet="",
                message=f"LLM evaluation failed for category '{category}': {exc}",
            ))
            continue

        dimension_scores, feedback = evaluator.parse_llm_response(raw_text)
        result = evaluator.grade(bullet_block, category, dimension_scores, feedback)
        report.category_scores[category] = result["score"]

        if result["verdict"] == "REQUEST_CHANGES":
            report.issues.append(ValidationIssue(
                severity=IssueSeverity.WARNING,
                layer=2,
                category=category,
                bullet="",
                message=(
                    f"Category '{category}' scored {result['score']:.1f}/10 "
                    f"(threshold {approve_threshold}). {feedback}"
                ),
                suggestion=(
                    f"Improve bullets in '{category}': add error cases, "
                    "make outcomes concrete, split compound bullets."
                ),
            ))

    return report
```

- [ ] **Step 4: Run Layer 2 tests**

```bash
uv run pytest tests/spec/test_validator.py -k "llm or evaluator" -v
```
Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/spec/validator.py tests/spec/test_validator.py
git commit -m "feat(spec): add validator Layer 2 — adversarial LLM evaluation per category"
```

---

## Task 4: `validate_spec` entry point and full-spec runner

**Files:**
- Modify: `claw_forge/spec/validator.py` (add `validate_spec` function)
- Modify: `tests/spec/test_validator.py` (add integration test)

- [ ] **Step 1: Write failing test**

Append to `tests/spec/test_validator.py`:

```python
from claw_forge.spec.validator import validate_spec

def test_validate_spec_returns_combined_report():
    spec = _make_spec([
        "User can register with email and password (returns 201 with user_id)",
        "System returns 409 when email is already registered",
        "register and login and do everything",  # compound → Layer 1 ERROR
    ])
    spec.api_endpoints = {"Auth": ["POST /api/payments/charge - Charge"]}  # → Layer 3 gap
    spec.database_tables = {}

    # Layer 2 skipped (no API key in test env)
    report = validate_spec(spec, run_llm=False)
    assert report.error_count >= 1           # compound bullet
    layer3 = report.layer_issues(3)
    assert len(layer3) >= 1                  # missing endpoint coverage
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/spec/test_validator.py::test_validate_spec_returns_combined_report -v
```
Expected: `ImportError: cannot import name 'validate_spec'`

- [ ] **Step 3: Add `validate_spec` to `validator.py`**

Append to the end of `claw_forge/spec/validator.py`:

```python
# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate_spec(
    spec: ProjectSpec,
    run_llm: bool = True,
    approve_threshold: float = 7.0,
    llm_model: str = "claude-haiku-4-5-20251001",
) -> ValidationReport:
    """Run all three validation layers and return a merged ValidationReport.

    Parameters
    ----------
    spec:
        Parsed ProjectSpec (from ProjectSpec.from_file()).
    run_llm:
        Whether to run Layer 2 adversarial LLM evaluation.
        If False (or ANTHROPIC_API_KEY is absent), Layer 2 is skipped.
    approve_threshold:
        Minimum category score for Layer 2 APPROVE. Default: 7.0.
    llm_model:
        Model to use for Layer 2. Default: Haiku (fast + cheap).
    """
    merged = ValidationReport()

    # Layer 1 — structural checks
    l1 = run_structural_checks(spec)
    merged.issues.extend(l1.issues)

    # Layer 2 — adversarial LLM (optional)
    if run_llm:
        l2 = run_llm_evaluation(spec, approve_threshold=approve_threshold, model=llm_model)
        merged.issues.extend(l2.issues)
        merged.category_scores.update(l2.category_scores)

    # Layer 3 — coverage gaps
    l3 = run_coverage_checks(spec)
    merged.issues.extend(l3.issues)

    return merged
```

- [ ] **Step 4: Run the integration test**

```bash
uv run pytest tests/spec/test_validator.py::test_validate_spec_returns_combined_report -v
```
Expected: PASS.

- [ ] **Step 5: Run the full test suite**

```bash
uv run pytest tests/spec/test_validator.py -v
```
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add claw_forge/spec/validator.py tests/spec/test_validator.py
git commit -m "feat(spec): add validate_spec() entry point combining all 3 layers"
```

---

## Task 5: `validate-spec` CLI command

**Files:**
- Modify: `claw_forge/cli.py`

The new command goes after the `plan` command (around line 2144 in current file).

- [ ] **Step 1: Write failing CLI test**

Append to `tests/spec/test_validator.py`:

```python
from typer.testing import CliRunner
from claw_forge.cli import app
import tempfile, os

def test_validate_spec_cli_passes_on_good_spec(tmp_path):
    spec_content = (
        Path(__file__).parent.parent.parent
        / "claw_forge" / "spec" / "app_spec.template.xml"
    ).read_text()
    spec_file = tmp_path / "app_spec.txt"
    spec_file.write_text(spec_content)

    runner = CliRunner()
    result = runner.invoke(app, ["validate-spec", str(spec_file), "--no-llm"])
    # Template has well-formed bullets — should pass structural checks
    assert result.exit_code == 0
    assert "Layer 1" in result.output

def test_validate_spec_cli_fails_on_bad_spec(tmp_path):
    bad_spec = textwrap.dedent("""\
        <project_specification>
          <project_name>bad</project_name>
          <overview>test</overview>
          <core_features>
            <category name="Auth">
              - register and login and do stuff etc
            </category>
          </core_features>
        </project_specification>
    """)
    spec_file = tmp_path / "bad_spec.txt"
    spec_file.write_text(bad_spec)

    runner = CliRunner()
    result = runner.invoke(app, ["validate-spec", str(spec_file), "--no-llm"])
    assert result.exit_code == 1
    assert "error" in result.output.lower() or "ERROR" in result.output
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/spec/test_validator.py -k "cli" -v 2>&1 | head -20
```
Expected: `UsageError` or `No such command 'validate-spec'`

- [ ] **Step 3: Add `validate_spec_cmd` to `cli.py`**

Find the `add` command in `cli.py` (around line 2145) and insert the new command **before** it:

```python
@app.command("validate-spec")
def validate_spec_cmd(
    spec: str = typer.Argument(..., help="Path to app_spec.txt or additions_spec.xml."),
    no_llm: bool = typer.Option(
        False, "--no-llm",
        help="Skip Layer 2 adversarial LLM evaluation (Layer 1 + Layer 3 only).",
    ),
    threshold: float = typer.Option(
        7.0, "--threshold", "-t",
        help="Layer 2 LLM approval threshold (0-10). Default: 7.0.",
    ),
    model: str = typer.Option(
        "claude-haiku-4-5-20251001", "--model", "-m",
        help="Model for Layer 2 LLM evaluation. Default: Haiku (fast + cheap).",
    ),
) -> None:
    """Validate a spec file before planning.

    Runs 3 validation layers and exits non-zero if errors are found:

      Layer 1 — Structural: action verbs, measurable outcomes, atomicity, vagueness
      Layer 2 — LLM:        adversarial per-category scoring (requires ANTHROPIC_API_KEY)
      Layer 3 — Coverage:   cross-references endpoints and tables against bullets

    Examples:

        # Full validation (all 3 layers)
        claw-forge validate-spec app_spec.txt

        # Skip LLM layer (zero cost, structural + coverage only)
        claw-forge validate-spec app_spec.txt --no-llm

        # Custom threshold for LLM layer
        claw-forge validate-spec app_spec.txt --threshold 8.0
    """
    from claw_forge.spec.parser import ProjectSpec
    from claw_forge.spec.validator import IssueSeverity, validate_spec

    spec_path = Path(spec)
    if not spec_path.exists():
        console.print(f"[red]Spec file not found: {spec_path}[/red]")
        raise typer.Exit(1)

    try:
        parsed = ProjectSpec.from_file(spec_path)
    except Exception as exc:
        console.print(f"[red]Failed to parse spec: {exc}[/red]")
        raise typer.Exit(1) from exc

    console.print(f"\n[bold]Validating:[/bold] {spec_path.name}")
    console.print(f"  Features: {len(parsed.features)}")
    console.print(f"  Categories: {len({f.category for f in parsed.features})}")
    console.print(f"  Endpoints: {sum(len(v) for v in parsed.api_endpoints.values())}")
    console.print(f"  Tables: {len(parsed.database_tables)}")
    console.print()

    run_llm = not no_llm
    if run_llm:
        console.print("[dim]Running Layer 2 LLM evaluation (--no-llm to skip)...[/dim]")

    report = validate_spec(
        parsed,
        run_llm=run_llm,
        approve_threshold=threshold,
        llm_model=model,
    )

    # ── Layer 1 summary ─────────────────────────────────────────────────────
    l1 = report.layer_issues(1)
    l1_errors = [i for i in l1 if i.severity == IssueSeverity.ERROR]
    l1_warnings = [i for i in l1 if i.severity == IssueSeverity.WARNING]
    status_l1 = "[red]FAIL[/red]" if l1_errors else "[green]PASS[/green]"
    console.print(f"Layer 1 (Structural)  {status_l1}  "
                  f"{len(l1_errors)} errors, {len(l1_warnings)} warnings")
    for issue in l1_errors:
        console.print(f"  [red]✗[/red] [{issue.category}] {issue.message}")
        if issue.suggestion:
            console.print(f"    → {issue.suggestion}")
        console.print(f"    Bullet: \"{issue.bullet[:80]}\"")
    for issue in l1_warnings[:5]:  # cap warnings shown inline
        console.print(f"  [yellow]⚠[/yellow] [{issue.category}] {issue.message}")
    if len(l1_warnings) > 5:
        console.print(f"  [dim]... and {len(l1_warnings) - 5} more warnings[/dim]")

    # ── Layer 2 summary ─────────────────────────────────────────────────────
    l2 = report.layer_issues(2)
    if run_llm and not any(
        "skipped" in i.message.lower() for i in l2
    ):
        l2_fails = [i for i in l2 if i.severity == IssueSeverity.ERROR or
                    (i.severity == IssueSeverity.WARNING and i.category)]
        status_l2 = "[red]FAIL[/red]" if l2_fails else "[green]PASS[/green]"
        console.print(f"\nLayer 2 (LLM eval)    {status_l2}")
        for cat, score in report.category_scores.items():
            mark = "[green]✓[/green]" if score >= threshold else "[yellow]⚠[/yellow]"
            console.print(f"  {mark} {cat}: {score:.1f}/10")
        for issue in l2_fails:
            console.print(f"  [yellow]⚠[/yellow] {issue.message}")
    elif not run_llm:
        console.print("\nLayer 2 (LLM eval)    [dim]skipped (--no-llm)[/dim]")
    else:
        for issue in l2:
            console.print(f"\n  [dim]{issue.message}[/dim]")

    # ── Layer 3 summary ─────────────────────────────────────────────────────
    l3 = report.layer_issues(3)
    status_l3 = "[yellow]GAPS[/yellow]" if l3 else "[green]PASS[/green]"
    console.print(f"\nLayer 3 (Coverage)    {status_l3}  {len(l3)} gaps")
    for issue in l3:
        console.print(f"  [yellow]⚠[/yellow] {issue.message}")
        if issue.suggestion:
            console.print(f"    → {issue.suggestion}")

    # ── Final verdict ────────────────────────────────────────────────────────
    console.print()
    if report.passed:
        console.print(
            f"[bold green]✅ Spec passed validation[/bold green]  "
            f"({report.warning_count} warnings)"
        )
        console.print(
            "\n  Next: [bold]claw-forge plan " + spec + "[/bold]"
        )
    else:
        console.print(
            f"[bold red]✗ Spec has {report.error_count} error(s) "
            f"— fix before running claw-forge plan[/bold red]"
        )
        raise typer.Exit(1)
```

- [ ] **Step 4: Run CLI tests**

```bash
uv run pytest tests/spec/test_validator.py -k "cli" -v
```
Expected: both CLI tests pass.

- [ ] **Step 5: Run the full validator test suite**

```bash
uv run pytest tests/spec/test_validator.py -v
```
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add claw_forge/cli.py tests/spec/test_validator.py
git commit -m "feat(cli): add validate-spec command — 3-layer pre-plan quality gate"
```

---

## Task 6: Coverage gate and lint/type checks

**Files:**
- No new files — verify existing CI gates pass

- [ ] **Step 1: Run full test suite with coverage**

```bash
uv run pytest tests/ -q --cov=claw_forge --cov-report=term-missing 2>&1 | tail -20
```
Expected: coverage >= 90%. If below, add missing test cases for uncovered branches in `validator.py`.

- [ ] **Step 2: Run ruff lint**

```bash
uv run ruff check claw_forge/spec/validator.py tests/spec/test_validator.py
```
Expected: no errors. Fix any with `uv run ruff check --fix`.

- [ ] **Step 3: Run mypy**

```bash
uv run mypy claw_forge/spec/validator.py --ignore-missing-imports
```
Expected: no errors.

- [ ] **Step 4: Final commit**

```bash
git add -u
git commit -m "chore(spec): all tests passing, lint clean, coverage gate met"
```

---

## Self-Review

**Spec coverage check:**
- ✅ Layer 1 structural rules: `check_starts_with_action_verb`, `check_has_measurable_outcome`, `check_is_atomic`, `check_not_too_vague`
- ✅ Layer 2 adversarial LLM per category: `SpecEvaluator`, `run_llm_evaluation`
- ✅ Layer 3 coverage gaps: `run_coverage_checks`
- ✅ Combined entry point: `validate_spec`
- ✅ CLI command: `validate-spec` with `--no-llm`, `--threshold`, `--model`
- ✅ Graceful degradation: Layer 2 skips cleanly if `ANTHROPIC_API_KEY` is absent
- ✅ Exit code 1 on errors (CI-compatible)

**Placeholder scan:** No TBD, TODO, or "similar to" references. All code blocks complete.

**Type consistency:**
- `ValidationIssue.layer` is `int` throughout (1, 2, 3)
- `ValidationReport.category_scores` is `dict[str, float]` — set in `run_llm_evaluation`, read in CLI
- `SpecEvaluator.grade()` returns `dict[str, Any]` — consumed only in `run_llm_evaluation`
- `validate_spec()` returns `ValidationReport` — consumed in CLI command
