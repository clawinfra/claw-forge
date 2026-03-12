# claw-forge as an OpenClaw Agent Skill

claw-forge ships as an installable **OpenClaw agent skill** so any AI agent running
on OpenClaw can invoke the full claw-forge workflow without manual setup.

## Install via ClawHub

```bash
clawhub install claw-forge-cli
```

Or search for it:

```bash
clawhub search "claw-forge"
```

ClawHub page: https://clawhub.com/skills/claw-forge-cli

## What the skill provides

Once installed, your agent gains:

- A **SKILL.md** teaching it the full claw-forge CLI (`init → plan → run → status → ui`)
- **Edit mode guidance**: when to use `--edit-mode hashline` vs `str_replace`
- **Brownfield workflow**: how to add features to an existing project
- **Bug-fix protocol**: the `claw-forge fix` reproduce-first pattern
- **Config reference**: `claw-forge.yaml` provider pool setup
- **Provider pool tips**: multi-provider failover, cost-optimised runs

## How it gets used

When an agent receives a task like:
- "Build a FastAPI backend from this spec"
- "Add OAuth2 to my existing project"
- "Fix the login bug using claw-forge"
- "Run agents on my project overnight"

The skill fires and the agent follows the correct workflow automatically.

## Edit Modes: `str_replace` vs `hashline`

### The problem with `str_replace`

Standard string-replace requires the model to produce exact text matches including
whitespace, indentation, and surrounding context. On longer files or after edits
shift line numbers, this fails silently — the agent *thinks* it made a change but
the file is unchanged.

### hashline: content-addressed editing

`hashline` mode prefixes every line with a 3-char SHA-256 hash tag when reading:

```
a3f|def calculate_total(items):
b2c|    result = 0
d4e|    for item in items:
f1a|        result += item.price
g5b|    return result
```

The model edits by hash reference, not text content:

```json
{"hash": "b2c", "new_content": "    result = 0.0"}
{"after_hash": "f1a", "new_content": "        result = round(result, 2)"}
{"hash": "g5b", "delete": true}
```

**Result:** immune to whitespace drift, indentation changes, and line-number shifts.

### Benchmark

| Metric | str_replace | hashline |
|--------|-------------|----------|
| Grok Code Fast success rate | 6.7% | 68.3% |
| Token reduction | baseline | −61% |
| Collision rate (3-char hash) | N/A | <0.1% typical |

Source: [can1357/hashline experiments](http://blog.can.ac/2026/02/12/the-harness-problem/)

### When to use hashline

- Weaker or cost-optimised models (Haiku, GPT-4o-mini, local models)
- Files >500 lines where context compression is needed
- Brownfield projects with complex existing code
- When you're seeing agents making "changes" that don't stick

```bash
claw-forge run --edit-mode hashline --model claude-haiku-4-5 --concurrency 10
```

## Middleware Stack

claw-forge v0.3+ ships three composable middleware layers that fire inside the agent turn via
Claude Agent SDK hooks. All are enabled by default; all can be tuned or disabled.

### LoopDetectionMiddleware

Tracks per-file edit counts. When a file is edited more than `--loop-detect-threshold` times
(default: 5), injects a structured "reconsider" prompt to break doom loops.

- Hook: `PostToolUse` (Edit, MultiEdit)
- Threshold auto-boosts by 3 when `--edit-mode hashline` is active (line-level edits are
  more frequent by design)
- `--loop-detect-threshold 0` disables it entirely
- Design doc: [`docs/middleware/loop-detection.md`](middleware/loop-detection.md)

### PreCompletionChecklistMiddleware

Intercepts the `Stop` event before the agent exits and injects a verification checklist:
re-read spec → check acceptance criteria → run tests → confirm done.

- Hook: `Stop`
- `--no-verify-on-exit` disables it (useful for debugging)
- Design doc: [`docs/middleware/pre-completion-checklist.md`](middleware/pre-completion-checklist.md)

### Recommended production stack

```bash
claw-forge run --edit-mode hashline --loop-detect-threshold 5 --verify-on-exit
```

This is **Config E** in the Terminal Bench 2.0 ablation. See
[`docs/benchmarks/terminal-bench.md`](benchmarks/terminal-bench.md) for full ablation results.

## Terminal Bench 2.0

claw-forge ships an eval harness (`claw_forge/eval/`) for measuring the impact of each
middleware layer on a standardised set of coding tasks.

Run the full ablation:

```bash
# All 5 configs (A=baseline → E=full stack)
uv run python -m claw_forge.eval.terminal_bench --config all

# Single config
uv run python -m claw_forge.eval.terminal_bench --config E --reps 3

# Results are appended to docs/benchmarks/results.md
```

Config definitions:
| Config | edit-mode | loop-detect | verify-on-exit |
|--------|-----------|-------------|----------------|
| A | str_replace | disabled | disabled |
| B | hashline | disabled | disabled |
| C | str_replace | 5 | enabled |
| D | str_replace | disabled | enabled |
| E | hashline | 5 | enabled |

## Updating the skill

```bash
clawhub update claw-forge-cli
```

## Source

Skill source: `skills/claw-forge-cli/SKILL.md` in this repo.  
Published to ClawHub: https://clawhub.com/skills/claw-forge-cli
