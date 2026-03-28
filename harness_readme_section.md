---

## Harness Design Patterns

claw-forge includes advanced harness patterns inspired by Anthropic's research on long-running AI applications. These patterns improve output quality, manage context limits, and enable strategic decision-making during multi-iteration agent workflows.

### Context Resets (`--reset-threshold`)

**Problem:** Long-running agent sessions eventually hit context limits or degrade due to accumulated conversation history ("context anxiety"). The agent may prematurely wrap up work to avoid losing context.

**Solution:** After N tool calls, the builder saves a structured `HANDOFF.md` artifact and spawns a fresh builder with it as context. The new builder gets a clean slate with just the essential state.

```python
from claw_forge.harness import ContextResetManager, HandoffArtifact

# Configure: trigger reset after 80 tool calls
reset_mgr = ContextResetManager(project_dir="/path/to/project", threshold=80)

# Track progress
for task in tasks:
    result = await agent.run(task)
    if reset_mgr.record_tool_call():  # Returns True when threshold reached
        # Save handoff and spawn fresh builder
        handoff = HandoffArtifact(
            completed=["feat: auth (abc123)", "feat: database (def456)"],
            state=["src/auth.py — 150 lines", "tests/ — 85% coverage"],
            next_steps=["Add rate limiting", "Write API docs"],
            decisions_made=["Using SQLite for local dev"],
            quality_bar="6.5/10 — needs error handling",
        )
        reset_mgr.save_handoff(handoff)
        # Spawn new builder with HANDOFF.md as context
        await spawn_fresh_builder(project_dir="/path/to/project")
```

**HANDOFF.md schema:**
- `## Completed` — Items done (with commit hashes for traceability)
- `## State` — Current codebase structure, test coverage, file counts
- `## Next Steps` — Ordered action items for the next builder
- `## Decisions Made` — Architectural decisions to avoid revisiting
- `## Quality Bar` — Current evaluator score, what needs improvement

### Adversarial Review (`--adversarial-review`)

**Problem:** Agents are overly optimistic about their own work. Self-evaluation scores are inflated (average 8.5/10 even for mediocre output), and vague praise ("looks good!") provides no actionable feedback.

**Solution:** Separate the generator from the evaluator. The evaluator uses a skeptical, evidence-based rubric with weighted grading dimensions:

| Dimension | Weight | Focus |
|-----------|--------|-------|
| Correctness | ×3 | Bugs, edge cases, error handling |
| Completeness | ×3 | Missing features, unimplemented specs |
| Quality | ×2 | Maintainability, duplication, architecture |
| Originality | ×1 | Novel approaches, design choices |

```python
from claw_forge.harness import AdversarialEvaluator, GradingDimension

evaluator = AdversarialEvaluator(
    approval_threshold=7.0,
    dimensions=[
        GradingDimension.CORRECTNESS,  # ×3
        GradingDimension.COMPLETENESS,  # ×3
        GradingDimension.QUALITY,  # ×2
        GradingDimension.ORIGINALITY,  # ×1
    ],
)

# Run adversarial review (via reviewer plugin with --adversarial flag)
# The evaluator returns:
# - Per-dimension scores (1-10) with specific evidence
# - Overall weighted score
# - Verdict: APPROVE or REQUEST_CHANGES
# - Actionable findings (blocking issues, suggestions)
```

**Adversarial prompt features:**
- "Assume the code has bugs until proven otherwise"
- Requires specific evidence (file names, line numbers, test names)
- Few-shot examples calibrated to distinguish good vs. bad reviews
- Generic praise ("well done!") is explicitly discouraged

### Strategic Pivot

**Problem:** Agents can get stuck in a local optimum, iterating endlessly on an approach that isn't converging. Declining scores over multiple iterations signal that the current direction is flawed.

**Solution:** Track evaluator scores across iterations and force a strategic decision after each review cycle:

- **Score ≥ threshold (7.0)** → `APPROVE` — work meets quality bar
- **Score trending up** → `REFINE` — continue with improvements
- **Score flat, below threshold** → `REFINE` — iterate with specific changes
- **Score declining for 2+ iterations** → `PIVOT` — abandon approach, try something different

```python
from claw_forge.harness import PivotTracker, PivotAction

tracker = PivotTracker(
    forced_pivot_streak=2,  # Force PIVOT after 2 consecutive declining scores
    approval_threshold=7.0,
)

# After each evaluator cycle:
decision = tracker.decide(score=6.2, iteration=3)
if decision.action == PivotAction.PIVOT:
    logger.warning("Scores declining: 7.5 → 6.8 → 6.2. Pivoting to new approach.")
    # Log to PLAN.md for traceability
    tracker.log_to_plan("PLAN.md")
    # Agent switches strategies entirely
elif decision.action == PivotAction.REFINE:
    logger.info("Score improving or flat. Continue with evaluator feedback.")
    # Agent iterates on current approach
elif decision.action == PivotAction.APPROVE:
    logger.info("Score meets threshold. Work approved.")
    # Agent finalizes and exits
```

**Pivot log in PLAN.md:**
```markdown
## Pivot Decision Log

### Iteration 3 — PIVOT
- **Score:** 6.2/10
- **Trend:** 7.5 → 6.8 → 6.2
- **Reasoning:** Score declining for 2+ consecutive iterations (7.5 → 6.8 → 6.2). Current approach is not converging — pivot to a different strategy.
- **Time:** 2026-03-28T12:34:56Z
```

### Usage

These patterns are integrated into the reviewer and coding plugins:

```bash
# Enable adversarial review in the reviewer plugin
claw-forge run --config reviewer.yaml  # with config: {adversarial: true}

# Coding plugin automatically loads HANDOFF.md when resuming
claw-forge run  # continues from previous handoff if HANDOFF.md exists
```

See the [`claw_forge.harness`](claw_forge/harness/) module for full API documentation and [`docs/harness-patterns.md`](docs/harness-patterns.md) for detailed usage patterns.

---

