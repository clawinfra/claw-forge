"""Tests for claw_forge.github.models."""

from __future__ import annotations

import pytest

from claw_forge.github.models import GitHubContext, IssueSpec

# ── IssueSpec ─────────────────────────────────────────────────────────────────


def test_issue_spec_to_xml_contains_title() -> None:
    spec = IssueSpec(
        title="Add authentication",
        description="Implement OAuth2 login",
        comments=[],
        author="testuser",
        number=15,
        labels=["feature"],
    )

    xml = spec.to_xml()

    assert "Add authentication" in xml
    assert "OAuth2 login" in xml


def test_issue_spec_to_xml_escapes_special_chars() -> None:
    spec = IssueSpec(
        title="Fix <XSS> & injection",
        description='Use "safe" handling',
        comments=[],
        author="bob",
        number=1,
    )

    xml = spec.to_xml()

    assert "&lt;XSS&gt;" in xml
    assert "&amp;" in xml
    assert "&quot;safe&quot;" in xml


def test_issue_spec_to_xml_no_body() -> None:
    spec = IssueSpec(
        title="Bare issue",
        description="",
        comments=[],
        author="alice",
        number=2,
    )

    xml = spec.to_xml()

    assert "No description provided" in xml


def test_issue_spec_to_markdown_contains_title_and_desc() -> None:
    spec = IssueSpec(
        title="Add rate limiting",
        description="Use token-bucket algorithm",
        comments=["Please add Redis support"],
        author="alice",
        number=7,
        labels=["feature", "backend"],
    )

    md = spec.to_markdown_spec()

    assert "Add rate limiting" in md
    assert "token-bucket" in md
    assert "Redis support" in md
    assert "GitHub issue #7" in md


def test_issue_spec_to_markdown_no_comments() -> None:
    spec = IssueSpec(
        title="Simple task",
        description="Do something",
        comments=[],
        author="bob",
        number=3,
    )

    md = spec.to_markdown_spec()

    assert "Simple task" in md
    assert "Issue Comments" not in md


def test_issue_spec_to_markdown_with_labels() -> None:
    spec = IssueSpec(
        title="Add tests",
        description="Write pytest tests",
        comments=[],
        author="alice",
        number=5,
        labels=["testing", "priority-high"],
    )

    md = spec.to_markdown_spec()

    assert "testing" in md
    assert "priority-high" in md


def test_issue_spec_default_labels_is_empty() -> None:
    spec = IssueSpec(
        title="Quick fix",
        description="Fix typo",
        comments=[],
        author="alice",
        number=9,
    )

    assert spec.labels == []


# ── GitHubContext ─────────────────────────────────────────────────────────────


def test_github_context_is_frozen() -> None:
    ctx = GitHubContext(
        owner="clawinfra",
        repo="claw-forge",
        issue_number=15,
        token="ghp_test",
        branch_name="feat/github-15",
    )

    with pytest.raises((AttributeError, TypeError)):
        ctx.owner = "other"  # type: ignore[misc]


def test_github_context_fields() -> None:
    ctx = GitHubContext(
        owner="owner",
        repo="repo",
        issue_number=42,
        token="tok",
        branch_name="feat/github-42",
    )

    assert ctx.owner == "owner"
    assert ctx.repo == "repo"
    assert ctx.issue_number == 42
    assert ctx.token == "tok"
    assert ctx.branch_name == "feat/github-42"
