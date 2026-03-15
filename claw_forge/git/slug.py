"""Centralized slug generation for git branch names.

All ad-hoc slug patterns in the codebase should use these two functions
instead of inline regex so branch naming stays consistent.
"""

from __future__ import annotations

import re

# Leading action verbs stripped from feature descriptions before slugifying.
# These read awkwardly in branch names: feat/auth-add-jwt is worse than feat/auth-jwt.
_STRIP_VERBS: frozenset[str] = frozenset({
    "add", "allow", "apply", "build", "configure", "convert", "create",
    "define", "delete", "display", "enable", "ensure", "extend", "fetch",
    "fix", "generate", "handle", "implement", "improve", "initialize",
    "integrate", "introduce", "load", "make", "manage", "migrate",
    "process", "provide", "refactor", "remove", "render", "replace",
    "setup", "set", "show", "support", "update", "use", "write",
})

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_MULTI_DASH = re.compile(r"-{2,}")


def make_slug(text: str, *, max_len: int = 40) -> str:
    """Turn *text* into a git-safe slug, stripping leading action verbs.

    >>> make_slug("Add JWT authentication")
    'jwt-authentication'
    >>> make_slug("Implement user registration flow", max_len=20)
    'user-registration-fl'
    """
    words = _NON_ALNUM.sub(" ", text.lower()).split()
    # Drop consecutive leading verbs so "Add and implement X" → "x"
    while words and words[0] in _STRIP_VERBS:
        words.pop(0)
    slug = "-".join(words)
    slug = _MULTI_DASH.sub("-", slug).strip("-")
    return slug[:max_len].rstrip("-")


def make_branch_name(
    description: str | None,
    category: str | None,
    plugin_name: str = "feat",
    *,
    prefix: str = "feat",
    max_len: int = 55,
) -> str:
    """Build a semantic branch name from category + description.

    Format: ``{prefix}/{category_slug}-{description_slug}``

    Falls back to *plugin_name* when *category* is absent.  If neither
    *description* nor *category* yields anything meaningful the function
    returns ``{prefix}/{plugin_name}``.

    >>> make_branch_name("Add JWT authentication", "auth")
    'feat/auth-jwt-authentication'
    >>> make_branch_name("Fix Stripe webhook timeout", None, "fix", prefix="fix")
    'fix/fix-stripe-webhook-timeout'
    >>> make_branch_name(None, "payments")
    'feat/payments'
    """
    # Slugify category (keep short so description has room)
    cat_raw = category or plugin_name or "feat"
    cat_slug = _NON_ALNUM.sub("-", cat_raw.lower()).strip("-")[:15]

    # Budget remaining chars for the description slug (-1 for the separator dash)
    desc_budget = max(10, max_len - len(cat_slug) - 1)
    desc_slug = make_slug(description, max_len=desc_budget) if description else ""

    if desc_slug:
        return f"{prefix}/{cat_slug}-{desc_slug}"
    return f"{prefix}/{cat_slug}"
