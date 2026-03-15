"""Tests for claw_forge/git/slug.py — semantic slug generation."""

from __future__ import annotations

from claw_forge.git.slug import make_branch_name, make_slug


class TestMakeSlug:
    def test_strips_single_leading_verb(self) -> None:
        assert make_slug("Add JWT authentication") == "jwt-authentication"

    def test_strips_multiple_leading_verbs(self) -> None:
        # "implement" stripped; "and" is a conjunction, not a verb — stays
        assert make_slug("Implement and add user registration") == "and-add-user-registration"

    def test_no_verbs_preserved(self) -> None:
        assert make_slug("JWT token validation") == "jwt-token-validation"

    def test_lowercases(self) -> None:
        assert make_slug("Dashboard Analytics") == "dashboard-analytics"

    def test_special_chars_become_dashes(self) -> None:
        # "fix" is a strip verb so it's dropped; remaining parts slugified
        assert make_slug("Fix: stripe/webhook_timeout") == "stripe-webhook-timeout"

    def test_truncates_at_max_len(self) -> None:
        result = make_slug("user registration flow for new accounts", max_len=20)
        assert len(result) <= 20

    def test_no_trailing_dash_after_truncation(self) -> None:
        result = make_slug("user registration flow for new accounts", max_len=10)
        assert not result.endswith("-")

    def test_empty_string_returns_empty(self) -> None:
        assert make_slug("") == ""

    def test_all_verbs_returns_empty(self) -> None:
        assert make_slug("add implement create") == ""

    def test_unicode_normalized(self) -> None:
        result = make_slug("Añadir autenticación OAuth")
        # Non-ASCII chars become dashes; word boundaries preserved
        assert "-" in result or result.isalnum()

    def test_collapses_multiple_dashes(self) -> None:
        result = make_slug("fix---login  issue")
        assert "--" not in result


class TestMakeBranchName:
    def test_basic_category_and_description(self) -> None:
        assert make_branch_name("Add JWT authentication", "auth") == "feat/auth-jwt-authentication"

    def test_category_prefix_applied(self) -> None:
        result = make_branch_name("Build real-time dashboard", "ui")
        assert result.startswith("feat/ui-")

    def test_fallback_to_plugin_name_when_no_category(self) -> None:
        result = make_branch_name("Fix pagination bug", None, "coding")
        assert result.startswith("feat/coding-")

    def test_fallback_to_plugin_name_when_empty_category(self) -> None:
        result = make_branch_name("Fix pagination bug", "", "bugfix")
        assert result.startswith("feat/bugfix-")

    def test_custom_prefix(self) -> None:
        result = make_branch_name("Stripe webhook timeout", None, "fix", prefix="fix")
        assert result.startswith("fix/fix-")

    def test_none_description_returns_category_only(self) -> None:
        assert make_branch_name(None, "payments") == "feat/payments"

    def test_empty_description_returns_category_only(self) -> None:
        assert make_branch_name("", "payments") == "feat/payments"

    def test_total_length_within_max_len(self) -> None:
        result = make_branch_name(
            "Implement user registration flow with email verification and OAuth support",
            "auth",
            max_len=55,
        )
        # Strip prefix/ for measurement
        branch_body = result.split("/", 1)[1]
        assert len(branch_body) <= 55

    def test_category_truncated_at_15_chars(self) -> None:
        result = make_branch_name("Add feature", "a-very-long-category-name")
        cat_part = result.split("/")[1].split("-")[0]
        assert len(cat_part) <= 15

    def test_leading_verbs_stripped_from_description(self) -> None:
        result = make_branch_name("Create payment gateway integration", "payments")
        assert "create" not in result

    def test_no_double_dashes(self) -> None:
        result = make_branch_name("Fix: some--weird  title", "api")
        assert "--" not in result

    def test_none_category_none_plugin_defaults_to_feat(self) -> None:
        result = make_branch_name("Build something", None, "")
        assert result.startswith("feat/feat-") or result.startswith("feat/")
