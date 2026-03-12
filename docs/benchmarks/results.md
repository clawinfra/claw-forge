# Terminal Bench 2.0 — Ablation Results

Results are prepended (newest first) by `terminal-bench --config all`.

---

<!-- RESULTS_MARKER: new sections inserted above this line -->

## claw-forge-bench Ablation — 2026-03-13

Model: `claude-opus-4-6` (Anthropic OAuth)  
Suite: [claw-forge-bench](https://github.com/clawinfra/claw-forge-bench) — 30 tasks (10 easy / 10 medium / 10 hard)

| Config | Description | Pass Rate | Δ vs A | Passed | Failed |
|--------|-------------|----------:|-------:|-------:|-------:|
| A | Baseline (str_replace, no middleware) | 86.7% | — | 26 | 4 |
| B | Hashline edit mode | 86.7% | +0.0pp | 26 | 4 |
| C | str_replace + loop detection (threshold=5) | 86.7% | +0.0pp | 26 | 4 |
| D | str_replace + verify-on-exit | 86.7% | +0.0pp | 26 | 4 |
| **E** | **Full stack (hashline + loop + verify)** | **90.0%** | **+3.3pp** | **27** | **3** |

**Hashline impact (B vs A):** +0.0pp  
**Verify-on-exit impact (D vs A):** +0.0pp  
**Full-stack impact (E vs A):** +3.3pp ✅  
**Best config:** E — all middleware active  

### Notes

- 150 total runs (30 tasks × 5 configs), all completed
- Direct Claude Agent SDK runner (no claw-forge CLI subprocess)
- Tasks: fizzbuzz → protocol_parser (easy/medium/hard tiers)
- Config E is the recommended production stack:
  `claw-forge run --edit-mode hashline --loop-detect-threshold 5 --verify-on-exit`

## Terminal Bench 2.0 Results — YYYY-MM-DD

Model: `model-name`

| Config | Score | ± | Pass Rate | Δ vs A | Runs | Errors |
|--------|------:|--:|----------:|-------:|-----:|-------:|
| A — baseline | XX.X | ±Y.Y | ZZ% | — | N | 0 |
| B — hashline | XX.X | ±Y.Y | ZZ% | +N.N | N | 0 |
| C — verify   | XX.X | ±Y.Y | ZZ% | +N.N | N | 0 |
| D — loop     | XX.X | ±Y.Y | ZZ% | +N.N | N | 0 |
| E — full     | XX.X | ±Y.Y | ZZ% | +N.N | N | 0 |

**Hashline impact (B vs A):** +X.X pts  
**Full-stack impact (E vs A):** +X.X pts  
**Best single change:** Config X (+N.N pts)  

### Notes

- Model: `model-name`
- Repetitions: N per config
- Tasks: 89 (full Terminal Bench 2.0 suite)
- Harbor run ID: `TBD`

---
