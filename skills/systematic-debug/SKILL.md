# Systematic Debug

## When to use this skill
Use when debugging any bug — follow these steps in order; never skip ahead to "just try a fix".

## Protocol
Follow strictly in order — never skip a step:

1. **Reproduce** — get a minimal, deterministic reproduction.
   - If you can't reproduce it reliably, you can't fix it.
   - Reduce to the smallest possible input that still triggers the bug.
   - Document the exact reproduction steps.

2. **Isolate** — binary search to find the exact location:
   - Comment out half the relevant code. Does it still fail?
   - Keep narrowing until you have the smallest failing unit (ideally one function or one line).
   - Use `print()` or logging to observe actual vs expected values at each step.

3. **Hypothesize** — write down 3 candidate causes, ranked by likelihood:
   - One sentence each: "The bug is probably caused by X because Y."
   - Do this before making any changes. Write them down.

4. **Verify** — test your top hypothesis with a minimal, targeted probe:
   - Don't fix it yet — just confirm the hypothesis is correct.
   - If the probe disproves the hypothesis, go back to step 3 with new information.

5. **Fix** — make the targeted fix:
   - Fix only the confirmed root cause. Do not "also fix" unrelated things.
   - Keep the fix as small as possible.

6. **Regression test** — write a test that would have caught this bug:
   - The test must fail before the fix and pass after.
   - Commit the test alongside the fix.

## Commands
```bash
# Run with verbose output to see what's happening
uv run pytest tests/test_specific.py -v --tb=long -s

# Run just the failing test
uv run pytest tests/ -k "test_name" -v

# Add a breakpoint
import pdb; pdb.set_trace()   # or breakpoint() in Python 3.7+

# Check what's in a variable at runtime
print(f"DEBUG: {variable=}")  # Python 3.8+ f-string debug format

# Check git blame to see when a line changed
git log -p -S "function_name" -- path/to/file.py
```

## Output interpretation
- Error traceback: read from the bottom up — the last frame is usually where the bug is
- `AttributeError: 'NoneType' has no attribute X` → something that should never be None is None; trace back to where it was set
- `KeyError` → dict key missing; check input validation or default handling
- `IndexError` → list access out of bounds; check loop range or slice logic
- Test passes locally but fails in CI → environment difference; check env vars, OS, Python version

Rules:
- Never add debugging code and shipping code in the same commit
- `print()` debugging is fine during steps 2–3; remove before step 5
- If stuck for >20 minutes → escalate or ask for human input; don't keep guessing

## Done criteria
- Minimal reproduction documented
- Root cause identified and confirmed (not guessed)
- Fix is targeted (changes only what's needed)
- Regression test added that fails before fix, passes after
- Debug prints removed from final commit
