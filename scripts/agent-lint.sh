#!/bin/bash
# Agent harness linter (Python) — errors are agent-readable
# Usage: bash scripts/agent-lint.sh [--json]
set -euo pipefail
ERRORS=0
JSON_MODE=false
[ "${1:-}" = "--json" ] && JSON_MODE=true
cd "$(git rev-parse --show-toplevel)"
echo "=== Agent Lint (Python) ==="

# Rule 1: No bare except clauses
echo "[1/7] Checking for bare except..."
BARE=$(grep -rn "except:" claw_forge/ 2>/dev/null | grep -v "# noqa" | grep -v "_test\|test_" || true)
if [ -n "$BARE" ]; then
  echo "LINT ERROR [bare-except]: Found bare except: clauses"
  echo "$BARE" | head -5
  echo "  WHAT: Bare except catches SystemExit and KeyboardInterrupt — masks real bugs."
  echo "  FIX:  Use specific exception types: except (ValueError, TypeError):"
  echo "  REF:  docs/QUALITY.md#error-handling"
  ERRORS=$((ERRORS+1))
fi

# Rule 2: No print() in source (use logging)
echo "[2/7] Checking for print statements..."
PRINTS=$(grep -rn "^[[:space:]]*print(" claw_forge/ 2>/dev/null | grep -v "# noqa" | grep -v "_test\|test_" || true)
if [ -n "$PRINTS" ]; then
  COUNT=$(echo "$PRINTS" | wc -l | tr -d ' ')
  echo "LINT WARNING [print-statements]: $COUNT print() calls in source (use logging)"
  echo "$PRINTS" | head -3
  echo "  FIX:  import logging; logger = logging.getLogger(__name__)"
  echo "  REF:  docs/CONVENTIONS.md#logging"
fi

# Rule 3: All public modules must have docstrings
echo "[3/7] Checking module docstrings..."
MISSING_DOCS=$(find claw_forge/ -name "*.py" ! -name "_*" ! -name "test_*" -exec grep -L '"""' {} \; 2>/dev/null || true)
if [ -n "$MISSING_DOCS" ]; then
  echo "LINT ERROR [missing-docstring]: Public modules missing docstrings:"
  echo "$MISSING_DOCS" | head -5
  echo "  FIX:  Add triple-quoted module docstring at top of file."
  echo "  REF:  docs/CONVENTIONS.md#docstrings"
  ERRORS=$((ERRORS+1))
fi

# Rule 4: Tool count guard (check __init__.py exports)
echo "[4/7] Checking tool ceiling..."
TOOL_COUNT=$(grep -rn "^def \|^async def " claw_forge/ 2>/dev/null | grep -v "_test\|test_\|_impl\|_helper" | grep -c "^" 2>/dev/null || echo 0)
if [ "$TOOL_COUNT" -gt 40 ]; then
  echo "LINT WARNING [tool-ceiling]: $TOOL_COUNT public functions found"
  echo "  WHAT: High function count increases agent decision overhead (guideline: <20 tools per agent)."
  echo "  FIX:  Group related functions into classes or move to submodules."
  echo "  REF:  docs/ARCHITECTURE.md#tool-ceiling"
fi

# Rule 5: AGENTS.md length
echo "[5/7] Checking AGENTS.md length..."
if [ -f AGENTS.md ] && [ "$(wc -l < AGENTS.md)" -gt 150 ]; then
  echo "LINT ERROR [agents-too-long]: AGENTS.md exceeds 150 lines"
  echo "  FIX: Move details to docs/ and replace with pointers."
  ERRORS=$((ERRORS+1))
fi

# Rule 6: ruff (Python linter — import sorting, pyflakes, pycodestyle)
echo "[6/7] Running ruff..."
if command -v ruff &>/dev/null || [ -f .venv/bin/ruff ]; then
  RUFF_OUT=$(ruff check claw_forge/ tests/ --select E,F,I --quiet 2>&1 || true)
  if [ -n "$RUFF_OUT" ]; then
    RUFF_COUNT=$(echo "$RUFF_OUT" | grep -c "^" 2>/dev/null || echo 0)
    echo "LINT ERROR [ruff]: $RUFF_COUNT issue(s) found"
    echo "$RUFF_OUT" | head -10
    echo "  WHAT: ruff found lint errors (import sort, pyflakes, pycodestyle)."
    echo "  FIX:  Run 'ruff check --fix claw_forge/ tests/' to auto-fix."
    echo "  REF:  docs/QUALITY.md#linting"
    ERRORS=$((ERRORS+1))
  fi
else
  echo "  SKIP: ruff not installed (install via 'uv pip install ruff')"
fi

# Rule 7: pyright (Python type checker)
echo "[7/7] Running pyright..."
if command -v pyright &>/dev/null || [ -f .venv/bin/pyright ]; then
  PYRIGHT_OUT=$(pyright claw_forge/ --warnings 2>&1 || true)
  PYRIGHT_ERRS=$(echo "$PYRIGHT_OUT" | grep -c "error:" 2>/dev/null || echo 0)
  if [ "$PYRIGHT_ERRS" -gt 0 ]; then
    echo "LINT ERROR [pyright]: $PYRIGHT_ERRS type error(s) found"
    echo "$PYRIGHT_OUT" | grep "error:" | head -10
    echo "  WHAT: pyright found type checking errors."
    echo "  FIX:  Fix type annotations or add # type: ignore[rule] comments."
    echo "  REF:  docs/QUALITY.md#type-checking"
    ERRORS=$((ERRORS+1))
  fi
else
  echo "  SKIP: pyright not installed (install via 'uv pip install pyright')"
fi

echo "=== Lint: $ERRORS error(s) ==="
if $JSON_MODE; then
  echo "{\"errors\": $ERRORS, \"status\": \"$([ $ERRORS -eq 0 ] && echo pass || echo fail)\"}"
fi
[ $ERRORS -eq 0 ] || exit 1
echo "All checks passed. ✓"
