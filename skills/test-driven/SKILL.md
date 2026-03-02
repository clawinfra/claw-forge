# Test-Driven Development

## When to use this skill
Use when implementing any new feature or fixing a bug — write the test first, then the code.

## Protocol
Strictly follow red → green → refactor. Do not skip steps.

1. **Red** — write a failing test for the next small, specific behaviour:
   - Run it: confirm it fails for the right reason (not a syntax error or import error)
   - One test at a time — don't write 10 tests then implement

2. **Green** — write the minimum code to make the test pass:
   - Literally the minimum — no extra logic, no "while I'm here" additions
   - Run the test: confirm it passes

3. **Refactor** — clean up without changing behaviour:
   - Remove duplication
   - Improve naming
   - Run tests again: confirm they still pass

4. **Repeat** — pick the next behaviour and go back to step 1.

## Commands
```bash
# Python (stop at first failure, verbose)
uv run pytest tests/ -v --tb=short -x

# Python (with coverage)
uv run pytest tests/ -v --tb=short --cov=src --cov-report=term-missing

# Python (watch mode via pytest-watch)
uv run ptw tests/ -- -v

# Go
go test ./... -v -run TestFunctionName

# Rust
cargo test -- --nocapture

# Node/TypeScript
npx jest --watch --verbose
```

## Output interpretation
- `FAILED tests/test_foo.py::test_name - AssertionError` → test is red; expected during step 1
- `PASSED` → test is green; proceed to refactor
- `ERROR` (not FAILED) → test has a bug (import error, syntax error); fix the test first
- Coverage <90% on new code → add tests for uncovered branches before declaring done
- All tests pass but one was removed or skipped → that's a cheat; restore it

Rules:
- Test names describe behaviour: `test_user_cannot_login_with_wrong_password`, not `test_login_2`
- Don't mock what you own — only mock external systems (HTTP, DB, filesystem, time)
- 90% coverage is the floor, not the goal — 100% on critical/financial/auth paths
- Never write `# type: ignore` or cast to `Any` to make a test pass

## Done criteria
- All tests pass: `uv run pytest tests/ -q` shows 0 failures
- Coverage ≥ 90% on all new code (check with `--cov-report=term-missing`)
- No `# type: ignore` or `any` types added to pass tests
- Each test name clearly describes the behaviour it verifies
