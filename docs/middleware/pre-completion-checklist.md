# PreCompletionChecklistMiddleware Design Doc

**Issue:** #4  
**Status:** Design — awaiting review before implementation  
**Author:** Alex Chen  
**Date:** 2026-03-12

---

## Problem

The most common agent failure mode in autonomous coding is premature completion: the agent writes
a solution, re-reads its own code, decides it looks correct, and stops — without ever running
tests or comparing output against the original task specification.

LangChain's deepagents research (Terminal Bench 2.0, 2026-03-12) identifies this as their
highest-impact harness fix, contributing to a +13.7 point improvement (52.8→66.5).

The root cause is model bias: **models are biased toward their first plausible solution**. Without
a structural forcing function, they don't self-verify.

---

## Solution

A `PreCompletionChecklistMiddleware` hook that intercepts `Stop` events before the agent exits
and injects a structured verification prompt. The agent must complete the checklist before it is
allowed to stop.

This is a **hook**, not a prompt change — it fires at the tool/event level, not in the system
prompt. This keeps the forcing function structural and not subject to "prompt drift" where agents
learn to shortcut verbose instructions.

---

## Architecture

```
Agent loop
    │
    ├── Tool calls (Edit, Write, Bash, ...)
    │
    └── Stop event
            │
            ▼
    PreCompletionChecklistMiddleware
            │
            ├── Inject checklist context into agent
            │
            └── Agent must respond with verification steps
                    │
                    ├── Tests pass? → Allow Stop
                    └── Tests fail? → Continue loop
```

### Hook type

`Stop` event hook (intercepts `stop_reason == "end_turn"` or similar terminal signal).

### What the hook injects

```
Before you finish, complete this checklist:

1. TASK SPEC: Re-read the original task description. Do NOT read your own code — read the spec.
2. TESTS: Run the test suite now. Read the full output, not just the pass/fail summary.
3. VERIFY: Does your output match what the spec asked for exactly? Check edge cases.
4. FIX: If anything fails, fix it now. Do not exit with failing tests.

Only exit when: all tests pass AND output matches the original specification.
```

The checklist is injected as `additionalContext` into the stop hook output, which causes the
agent to continue the loop.

---

## Implementation Plan

### Files

```
claw_forge/agent/middleware/
├── __init__.py
├── pre_completion.py      ← new
└── loop_detection.py      ← see issue #5

tests/agent/middleware/
├── __init__.py
└── test_pre_completion.py ← new
```

### API

```python
from claw_forge.agent.middleware.pre_completion import pre_completion_checklist_hook

# Returns a hook function for use with HookMatcher
hook = pre_completion_checklist_hook(
    checklist_prompt: str | None = None,   # custom prompt, or use default
    require_test_run: bool = True,         # require explicit test command before exit
    max_verifications: int = 3,            # prevent infinite verification loops
)
```

### Integration with get_default_hooks()

```python
def get_default_hooks(
    edit_mode: str = "str_replace",
    verify_on_exit: bool = True,           # new flag (default: True)
) -> dict[str, list[HookMatcher]]:
    hooks = {}
    if edit_mode == "hashline":
        # ... existing hashline hooks
    if verify_on_exit:
        hooks["Stop"] = [HookMatcher(hooks=[pre_completion_checklist_hook()])]
    return hooks
```

### CLI flag

```bash
claw-forge run --verify-on-exit          # enabled by default
claw-forge run --no-verify-on-exit       # disable for fast iteration/debugging
```

---

## Benchmark Plan

Run Terminal Bench 2.0 ablation:

| Config | Expected |
|--------|----------|
| Baseline (no middleware) | Baseline score |
| + verify-on-exit | +N points (hypothesis: significant) |

See `docs/benchmarks/terminal-bench.md` for full benchmark setup.

---

## Edge Cases

| Scenario | Handling |
|----------|----------|
| Agent runs verification loop > `max_verifications` times | Allow stop to prevent infinite loop |
| Task has no tests | Checklist still runs; agent verifies against spec manually |
| Agent in `--yolo` mode | `verify_on_exit` still applies (safety, not speed setting) |
| Hook errors | Degrade gracefully — log error, allow stop |

---

## Open Questions

1. Should the checklist prompt be configurable per-project via `claw-forge.yaml`? (Probably yes)
2. Should `require_test_run` track whether a Bash tool call with "test" ran, or trust the model?
3. Is `max_verifications=3` the right default or should it be configurable?

---

## References

- https://blog.langchain.com/improving-deep-agents-with-harness-engineering/
- https://ghuntley.com/loop/ — Ralph Wiggum Loop pattern
- Issue #4
