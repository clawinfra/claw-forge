# Verification Gate

## When to use this skill
Run this skill LAST — before reporting any task as complete. All steps are mandatory.

## Protocol
All 6 steps are required. Do not skip any. "It should work" is not verification.

1. **Run tests** — execute the full test suite and confirm all pass:
   ```
   uv run pytest tests/ -q
   ```
   Paste or reference the actual output. "Tests should pass" is not acceptable.

2. **Run linter and type-checker** — zero errors allowed:
   ```
   uv run ruff check claw_forge/ tests/
   uv run mypy claw_forge/ --ignore-missing-imports
   ```

3. **Check coverage** — new code must be ≥ 90% covered:
   ```
   uv run pytest tests/ --cov=claw_forge --cov-report=term-missing -q
   ```
   Identify any uncovered lines in new code and add tests.

4. **Read your own changes** — review every line you wrote:
   ```
   git diff HEAD~1
   ```
   Check for: typos, logic errors, TODOs left in, debug prints, wrong variable names.

5. **Smoke test** — run the actual command/function/endpoint with real inputs:
   - Don't just run unit tests; exercise the real code path end-to-end.
   - For a CLI command: run it with typical args and verify the output.
   - For an API endpoint: `curl` it and check the response.

6. **Check for sensitive data** — nothing personal or secret in the diff:
   ```bash
   git diff HEAD~1 | grep -iE "password|secret|key|token|@gmail|phone|private"
   ```
   If anything is found, remove it before committing.

## Commands
```bash
# Full verification sequence
uv run pytest tests/ -q
uv run ruff check claw_forge/ tests/
uv run pytest tests/ --cov=claw_forge --cov-report=term-missing -q
git diff HEAD~1
git diff HEAD~1 | grep -iE "password|secret|key|token|@gmail|phone"
```

## Output interpretation
- Any test failure → fix before reporting done; no exceptions
- Ruff error → fix it; do not suppress with `# noqa` unless truly necessary and commented
- Coverage <90% → add tests; do not lower the threshold
- Sensitive data in diff → remove and rotate if already committed
- Smoke test produces unexpected output → investigate; do not assume it's fine

Failure modes that don't count as verification:
- "I think the tests pass" → actually run them
- "The logic looks correct" → tests must actually execute
- "I'll fix coverage later" → fix it now before reporting done
- Missing deps / broken env → fix the environment first, do not skip verification

## Done criteria
- `uv run pytest tests/ -q` exits 0 with all tests passing
- `uv run ruff check` exits 0 with no errors
- Coverage ≥ 90% on new code
- `git diff HEAD~1` reviewed line by line
- Smoke test executed with real inputs and verified
- No sensitive data in diff
