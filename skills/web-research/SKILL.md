# Web Research

## When to use this skill
Use when you need to look up documentation, investigate a library bug, or verify a technical fact before writing code.

## Protocol
1. **Write a specific query** — vague queries waste time:
   - Bad: `python async`
   - Good: `python asyncio gather exception handling site:docs.python.org`
   - Include version number if relevant: `pydantic v2 model_validator`

2. **Source priority** — prefer in this order:
   1. Official docs (`docs.python.org`, `pkg.go.dev`, `docs.rs`, etc.)
   2. GitHub repo README / CHANGELOG / releases
   3. GitHub issues and discussions (for known bugs)
   4. Stack Overflow (for specific error messages)
   5. Blog posts (last resort; verify against official docs)

3. **Check the version** — docs for v1.x don't apply to v3.x:
   - Check your lockfile (`uv.lock`, `package-lock.json`, `Cargo.lock`) for the exact version
   - Verify the docs page is for that version

4. **Check GitHub issues before assuming your code is wrong** — if a library behaves unexpectedly:
   - Search issues for your error message or behaviour
   - Check if it's a known bug with a workaround
   - Check the CHANGELOG for breaking changes in recent versions

5. **Cross-reference** — if only one source says X:
   - Find a second source that confirms it
   - Test it locally with a minimal example

6. **Stop when**: you have an official docs example that covers your use case → copy it, adapt it, test it.

## Commands
```bash
# Check installed version
uv run python -c "import package; print(package.__version__)"
cat uv.lock | grep "^name = \"package\""

# Test a minimal example from docs
uv run python -c "
import asyncio
# paste minimal example here
asyncio.run(main())
"
```

## Output interpretation
- Official docs with a working example → high confidence; use it
- Single blog post without official backup → low confidence; verify with minimal test
- GitHub issue marked "closed / fixed in v2.3" → check your version; upgrade if needed
- GitHub issue marked "won't fix" or "by design" → it's not a bug; adjust your code

Rules:
- Never paste code from the web without reading it line by line
- Never use code you don't understand just because it appeared in a search result
- If the official docs are unclear, check the source code — it's the ground truth
- Web results can be wrong or outdated; always verify with a minimal local test

## Done criteria
- Found an official docs reference or authoritative source for the approach
- Verified version compatibility
- Tested the approach locally with a minimal example before integrating
