# Semantic Slug Naming for Feature Branches

**Date:** 2026-03-15
**Status:** Approved
**Scope:** `claw_forge/git/slug.py` + 3 call-site updates in `claw_forge/cli.py`

---

## Problem

Feature branches are currently named `feat/coding-a1b2c3d4` — a concatenation of the plugin name and a UUID fragment. This is opaque: it tells you nothing about what the feature does, making branch lists and `git log` outputs hard to scan.

Four separate ad-hoc slug patterns exist across the codebase with no shared logic.

## Goal

Branches should read like human intentions:
```
feat/auth-jwt-validation
feat/ui-dashboard-analytics
fix/payments-stripe-webhook
```

**Format:** `{prefix}/{category_slug}-{description_slug}`

---

## Design

### New module: `claw_forge/git/slug.py`

Two public functions:

**`make_slug(text, *, max_len=40) -> str`**
- Lowercases and strips non-alphanumeric characters
- Removes leading action verbs (add, implement, create, build, update, fix, …)
- Truncates to `max_len`, stripping any trailing dash

**`make_branch_name(description, category, plugin_name, *, prefix="feat", max_len=55) -> str`**
- Slugifies category (max 15 chars) → `cat_slug`
- Falls back to `plugin_name` when category is absent
- Computes remaining budget for description: `max_len - len(cat_slug) - 1`
- Returns `{prefix}/{cat_slug}-{desc_slug}`

### Call-site updates

| Location | Current | New |
|---|---|---|
| `cli.py:734` (dispatcher) | `plugin_name + id[:8]` | `make_branch_name(description, category, plugin_name)` |
| `cli.py:1655` (add cmd) | `feature.lower().replace(" ", "-")[:40]` | `make_slug(feature)` |
| `cli.py:2542` (fix cmd) | `re.sub(..., bug.title.lower())[:50]` | `make_branch_name(bug.title, None, "fix", prefix="fix")` |

`reviewer.py:352` uses `_`-separated slugs for text matching (not git) — left unchanged.

### Exports

`make_slug` and `make_branch_name` exported from `claw_forge/git/__init__.py`.

---

## Examples

| Input | Output branch |
|---|---|
| desc="Add JWT authentication", cat="auth" | `feat/auth-jwt-authentication` |
| desc="Implement user registration flow", cat="auth" | `feat/auth-user-registration-flow` |
| desc="Create dashboard with real-time analytics", cat="ui" | `feat/ui-dashboard-with-real-time-analy` |
| desc="Fix Stripe webhook timeout", cat=None, plugin="fix" | `feat/fix-stripe-webhook-timeout` |
| desc=None, cat="payments" | `feat/payments` |

---

## Testing

`tests/git/test_slug.py` covers:
- Verb stripping (single and multiple leading verbs)
- Category prefix applied correctly
- Fallback to plugin_name when no category
- Long descriptions truncated at max_len
- Special chars / unicode normalized to dashes
- Empty description returns category-only branch
- `max_len` respected end-to-end
