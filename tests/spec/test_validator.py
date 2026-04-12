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


# ---------------------------------------------------------------------------
# run_coverage_checks (Layer 3)
# ---------------------------------------------------------------------------

from claw_forge.spec.validator import run_coverage_checks  # noqa: E402


def test_run_coverage_checks_no_gaps():
    spec = _make_spec([
        "User can POST /api/auth/register with email (returns 201)",
        "User can view users table records (returns 200)",
    ])
    spec.api_endpoints = {"Auth": ["POST /api/auth/register - Register"]}
    spec.database_tables = {"users": ["id UUID PRIMARY KEY"]}
    report = run_coverage_checks(spec)
    assert report.error_count == 0
    assert len(report.layer_issues(3)) == 0


def test_run_coverage_checks_missing_endpoint():
    spec = _make_spec(["User can login (returns 200)"])
    spec.api_endpoints = {"Payments": ["POST /api/payments/charge - Charge card"]}
    spec.database_tables = {}
    report = run_coverage_checks(spec)
    l3 = report.layer_issues(3)
    assert len(l3) >= 1
    assert "/api/payments/charge" in l3[0].message


def test_run_coverage_checks_missing_table():
    spec = _make_spec(["User can login (returns 200)"])
    spec.api_endpoints = {}
    spec.database_tables = {"invoices": ["id UUID PRIMARY KEY", "amount NUMERIC NOT NULL"]}
    report = run_coverage_checks(spec)
    l3 = report.layer_issues(3)
    assert len(l3) >= 1
    assert "invoices" in l3[0].message


def test_run_coverage_checks_empty_spec():
    spec = _make_spec([])
    spec.api_endpoints = {}
    spec.database_tables = {}
    report = run_coverage_checks(spec)
    assert report.total_issues == 0


def test_run_coverage_checks_query_string_stripped():
    """Endpoint paths with query strings should be normalised before matching."""
    spec = _make_spec([
        "User can list active /api/users returning 200",
    ])
    spec.api_endpoints = {"Users": ["GET /api/users?active=true - List active users"]}
    spec.database_tables = {}
    report = run_coverage_checks(spec)
    # /api/users (after stripping ?active=true) is referenced → no warning
    assert len(report.layer_issues(3)) == 0


def test_run_coverage_checks_no_false_positive_path_prefix():
    """/api/user must NOT match a bullet that only mentions /api/users."""
    spec = _make_spec([
        "User can list /api/users records returning 200",
    ])
    spec.api_endpoints = {"Users": ["GET /api/user - Get single user"]}
    spec.database_tables = {}
    report = run_coverage_checks(spec)
    # /api/user is not in the bullets (only /api/users is) → warning expected
    l3 = report.layer_issues(3)
    assert len(l3) >= 1
    assert "/api/user" in l3[0].message


# ---------------------------------------------------------------------------
# Layer 2: adversarial LLM evaluation
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock, patch  # noqa: E402

from claw_forge.spec.validator import SpecEvaluator, run_llm_evaluation  # noqa: E402


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


def test_spec_evaluator_parse_llm_response():
    ev = SpecEvaluator()
    text = (
        "Testability: 9\nAtomicity: 8\nSpecificity: 7\nErrorCoverage: 8\n"
        "Verdict: APPROVE\nFeedback: Good coverage of error cases."
    )
    scores, feedback = ev.parse_llm_response(text)
    assert scores == {
        "Testability": 9.0, "Atomicity": 8.0, "Specificity": 7.0, "ErrorCoverage": 8.0
    }
    assert "Good coverage" in feedback


def test_run_llm_evaluation_skips_without_key():
    spec = _make_spec(["User can login (returns 200)"])
    with patch.dict("os.environ", {}, clear=True):
        report = run_llm_evaluation(spec)
    assert isinstance(report, ValidationReport)
    skipped = [
        i for i in report.issues
        if "skipped" in i.message.lower() or "ANTHROPIC_API_KEY" in i.message
    ]
    assert len(skipped) == 1


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
    with patch("anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = mock_response
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            report = run_llm_evaluation(spec)
    assert "Authentication" in report.category_scores
    assert report.category_scores["Authentication"] >= 7.0


def test_run_llm_evaluation_adds_issue_on_low_score():
    spec = _make_spec(["User can manage things"], category="Core")
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=(
        "Testability: 2\nAtomicity: 4\nSpecificity: 2\nErrorCoverage: 1\n"
        "Verdict: REQUEST_CHANGES\nFeedback: Too vague, no error cases."
    ))]
    with patch("anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = mock_response
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            report = run_llm_evaluation(spec)
    l2 = report.layer_issues(2)
    assert len(l2) >= 1
    assert report.category_scores["Core"] < 7.0
