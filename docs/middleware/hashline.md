# Hashline Edit Mode

**`--edit-mode hashline`** is claw-forge's content-addressed editing mode — the single biggest
lever for improving agent edit reliability on real codebases.

## The Problem It Solves

Standard `str_replace` editing requires the agent to reproduce an exact substring of the file —
whitespace, indentation, and all — before the edit tool accepts it. This breaks constantly:

- **Indentation drift** — the agent writes 3 spaces, file has 4 → edit rejected
- **Whitespace hallucination** — model invents trailing spaces that don't exist
- **Long context degradation** — after many turns, the model's recall of exact file content
  degrades; it produces "close but not exact" substrings
- **Weak model penalty** — smaller/faster models are disproportionately hurt; a model with
  95% text recall still fails 100% of edits that need exact matches

The failure mode is an `edit_rejected` loop: agent tries → fails → retries with slightly different
text → fails again → burns turns until timeout.

## How Hashline Works

When `--edit-mode hashline` is active, two hooks fire:

**1. Read hook (PostToolUse/Read):** Every file the agent reads gets annotated with 3-char content
hashes, one per line:

```
a3f|def calculate_total(items):
7b2|    return sum(item.price for item in items)
c91|
4d8|def apply_discount(total, rate):
```

**2. Edit hook (PreToolUse/Edit):** The agent references lines by hash instead of reproducing
their content. The hook translates hash references → exact file positions before passing to
the underlying `str_replace` tool:

```
# Agent writes:
7b2|    return sum(item.price * item.quantity for item in items)

# Hook translates to:
old: "    return sum(item.price for item in items)"
new: "    return sum(item.price * item.quantity for item in items)"
```

The agent never has to reproduce the original line. It just references the hash of the line it
wants to change and writes the replacement.

**Collision handling:** If two lines in a file have the same 3-char hash, the second gets `_2`,
third gets `_3`, etc. The agent learns this from the annotated output and uses `7b2_2` to target
the second occurrence.

**Graceful degradation:** If the agent writes a normal `str_replace` block (no hash refs), the
hook passes it through unchanged. Hashline mode is additive — it never breaks normal edits.

## When to Use Hashline

### ✅ Use hashline when…

**You're on a weaker or faster model (Sonnet, Haiku, local models)**
The str_replace failure rate on smaller models can exceed 30%. Hashline removes the exact-match
requirement entirely — even a model with poor exact-text recall succeeds on every edit.

**The codebase has heavy indentation or complex whitespace**
Python (mandatory indentation), YAML, Rust with nested closures, deeply indented TypeScript —
any file where whitespace is semantically significant and models frequently get it wrong.

**Long sessions with many edits**
After 20+ turns, models start misremembering file contents. Hash references stay valid regardless
of how many turns have passed since the Read.

**You want maximum reliability for unattended runs**
Running claw-forge in CI, overnight, or fully autonomous (with `--auto-push`)? Hashline means
the agent doesn't get stuck in edit-rejection loops at 3 AM.

**Benchmark / evaluation runs**
All claw-forge-bench evaluation runs used Config E (hashline + loop-detect + verify-on-exit).
It's the configuration that achieves 100% on the ablation suite.

### ⚠️ Consider skipping hashline when…

**You're debugging the agent's edit behaviour**
Hash annotations add noise to logs. For debugging whether the agent is reading the right lines,
plain `str_replace` mode gives cleaner output.

**The file is auto-generated or binary-adjacent**
Hashline annotates every file the agent reads. On minified JS, generated protobuf files, or
files with lines > 500 chars, the annotations are noise and may confuse the model.

**You need to review agent diffs as plain patches**
Hashline edit blocks (`a3f|new content`) aren't valid unified diffs. If you're reviewing agent
work as patch files, str_replace mode produces cleaner artifacts.

## Interaction with LoopDetectionMiddleware

When `--edit-mode hashline` is active, `LoopDetectionMiddleware` automatically raises the
loop-detection threshold by 3 (default 5 → 8).

**Why:** hashline edits are more granular. An agent doing a legitimate multi-step refactor might
touch the same file 7 times with hashline (one hash reference per logical chunk) vs. 3 times with
str_replace (one big block). Without the boost, loop detection fires too early on complex tasks.

The boost is automatic — you don't need to tune `--loop-detect-threshold` when using hashline.

## Benchmark Results

Measured on [claw-forge-bench](https://github.com/clawinfra/claw-forge-bench) — 30 Python
coding tasks, model `claude-opus-4-6`, 2026-03-13:

| Config | edit-mode | Δ vs baseline |
|--------|-----------|---------------|
| A — baseline | str_replace | — |
| B — hashline only | **hashline** | +0pp (individual uplift masked) |
| E — full stack | **hashline** + loop=5 + verify | **+3.3pp → 100%** |

The combination effect is real: hashline alone doesn't add statistical uplift on a 30-task suite,
but it's what allows Config E to reach 100% — it's the foundation the other layers build on.

Original benchmark that motivated hashline: **6.7% → 68.3%** on Grok Code Fast (can1357),
a +61.6pp improvement on a weaker model.

## Quick Reference

```bash
# Recommended: full Config E (loop-detect + verify-on-exit are on by default)
claw-forge run --edit-mode hashline

# Explicit form (same as above, all defaults shown)
claw-forge run \
  --edit-mode hashline \
  --loop-detect-threshold 5 \   # auto-boosts to 8 when hashline is active
  --verify-on-exit              # default: on

# Disable hashline, keep other middleware
claw-forge run  # str_replace mode, loop-detect=5, verify-on-exit=on

# Debug mode (no middleware)
claw-forge run --no-verify-on-exit --loop-detect-threshold 0

# Autonomous CI run with push
claw-forge run --edit-mode hashline --auto-push /path/to/repo
```

## See Also

- [`docs/middleware/loop-detection.md`](loop-detection.md) — LoopDetectionMiddleware details
- [`docs/middleware/pre-completion-checklist.md`](pre-completion-checklist.md) — PreCompletionChecklistMiddleware details
- [`docs/benchmarks/results.md`](../benchmarks/results.md) — Full ablation results
- [`claw_forge/hashline.py`](../../claw_forge/hashline.py) — Implementation
