# Checkpoint

Save the current project state: git commit all changes with a timestamp, export the feature DB state to a JSON snapshot, and write a summary of what's passing.

## Instructions

### Step 1: Run quality checks

```bash
uv run pytest tests/ -q --no-header 2>&1 | tail -5
```

Note which tests pass/fail — this goes in the commit message.

### Step 2: Export feature state

```bash
# Snapshot the state DB
TIMESTAMP=$(date +%Y%m%dT%H%M%S)
SNAPSHOT_FILE=".claw-forge/snapshots/snapshot-${TIMESTAMP}.json"
mkdir -p .claw-forge/snapshots

# Query the state service
curl -s http://localhost:8420/sessions | python3 -m json.tool > "$SNAPSHOT_FILE" 2>/dev/null || \
  echo '{"note": "state service not running at checkpoint time"}' > "$SNAPSHOT_FILE"

echo "Snapshot saved: $SNAPSHOT_FILE"
```

### Step 3: Write checkpoint summary

Create `.claw-forge/CHECKPOINT.md`:

```markdown
# Checkpoint — <TIMESTAMP>

## Status
- Tests: <N> passing, <M> failing
- Features: <completed>/<total> complete
- Snapshot: snapshots/snapshot-<TIMESTAMP>.json

## What's working
<List of completed features based on state DB>

## What's in progress
<List of running/pending features>

## Known issues
<Any failing tests or blocked features>
```

### Step 4: Git commit

```bash
# Stage everything
git add -A

# Commit with structured message
git commit -m "checkpoint: $(date '+%Y-%m-%d %H:%M:%S')

Status:
- Tests: <N> passing
- Features: <completed>/<total>

See .claw-forge/CHECKPOINT.md for details"
```

### Step 5: Confirm

```
✅ Checkpoint saved!

  Commit: <git hash>
  Snapshot: .claw-forge/snapshots/snapshot-<TIMESTAMP>.json
  Summary: .claw-forge/CHECKPOINT.md

To restore to this state:
  git checkout <hash>
```

### Notes

- Checkpoints are safe to create at any time — they never disrupt running agents
- Run /checkpoint before risky operations (provider changes, schema migrations)
- The JSON snapshot is a point-in-time view of the task graph
