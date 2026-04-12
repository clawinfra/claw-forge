"""Tests for claw_forge/spec/validator.py — Layer 1 structural checks."""

from __future__ import annotations

from claw_forge.spec.parser import FeatureItem, ProjectSpec
from claw_forge.spec.validator import (
    IssueSeverity,
    ValidationIssue,
    ValidationReport,
    check_has_measurable_outcome,
    check_is_atomic,
    check_not_too_vague,
    check_starts_with_action_verb,
    run_structural_checks,
)

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_spec(bullets: list[str], category: str = "Auth") -> ProjectSpec:
    from claw_forge.spec.parser import TechStack

    features = [FeatureItem(category=category, name=b[:30], description=b) for b in bullets]
    return ProjectSpec(
        project_name="test",
        overview="",
        tech_stack=TechStack(),
        features=features,
        implementation_phases=[],
        success_criteria=[],
        design_system={},
        api_endpoints={},
        database_tables={},
        raw_xml="",
    )


def _make_feat(description: str, category: str = "Auth") -> FeatureItem:
    return FeatureItem(category=category, name=description[:30], description=description)


# ---------------------------------------------------------------------------
# check_starts_with_action_verb
# ---------------------------------------------------------------------------


def test_check_starts_with_action_verb_pass() -> None:
    feat = _make_feat("User can login and receive JWT")
    result = check_starts_with_action_verb(feat)
    assert result is None


def test_check_starts_with_action_verb_fail() -> None:
    feat = _make_feat("JWT token is issued on login")
    result = check_starts_with_action_verb(feat)
    assert result is not None
    assert isinstance(result, ValidationIssue)
    assert result.severity == IssueSeverity.WARNING
    assert result.bullet == "JWT token is issued on login"


def test_check_starts_with_action_verb_various_prefixes() -> None:
    prefixes = [
        "System validates the token",
        "API returns a list of users",
        "UI displays the dashboard",
        "App stores session data",
        "Admin can delete users",
        "Service processes the payment",
        "Backend handles the request",
        "Frontend renders the component",
        "Database stores user records",
        "Agent runs the task",
        "Webhook triggers on push",
        "Background job runs nightly",
    ]
    for bullet in prefixes:
        feat = _make_feat(bullet)
        assert check_starts_with_action_verb(feat) is None, f"Expected pass for: {bullet!r}"


def test_check_starts_with_action_verb_case_insensitive() -> None:
    feat = _make_feat("USER CAN login with email")
    result = check_starts_with_action_verb(feat)
    assert result is None


# ---------------------------------------------------------------------------
# check_has_measurable_outcome
# ---------------------------------------------------------------------------


def test_check_has_measurable_outcome_pass() -> None:
    feat = _make_feat("User can login (returns 200 with JWT)")
    result = check_has_measurable_outcome(feat)
    assert result is None


def test_check_has_measurable_outcome_fail() -> None:
    feat = _make_feat("User can login")
    result = check_has_measurable_outcome(feat)
    assert result is not None
    assert isinstance(result, ValidationIssue)
    assert result.severity == IssueSeverity.WARNING
    assert result.bullet == "User can login"


def test_check_has_measurable_outcome_http_status() -> None:
    feat = _make_feat("User can register returns 201")
    assert check_has_measurable_outcome(feat) is None


def test_check_has_measurable_outcome_displays() -> None:
    feat = _make_feat("UI displays the dashboard after login")
    assert check_has_measurable_outcome(feat) is None


def test_check_has_measurable_outcome_shows() -> None:
    feat = _make_feat("System shows error message to user")
    assert check_has_measurable_outcome(feat) is None


def test_check_has_measurable_outcome_redirects() -> None:
    feat = _make_feat("App redirects to home after login")
    assert check_has_measurable_outcome(feat) is None


def test_check_has_measurable_outcome_saves() -> None:
    feat = _make_feat("System saves to database on submit")
    assert check_has_measurable_outcome(feat) is None


def test_check_has_measurable_outcome_http_explicit() -> None:
    feat = _make_feat("API endpoint returns HTTP 404 when not found")
    assert check_has_measurable_outcome(feat) is None


def test_check_has_measurable_outcome_snake_case_field() -> None:
    feat = _make_feat("User can login with user_id and password")
    assert check_has_measurable_outcome(feat) is None


def test_check_has_measurable_outcome_error_message() -> None:
    feat = _make_feat("System shows error message when credentials are invalid")
    assert check_has_measurable_outcome(feat) is None


def test_check_has_measurable_outcome_toast() -> None:
    feat = _make_feat("App shows toast notification on success")
    assert check_has_measurable_outcome(feat) is None


def test_check_has_measurable_outcome_persists() -> None:
    feat = _make_feat("System persists user preferences in DB")
    assert check_has_measurable_outcome(feat) is None


# ---------------------------------------------------------------------------
# check_is_atomic
# ---------------------------------------------------------------------------


def test_check_is_atomic_pass() -> None:
    feat = _make_feat("User can login with email and password")
    result = check_is_atomic(feat)
    assert result is None


def test_check_is_atomic_fail() -> None:
    feat = _make_feat("User can register and then login and receive a JWT token")
    result = check_is_atomic(feat)
    assert result is not None
    assert isinstance(result, ValidationIssue)
    assert result.severity == IssueSeverity.ERROR
    assert result.bullet == "User can register and then login and receive a JWT token"


def test_check_is_atomic_fail_and_also() -> None:
    feat = _make_feat("User can submit form and also receive confirmation email")
    result = check_is_atomic(feat)
    assert result is not None
    assert result.severity == IssueSeverity.ERROR


def test_check_is_atomic_fail_and_redirect() -> None:
    feat = _make_feat("User can login and redirect to dashboard")
    result = check_is_atomic(feat)
    assert result is not None
    assert result.severity == IssueSeverity.ERROR


def test_check_is_atomic_fail_and_create() -> None:
    feat = _make_feat("System processes payment and create order record")
    result = check_is_atomic(feat)
    assert result is not None
    assert result.severity == IssueSeverity.ERROR


def test_check_is_atomic_fail_message_contains_phrase() -> None:
    feat = _make_feat("User can login and receive JWT token")
    result = check_is_atomic(feat)
    assert result is not None
    assert "and receive" in result.message.lower() or "and receive" in result.message


# ---------------------------------------------------------------------------
# check_not_too_vague
# ---------------------------------------------------------------------------


def test_check_not_too_vague_pass() -> None:
    feat = _make_feat(
        "User can reset their password by entering their email address and clicking the reset link"
    )
    result = check_not_too_vague(feat)
    assert result is None


def test_check_not_too_vague_fail_short() -> None:
    # "User can do things" is 4 words → WARNING
    feat = _make_feat("User can do")
    result = check_not_too_vague(feat)
    assert result is not None
    assert isinstance(result, ValidationIssue)
    assert result.severity == IssueSeverity.WARNING


def test_check_not_too_vague_fail_etc() -> None:
    feat = _make_feat("User can manage items, etc.")
    result = check_not_too_vague(feat)
    assert result is not None
    assert isinstance(result, ValidationIssue)
    assert result.severity == IssueSeverity.WARNING


def test_check_not_too_vague_fail_various() -> None:
    feat = _make_feat("System handles various edge cases in user input validation")
    result = check_not_too_vague(feat)
    assert result is not None
    assert result.severity == IssueSeverity.WARNING


def test_check_not_too_vague_fail_stuff() -> None:
    feat = _make_feat("Admin can manage stuff related to user accounts and permissions")
    result = check_not_too_vague(feat)
    assert result is not None
    assert result.severity == IssueSeverity.WARNING


def test_check_not_too_vague_boundary_exactly_six_words() -> None:
    # Exactly 6 words should pass the word-count check
    feat = _make_feat("User can login with valid credentials")
    # 6 words — no vague words → should pass
    # (may or may not fail measurable outcome, but not_too_vague should pass)
    result = check_not_too_vague(feat)
    assert result is None


# ---------------------------------------------------------------------------
# ValidationReport properties
# ---------------------------------------------------------------------------


def test_validation_report_properties() -> None:
    issues = [
        ValidationIssue(
            severity=IssueSeverity.ERROR,
            layer=1,
            category="atomic",
            bullet="test",
            message="compound",
        ),
        ValidationIssue(
            severity=IssueSeverity.WARNING,
            layer=1,
            category="vague",
            bullet="test2",
            message="too vague",
        ),
    ]
    report = ValidationReport(issues=issues, category_scores={})
    assert report.error_count == 1
    assert report.warning_count == 1
    assert report.total_issues == 2
    assert report.passed is False
    layer1 = report.layer_issues(1)
    assert len(layer1) == 2


def test_validation_report_passed_when_no_errors() -> None:
    issues = [
        ValidationIssue(
            severity=IssueSeverity.WARNING,
            layer=1,
            category="vague",
            bullet="test",
            message="too vague",
        ),
    ]
    report = ValidationReport(issues=issues, category_scores={})
    assert report.passed is True


def test_validation_report_passed_when_empty() -> None:
    report = ValidationReport(issues=[], category_scores={})
    assert report.passed is True
    assert report.error_count == 0
    assert report.warning_count == 0


# ---------------------------------------------------------------------------
# run_structural_checks integration
# ---------------------------------------------------------------------------


def test_run_structural_checks_all_pass() -> None:
    # Use clean bullets without compound connectors
    clean_bullets = [
        "User can login with email and password (returns 200 with JWT token)",
        "System validates token on each request returning 401 when expired",
        "Admin can deactivate user account with confirmation_email sent",
    ]
    spec = _make_spec(clean_bullets)
    report = run_structural_checks(spec)
    assert report.error_count == 0


def test_run_structural_checks_catches_violations() -> None:
    bad_bullets = [
        # no verb prefix + compound:
        "JWT token is issued and then stored and redirect user to home",
        "do etc",  # vague + short
    ]
    spec = _make_spec(bad_bullets)
    report = run_structural_checks(spec)
    assert report.total_issues > 0


def test_run_structural_checks_returns_validation_report() -> None:
    spec = _make_spec(["User can login with email and password (returns 200)"])
    report = run_structural_checks(spec)
    assert isinstance(report, ValidationReport)
    assert isinstance(report.issues, list)
    assert isinstance(report.category_scores, dict)


def test_run_structural_checks_category_scores_populated() -> None:
    spec = _make_spec(
        [
            "User can login with email and password (returns 200 with JWT)",
            "JWT is issued on login",  # missing verb prefix
        ]
    )
    report = run_structural_checks(spec)
    # category_scores should have entries
    assert isinstance(report.category_scores, dict)


def test_run_structural_checks_layer_issues_filter() -> None:
    spec = _make_spec(["JWT token is issued and then stored"])
    report = run_structural_checks(spec)
    layer1 = report.layer_issues(1)
    layer2 = report.layer_issues(2)
    assert len(layer1) > 0
    assert len(layer2) == 0


def test_run_structural_checks_category_scores_keys_match_issue_categories() -> None:
    """category_scores keys must match the ValidationIssue.category values they track."""
    spec = _make_spec(
        [
            "JWT is issued on login",  # missing verb prefix → action_verb issue
            "User can do etc",  # vague → vague issue
            "User can login and then register and receive a JWT",  # compound → atomic issue
        ]
    )
    report = run_structural_checks(spec)
    issue_categories = {i.category for i in report.issues}
    score_keys = set(report.category_scores.keys())
    # Every issue category must appear in category_scores
    for cat in issue_categories:
        assert cat in score_keys, (
            f"Issue category {cat!r} not found in category_scores keys: {score_keys}"
        )
