# Harness Design Patterns

This guide explains when and how to use the three Anthropic-inspired harness patterns in claw-forge: **context resets**, **adversarial review**, and **strategic pivot**.

## Context Resets

### When to use

Use context resets when:
- Building features that take **80+ tool calls** (typically >2 hours of agent work)
- The agent is **wrapping up prematurely** to avoid losing context
- You need **multiple iterations** on a large codebase
- Working with **limited context windows** (<200K tokens)

### How it works

After N tool calls (default: 80), the coding agent:
1. Saves a `HANDOFF.md` file to the project root
2. Stops the current session
3. Spawns a fresh builder with `HANDOFF.md` as its only context

The new builder gets a clean slate — no degraded conversation history, just the structured state it needs to continue.

### HANDOFF.md schema

```markdown
# HANDOFF.md — Builder Context Reset

**Iteration:** 2
**Total Tool Calls:** 160

## Completed
- feat: JWT authentication flow (commit: abc123)
- feat: user CRUD with SQLAlchemy (commit: def456)
- tests: 47 tests passing, 92% coverage

## State
- src/auth.py — 230 lines, OAuth2 PKCE implemented
- src/models/user.py — User model with bcrypt password hashing
- tests/test_auth.py — JWT flow tests, edge cases covered
- Database: SQLite for local dev, PostgreSQL for prod

## Next Steps
1. Add rate limiting to all /auth/ endpoints
2. Implement refresh token rotation
3. Write integration tests for logout flow

## Decisions Made
- Using python-jose for JWT (not authlib)
- SQLite for local dev (easier setup than PostgreSQL)
- bcrypt with cost factor 12 for password hashing
- Refresh tokens valid for 7 days, access tokens for 1 hour

## Quality Bar
6.5/10 — core auth flow works, needs rate limiting and better error handling
```

### Example usage

```python
from claw_forge.harness import ContextResetManager, HandoffArtifact

# In your coding plugin or agent loop
reset_mgr = ContextResetManager(project_dir=".", threshold=80)

for task in tasks:
    result = await agent.run(task)

    # Check if we need a context reset
    if reset_mgr.record_tool_call():
        # Build handoff artifact
        handoff = HandoffArtifact(
            completed=get_completed_items(),
            state=get_current_state(),
            next_steps=get_remaining_tasks(),
            decisions_made=get_architectural_decisions(),
            quality_bar=f"{evaluator_score:.1f}/10 — {feedback}",
        )
        reset_mgr.save_handoff(handoff)

        # Spawn fresh builder (your orchestration layer handles this)
        await spawn_fresh_builder(cwd=".")
        break  # exit current session
```

### Key benefits

- **Prevents context anxiety** — agents don't wrap up early to save tokens
- **Clean slate each iteration** — no accumulated noise from long conversations
- **Traceability** — `HANDOFF.md` records what was done, what's next, and why
- **Resumability** — handoff file survives crashes, enables manual inspection

---

## Adversarial Review

### When to use

Use adversarial review when:
- You need **high-quality output** with minimal human review
- The agent is **overly optimistic** about its own work
- You want **structured feedback** with specific, actionable findings
- Building **production code** where correctness matters

### How it works

The reviewer plugin runs in **adversarial mode** (`--adversarial` flag):
- Uses a skeptical system prompt: "Assume the code has bugs until proven otherwise"
- Scores work across **4 weighted dimensions** (correctness ×3, completeness ×3, quality ×2, originality ×1)
- Requires **specific evidence** for every score (file names, line numbers, test names)
- Returns structured JSON with per-dimension scores, findings, and a verdict

### Grading dimensions

| Dimension | Weight | What it checks |
|-----------|--------|----------------|
| **Correctness** | ×3 | Bugs, edge cases, error handling, security issues |
| **Completeness** | ×3 | Missing features, unimplemented specs, test coverage |
| **Quality** | ×2 | Maintainability, duplication, architecture, documentation |
| **Originality** | ×1 | Novel approaches, design patterns, code reuse |

### Example output

```json
{
  "overall_score": 6.2,
  "verdict": "request_changes",
  "summary": "Auth flow is implemented but missing rate limiting, refresh token rotation, and has a bare except that masks errors.",
  "dimensions": [
    {"dimension": "correctness", "score": 7.0, "weight": 3, "reasoning": "JWT flow works but bare except at line 142 masks ConnectionError"},
    {"dimension": "completeness", "score": 4.0, "weight": 3, "reasoning": "Rate limiting and refresh token rotation are missing"},
    {"dimension": "quality", "score": 7.0, "weight": 2, "reasoning": "Clean structure, good type hints"},
    {"dimension": "originality", "score": 6.0, "weight": 1, "reasoning": "Standard OAuth2 flow, no novel patterns"}
  ],
  "findings": [
    "🔴 BLOCKING: Rate limiting missing (spec requirement)",
    "🔴 BLOCKING: Bare except at src/auth.py:142 masks errors",
    "🟡 SUGGESTION: Add refresh token rotation",
    "🟡 SUGGESTION: Extract duplicated validation logic (lines 89, 112, 134)"
  ]
}
```

### Example usage

```python
from claw_forge.harness import AdversarialEvaluator, GradingDimension

evaluator = AdversarialEvaluator(
    approval_threshold=7.0,
    dimensions=list(GradingDimension),  # all 4 dimensions
)

# After a coding agent completes work:
# 1. Run adversarial review (via reviewer plugin with --adversarial)
reviewer_prompt = evaluator.get_system_prompt()
result = await reviewer_agent.run(reviewer_prompt, code=produced_code)

# 2. Parse the evaluation
eval_result = evaluator.parse_llm_response(result, iteration=1)

# 3. Check verdict
if eval_result.verdict == "approve":
    logger.info(f"Work approved (score: {eval_result.overall_score:.1f}/10)")
else:
    logger.warning(f"Request changes (score: {eval_result.overall_score:.1f}/10)")
    for finding in eval_result.findings:
        logger.error(f"  {finding}")

# 4. Feed score to pivot tracker for strategic decision
decision = pivot_tracker.decide(eval_result.overall_score, iteration=1)
```

### Key benefits

- **Counters optimism bias** — skeptical evaluator finds issues the generator misses
- **Evidence-based scoring** — every score requires specific code references
- **Actionable feedback** — structured findings tell the generator exactly what to fix
- **Few-shot calibration** — examples teach the evaluator what "good" and "bad" reviews look like

---

## Strategic Pivot

### When to use

Use strategic pivot when:
- Running **multi-iteration workflows** with adversarial review
- The agent is **stuck in a loop**, iterating without improvement
- You need **traceability** for strategic decisions (logged to PLAN.md)
- You want **automatic intervention** when scores decline

### How it works

After each adversarial evaluation, the pivot tracker:
1. Records the score and analyzes the trend (improving, flat, declining)
2. Makes a strategic decision: `REFINE`, `PIVOT`, or `APPROVE`
3. Logs the decision to `PLAN.md` for audit trail
4. Forces a **PIVOT** after 2+ consecutive declining scores (configurable)

### Decision logic

| Condition | Decision | Rationale |
|-----------|----------|-----------|
| Score ≥ threshold (7.0) | `APPROVE` | Work meets quality bar — finalize |
| Score trending up | `REFINE` | Current direction is working — iterate |
| Score flat, below threshold | `REFINE` | Iterate with evaluator feedback |
| Score declining 2+ times | `PIVOT` | Current approach isn't converging — abandon it |

### Example pivot log

```markdown
## Pivot Decision Log

### Iteration 1 — REFINE
- **Score:** 5.5/10
- **Trend:** 5.5
- **Reasoning:** Score 5.5 is below threshold (7.0) but trend is flat (first iteration). Continue refining current approach with evaluator feedback.
- **Time:** 2026-03-28T10:15:30Z

### Iteration 2 — REFINE
- **Score:** 6.2/10
- **Trend:** 5.5 → 6.2
- **Reasoning:** Score 6.2 is below threshold (7.0) but trend is improving. Continue refining current approach with evaluator feedback.
- **Time:** 2026-03-28T10:45:12Z

### Iteration 3 — PIVOT
- **Score:** 5.8/10
- **Trend:** 5.5 → 6.2 → 5.8
- **Reasoning:** Score declining for 2+ consecutive iterations (5.5 → 6.2 → 5.8). Current approach is not converging — pivot to a different strategy.
- **Time:** 2026-03-28T11:20:45Z
```

### Example usage

```python
from claw_forge.harness import PivotTracker, PivotAction

tracker = PivotTracker(
    forced_pivot_streak=2,  # Force PIVOT after 2 consecutive declines
    approval_threshold=7.0,
)

# In your orchestration loop:
for iteration in range(1, max_iterations + 1):
    # 1. Run coding agent
    code = await coding_agent.run(task)

    # 2. Run adversarial review
    eval_result = await adversarial_reviewer.run(code)

    # 3. Make strategic decision
    decision = tracker.decide(eval_result.overall_score, iteration=iteration)

    # 4. Act on decision
    if decision.action == PivotAction.APPROVE:
        logger.info("Work approved — finalizing")
        break
    elif decision.action == PivotAction.REFINE:
        logger.info(f"Refining: {decision.reasoning}")
        # Feed evaluator feedback to coding agent
        task = f"Fix these issues:\n" + "\n".join(eval_result.findings)
        continue
    elif decision.action == PivotAction.PIVOT:
        logger.warning(f"Pivoting: {decision.reasoning}")
        # Switch to entirely different approach
        task = f"Try a different strategy: {alternative_approach}"
        continue

# 5. Log all decisions to PLAN.md
tracker.log_to_plan("PLAN.md")
```

### Key benefits

- **Automatic intervention** — prevents endless iteration on failing approaches
- **Traceability** — all strategic decisions logged to `PLAN.md` with reasoning
- **Configurable thresholds** — adjust pivot streak and approval bar per project
- **Integration with adversarial review** — uses evaluator scores for decision-making

---

## Combining All Three Patterns

The most powerful workflow combines all three patterns:

1. **Coding agent** implements feature with **context reset** tracking
2. **Adversarial evaluator** reviews work and produces score
3. **Pivot tracker** decides: REFINE (improve), PIVOT (new approach), or APPROVE (done)
4. If threshold reached → **context reset** spawns fresh builder with `HANDOFF.md`
5. Loop continues until `APPROVE` or max iterations

```python
from claw_forge.harness import (
    ContextResetManager,
    HandoffArtifact,
    AdversarialEvaluator,
    PivotTracker,
    PivotAction,
)

reset_mgr = ContextResetManager(threshold=80)
evaluator = AdversarialEvaluator(approval_threshold=7.0)
pivot_tracker = PivotTracker(forced_pivot_streak=2)

for iteration in range(1, 10):
    # Run builder (resumes from HANDOFF.md if exists)
    if reset_mgr.handoff_path.exists():
        handoff = reset_mgr.load_handoff()
        prompt = reset_mgr.build_reset_prompt(handoff)
    else:
        prompt = "Implement feature X"

    code = await builder_agent.run(prompt)

    # Check for context reset
    if reset_mgr.record_tool_call():
        reset_mgr.save_handoff(build_handoff())
        await spawn_fresh_builder()
        continue

    # Adversarial review
    eval_result = evaluator.parse_llm_response(
        await reviewer_agent.run(evaluator.get_system_prompt(), code=code),
        iteration=iteration,
    )

    # Strategic pivot decision
    decision = pivot_tracker.decide(eval_result.overall_score, iteration=iteration)

    if decision.action == PivotAction.APPROVE:
        logger.info("Work approved!")
        break
    elif decision.action == PivotAction.PIVOT:
        logger.warning("Pivoting to new approach...")
        # Update task with alternative strategy
    else:  # REFINE
        # Feed evaluator feedback to builder
        pass

# Log decisions to PLAN.md
pivot_tracker.log_to_plan("PLAN.md")
```

---

## Further Reading

- [`claw_forge.harness`](../claw_forge/harness/) — API documentation for all harness modules
- [`README.md`](../README.md#harness-design-patterns) — Quick reference with code examples
- Anthropic's harness design research (blog posts, 2024)
