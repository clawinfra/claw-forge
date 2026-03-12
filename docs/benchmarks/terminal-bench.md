# Terminal Bench 2.0 Evaluation Harness

**Issue:** #6  
**Status:** Design — awaiting review before implementation  
**Author:** Alex Chen  
**Date:** 2026-03-12

---

## Goal

Run claw-forge against [Terminal Bench 2.0](https://www.tbench.ai/leaderboard/terminal-bench/2.0)
and produce an ablation study showing the incremental impact of each harness change.

This gives us:
1. Independent benchmark validation of our harness claims
2. A reproducible eval loop for ongoing harness iteration
3. Data for a public blog post / leaderboard submission

---

## Background

LangChain's deepagents (2026-03-12) went **52.8 → 66.5** (+13.7 points) on Terminal Bench 2.0
by changing only the harness, keeping `gpt-5.2-codex` fixed. Their key changes:

- Build-verify loop in system prompt
- PreCompletionChecklist hook (forces verification before stop)
- LoopDetection hook (breaks doom loops)
- LocalContextMiddleware (environment onboarding)
- Reasoning budget sandwich (xhigh-high-xhigh)

We hypothesise claw-forge can achieve comparable or better gains with:

- Hashline edit mode (eliminates tool-level doom loops — unique to claw-forge)
- PreCompletionChecklist hook (issue #4)
- LoopDetection hook (issue #5)

---

## Ablation Matrix

| Config ID | Edit mode | PreComplete | LoopDetect | Hypothesis |
|-----------|-----------|-------------|------------|------------|
| `A` — baseline | str_replace | ❌ | ❌ | Baseline |
| `B` — hashline | hashline | ❌ | ❌ | +N pts (fewer tool loops) |
| `C` — verify | str_replace | ✅ | ❌ | +N pts (fewer early exits) |
| `D` — loop | str_replace | ❌ | ✅ | +N pts (fewer doom loops) |
| `E` — full | hashline | ✅ | ✅ | Maximum score |

Run each config 3× and report mean ± std to account for model variance.

---

## Infrastructure

### Benchmark runner

Terminal Bench uses [Harbor](https://harborframework.com/) to orchestrate runs. Harbor spins up
[Daytona](https://www.daytona.io/) sandboxes, calls the agent API, and scores output.

claw-forge needs to expose an HTTP API or CLI adapter compatible with Harbor's agent interface.

```
scripts/eval/
├── terminal_bench.py      ← main runner (calls Harbor API + claw-forge)
├── harbor_adapter.py      ← translates Harbor's agent protocol to claw-forge run_agent()
└── results_parser.py      ← parses Harbor output into our ablation table
```

### Models to test

| Model | Rationale |
|-------|-----------|
| `claude-sonnet-4-6` (primary) | Our default; compare to LangChain's Codex baseline |
| `claude-opus-4-6` | Verify that better models + better harness compounds |
| `gpt-5.2-codex` | Apples-to-apples comparison with LangChain's results |

### Costs

Terminal Bench 2.0 has 89 tasks. At ~50K tokens/task on Sonnet:
- 89 tasks × 5 configs × 3 runs = 1335 runs
- ~50K tokens × 1335 = 66.75M tokens
- At $3/M input + $15/M output (Sonnet): est. **~$600-900** total

Start with config A vs E only (2 configs × 3 runs = 534 runs, ~$120-180) to validate
before running the full ablation.

---

## Results Format

Results committed to `docs/benchmarks/results.md` after each run:

```markdown
## Terminal Bench 2.0 Results — 2026-03-XX

Model: claude-sonnet-4-6

| Config | Score | ± | Runs |
|--------|-------|---|------|
| A — baseline | XX.X | ±Y.Y | 3 |
| B — hashline | XX.X | ±Y.Y | 3 |
| C — verify   | XX.X | ±Y.Y | 3 |
| D — loop     | XX.X | ±Y.Y | 3 |
| E — full     | XX.X | ±Y.Y | 3 |

**Hashline impact:** +X.X pts vs baseline  
**Full stack impact:** +X.X pts vs baseline  
```

---

## Implementation Plan

### Phase 1 — Setup (prerequisite)

- [ ] Obtain Terminal Bench / Harbor API access
- [ ] Document Harbor agent protocol in `docs/benchmarks/harbor-protocol.md`
- [ ] Build `harbor_adapter.py` — minimal HTTP wrapper around `run_agent()`
- [ ] Test locally on 5 tasks before full run

### Phase 2 — Baseline run

- [ ] Run config A (baseline) × 3 on 89 tasks
- [ ] Record baseline score in `docs/benchmarks/results.md`
- [ ] Identify top 20 failure modes from traces

### Phase 3 — Ablation

- [ ] Run configs B, C, D, E × 3 each
- [ ] Fill ablation table
- [ ] Identify which harness change contributes most

### Phase 4 — Publish

- [ ] Blog post: "claw-forge on Terminal Bench 2.0" with ablation data
- [ ] Submit to Terminal Bench leaderboard
- [ ] Update README with badge + score

---

## Tracing

All runs traced via claw-forge's existing PostToolUse hooks. Per-run traces stored in:

```
docs/benchmarks/traces/
└── YYYY-MM-DD/
    └── config-{A-E}/
        └── task-{id}/
            └── trace.jsonl
```

Trace analysis follows LangChain's Trace Analyzer pattern:
parallel error analysis agents → synthesis → targeted harness changes.

---

## Success Criteria

- Full ablation table with ≥3 runs per config
- Hashline edit mode shows measurable positive delta vs baseline
- Full stack (config E) score > LangChain's 66.5 on Sonnet (stretch goal)
- Results committed to repo and publicly disclosed

---

## References

- https://blog.langchain.com/improving-deep-agents-with-harness-engineering/
- https://www.tbench.ai/leaderboard/terminal-bench/2.0
- https://harborframework.com/
- Issue #6
