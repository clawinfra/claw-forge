# Code Review

## When to use this skill
Use when reviewing a pull request, diff, or code change for quality, correctness, and safety.

## Protocol
Run checks in this exact order — do not skip:

1. **Correctness** — Does it do what it claims?
   - Check edge cases: empty input, None/null, negative numbers, max values
   - Look for off-by-one errors in loops and slice indices
   - Verify error paths are handled, not silently swallowed

2. **Security** — Could this be exploited?
   - SQL injection: parameterized queries only; never string concat
   - XSS: user input must be escaped before rendering
   - Hardcoded secrets: grep for `password`, `token`, `key`, `secret`
   - Path traversal: `Path(user_input).resolve()` must stay under allowed root
   - Input validation: reject unexpected types/lengths before processing

3. **Performance** — Will this scale?
   - N+1 queries: fetching related objects in a loop → use JOIN or batch fetch
   - Unbounded loops: any loop that can run O(n²) on large input?
   - Unnecessary allocations: building large lists only to throw them away

4. **Test coverage** — Is it tested?
   - Happy path covered?
   - Error path and edge cases covered?
   - Mocks: are they realistic, or do they hide real bugs?

5. **Style** — Is it readable?
   - Function length: flag anything >40 lines
   - Single responsibility: does each function do one thing?
   - Naming clarity: `process_data()` is bad; `validate_user_email()` is good

6. **Type safety** — Is it type-safe?
   - No untyped `Any` without explicit comment explaining why
   - No `# type: ignore` without a comment
   - Return types declared on all public functions

## Commands
```bash
# Run linter
uv run ruff check .

# Run type checker
uv run mypy src/ --strict

# Run tests with coverage
uv run pytest tests/ -v --tb=short --cov=src --cov-report=term-missing

# Search for hardcoded secrets
grep -r "password\s*=\|token\s*=\|secret\s*=" --include="*.py" .
```

## Output interpretation
Use severity labels per finding:

| Label    | Meaning                                              | Action          |
|----------|------------------------------------------------------|-----------------|
| CRITICAL | RCE, auth bypass, data leak, broken logic            | Block merge     |
| HIGH     | SQLi, XSS, hardcoded secret, data corruption risk    | Block merge     |
| MEDIUM   | Missing error handling, performance issue, bad test  | Fix this sprint |
| LOW      | Style, naming, minor duplication                     | Suggestion only |
| INFO     | Nitpick, alternative approach                        | Suggestion only |

Example finding:
```
HIGH [security] user_input passed directly to SQL query (line 42) — use parameterized query
```

## Done criteria
- All CRITICAL and HIGH findings are either fixed or explicitly accepted with written justification
- Linter and type checker report zero errors
- Test coverage ≥ 90% on changed files
