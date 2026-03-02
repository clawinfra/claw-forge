# Parallel Dispatch

## When to use this skill
Use when facing 3 or more independent tasks that don't share files or state — dispatch agents simultaneously instead of sequentially.

## Protocol
1. **Identify independence** — confirm tasks have no shared files and no ordering dependency.
   - Ask: "Does task B need output from task A?" → if yes, they're sequential, not parallel.
   - Ask: "Do tasks A and B write to the same file?" → if yes, keep them sequential.

2. **Group by domain** — one agent per domain (e.g. auth module, database layer, frontend, tests).

3. **Write a manifest per agent** — before dispatching, define:
   - What files/directories this agent owns
   - What it must NOT touch
   - The exact task description

4. **Dispatch all agents simultaneously** — spawn all at once, do not wait for one before starting the next.

5. **Collect results** — wait for all agents to complete. If one fails, retry that domain only. Do not re-run successful agents.

6. **Verify no conflicts** — after all complete, run `git diff --stat` and check for merge conflicts.

## Commands
```bash
# After parallel work completes, check for conflicts
git status
git diff --stat

# If merge conflicts exist
git diff --diff-filter=U --name-only

# Run tests to verify combined output is correct
uv run pytest tests/ -q
```

## Output interpretation
Decision matrix:

| Condition                              | Use sequential | Use parallel |
|----------------------------------------|----------------|--------------|
| Task B needs Task A's output           | ✓              |              |
| Tasks write to the same file           | ✓              |              |
| Fewer than 3 tasks                     | ✓              |              |
| 3+ tasks in different domains/files    |                | ✓            |
| 3+ tasks in different languages        |                | ✓            |
| Independent test suites                |                | ✓            |

Signs of a bad parallel dispatch:
- Two agents edited the same file → merge conflict
- Agent B started before Agent A finished a shared dependency → runtime error
- One agent was unnecessary because another covered the same files

## Done criteria
- All dispatched agents report complete
- No merge conflicts between agent outputs
- Full test suite passes on the merged result
- Each agent stayed within its declared file domain
