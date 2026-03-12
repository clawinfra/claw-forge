# LoopDetectionMiddleware Design Doc

**Issue:** #5  
**Status:** Design — awaiting review before implementation  
**Author:** Alex Chen  
**Date:** 2026-03-12

---

## Problem

Agents get stuck in "doom loops" — making 10+ minor variations on the same broken approach to the
same file without stepping back to reconsider. LangChain observed this as a top failure mode in
their Terminal Bench 2.0 analysis.

### Two kinds of loops

claw-forge already addresses one kind:

| Loop type | Cause | Fix |
|-----------|-------|-----|
| **Tool failure loops** | `str_replace` fails repeatedly due to whitespace/offset mismatch | ✅ **Hashline edit mode (PR #3)** — content-addressed editing eliminates the failure surface |
| **Plan failure loops** | Agent is logically stuck — plan is wrong, not the tool | ⬅ **This issue** — detect via edit count, inject "reconsider" signal |

These are complementary. Hashline prevents loops *before they form* (tool level). LoopDetection
*detects* loops after they form and tries to break them (agent level).

---

## Solution

A `LoopDetectionMiddleware` PostToolUse hook that:

1. Tracks per-file edit counts in a shared, run-scoped context object
2. When a file exceeds a threshold (default: N=5 edits), injects a reconsideration prompt
3. Resets the counter when tests pass (progress confirmed)

---

## Architecture

```
PostToolUse hook fires after every Edit/Write/MultiEdit
        │
        ▼
LoopDetectionMiddleware
        │
        ├── Increment edit_counts[file_path]
        │
        ├── edit_counts[file] < threshold → pass through (no action)
        │
        └── edit_counts[file] >= threshold →
                inject: "You've edited {file} {N} times.
                         Consider reconsidering your approach.
                         Re-read the original spec and try a different strategy."

Test pass event (Bash tool with exit code 0 + test output)
        │
        └── Reset edit_counts[file] → 0
```

### Shared context object

The hook maintains a `RunContext` object that persists across tool calls within a single agent
run. This is passed into the hook closure at construction time.

```python
@dataclass
class LoopContext:
    edit_counts: dict[str, int] = field(default_factory=dict)
    threshold: int = 5
    injections: dict[str, int] = field(default_factory=dict)  # how many times injected per file
```

---

## Implementation Plan

### Files

```
claw_forge/agent/middleware/
├── __init__.py
├── pre_completion.py      ← see issue #4
└── loop_detection.py      ← new

tests/agent/middleware/
├── __init__.py
├── test_pre_completion.py ← see issue #4
└── test_loop_detection.py ← new
```

### API

```python
from claw_forge.agent.middleware.loop_detection import loop_detection_hook

hook_fn, ctx = loop_detection_hook(
    threshold: int = 5,            # edits before injecting reconsider prompt
    tracked_tools: list[str] = ["Edit", "Write", "MultiEdit"],
    reconsider_prompt: str | None = None,   # custom prompt, or use default
    max_injections: int = 2,       # max times to inject per file (avoid spam)
)
```

Returns both the hook function and the context object (so tests can inspect state).

### Integration with get_default_hooks()

```python
def get_default_hooks(
    edit_mode: str = "str_replace",
    verify_on_exit: bool = True,
    loop_detect_threshold: int = 5,        # new — 0 to disable
) -> dict[str, list[HookMatcher]]:
    hooks = {}
    if edit_mode == "hashline":
        # ... existing hashline hooks
    if verify_on_exit:
        hooks["Stop"] = [...]
    if loop_detect_threshold > 0:
        hook_fn, _ = loop_detection_hook(threshold=loop_detect_threshold)
        hooks.setdefault("PostToolUse", []).append(
            HookMatcher(matcher="Edit|Write|MultiEdit", hooks=[hook_fn])
        )
    return hooks
```

### CLI flag

```bash
claw-forge run --loop-detect-threshold 5   # default
claw-forge run --loop-detect-threshold 0   # disable
claw-forge run --loop-detect-threshold 3   # more aggressive
```

---

## The Injection Message

Default prompt injected when threshold exceeded:

```
⚠ Loop detected: you've edited '{file}' {N} times without a passing test.

Step back and reconsider your approach:
1. Re-read the original task spec (not your code)
2. Check your test output — what exactly is failing?
3. Consider a fundamentally different implementation strategy
4. If you're unsure, try a simpler approach first

Do NOT make another small variation on the same approach.
```

---

## Interaction with Hashline Edit Mode

When `--edit-mode hashline` is active, the loop threshold should be raised because:
- Hashline edits are more precise (fewer spurious failures)
- Edit count is a less noisy signal when the tool always succeeds

Recommended: `--edit-mode hashline --loop-detect-threshold 8`

This is documented in `docs/commands.md` and the CLI help text.

---

## Benchmark Plan

| Metric | Measurement |
|--------|-------------|
| Doom loop rate | % of runs with >5 edits to the same file |
| Task completion rate | % of Terminal Bench tasks passing |
| Token efficiency | Total tokens per task (loops burn tokens) |

See `docs/benchmarks/terminal-bench.md` for full benchmark setup.

---

## Edge Cases

| Scenario | Handling |
|----------|----------|
| Multiple agents editing same file | Context is per-run, not global — no cross-agent contamination |
| File renamed during run | Track by canonical path (resolve symlinks) |
| Agent deletes and recreates file | Count resets (treated as new file) |
| Injection not heeded | `max_injections=2` prevents spam; agent can override if confident |
| Test runner not available | Loop resets only on explicit "N tests passed" pattern in bash output |

---

## Open Questions

1. Should we track edit *lines changed* instead of edit count? (More precise signal)
2. Should the reconsider prompt be injected as `additionalContext` or as a new user message?
3. Does the threshold need to vary by agent type (coding vs reviewer vs planner)?

---

## References

- https://blog.langchain.com/improving-deep-agents-with-harness-engineering/
- PR #3 — hashline edit mode (complementary tool-level fix)
- Issue #5
