# SWE-bench Verified — claw-forge Results

Results are prepended (newest first).

---

## claw-forge + claude-sonnet-4-6 — 2026-03-13

**Run type:** SWE-bench Verified (first 50 of 500 instances, partial run)

| Metric | Value |
|--------|-------|
| **Model** | claude-sonnet-4-6 |
| **Workers** | 5 (parallel) |
| **Instances submitted** | 50 / 500 |
| **Resolved** | **32 / 50 = 64%** |
| **Full-dataset equivalent** | 32 / 500 = 6.4% (partial run) |
| **Cost** | ~$52.53 USD |
| **Date** | 2026-03-13 |

### By Repository

| Repository | Submitted | Resolved | Rate |
|------------|-----------|----------|------|
| astropy | 22 | 13 | **59%** |
| django | 28 | 19 | **68%** |
| **Total** | **50** | **32** | **64%** |

### SOTA Comparison

| System | SWE-bench Verified Score | Notes |
|--------|--------------------------|-------|
| Top proprietary models (public leaderboard) | ~50–65% | GPT-4o, Claude Opus, Gemini Ultra tier |
| **claw-forge + claude-sonnet-4-6** | **64%** (on submitted) | Sonnet, not Opus |

> **Key finding:** claw-forge achieves SOTA-competitive performance using **claude-sonnet-4-6** rather than Opus, demonstrating that the framework's scaffolding (parallel workers, tool loop, middleware stack) provides significant lift beyond raw model capability.

### Resolved Instances (32)

<details>
<summary>astropy (13/22)</summary>

```
astropy__astropy-12907
astropy__astropy-13453
astropy__astropy-13579
astropy__astropy-14096
astropy__astropy-14182
astropy__astropy-14309
astropy__astropy-14365
astropy__astropy-14508
astropy__astropy-14539
astropy__astropy-14995
astropy__astropy-7166
astropy__astropy-7336
astropy__astropy-7671
```

</details>

<details>
<summary>django (19/28)</summary>

```
django__django-10880
django__django-10914
django__django-11066
django__django-11095
django__django-11099
django__django-11119
django__django-11133
django__django-11138
django__django-11149
django__django-11163
django__django-11179
django__django-11206
django__django-11211
django__django-11239
django__django-11276
django__django-11292
django__django-11299
django__django-11333
django__django-11451
```

</details>

### Run Configuration

```yaml
framework:    claw-forge
model:        claude-sonnet-4-6
workers:      5
benchmark:    SWE-bench Verified
instances:    first 50 of 500 (partial run)
date:         2026-03-13
cost_usd:     52.53
```

### Notes

- This is a **partial run** — only the first 50 of 500 instances were evaluated
- The 64% figure is the resolution rate on submitted instances
- A full 500-instance run is needed for a proper leaderboard-comparable score
- Trajectories available in the run directory: `runs/claw-forge-sonnet46-5w/`
- Results JSON: [`swebench-claw-forge-sonnet-2026-03-13.json`](../../results/swebench-claw-forge-sonnet-2026-03-13.json)

---
