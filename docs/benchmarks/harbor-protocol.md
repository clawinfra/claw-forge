# Harbor API Protocol Reference

This document describes the Harbor agent protocol as used by the Terminal Bench 2.0
evaluation harness (`scripts/eval/harbor_adapter.py`).

## Base URL

Default: `https://api.harborframework.com`

Configurable via `--harbor-url` CLI flag or `HARBOR_BASE_URL` environment variable.

## Authentication

All requests include:
- `Authorization: Bearer {HARBOR_API_KEY}`
- `Content-Type: application/json`

## Endpoints

### GET `/api/v1/tasks`

List all task IDs available in this Harbor benchmark run.

**Response:**
```json
["task-001", "task-002", "task-003", ...]
```

### POST `/api/v1/tasks/{task_id}/start`

Start a task and retrieve its specification (sandbox, scoring URL, timeout).

**Response:**
```json
{
  "task_id": "task-042",
  "description": "Implement a Python function that ...",
  "sandbox_url": "https://sandbox-xyz.daytona.io",
  "working_dir": "/workspace/task-042",
  "scoring_url": "https://api.harborframework.com/api/v1/tasks/task-042/score",
  "timeout_s": 300,
  "metadata": {}
}
```

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | string | Unique task identifier |
| `description` | string | Natural-language task description |
| `sandbox_url` | string | Daytona sandbox SSH/HTTP endpoint |
| `working_dir` | string | Absolute path inside the sandbox |
| `scoring_url` | string | URL to submit agent output for scoring |
| `timeout_s` | int | Per-task timeout in seconds |
| `metadata` | object | Extra fields (forward-compatible) |

### POST `{scoring_url}`

Submit agent output for scoring. The `scoring_url` is task-specific and returned
by the start endpoint.

**Request body:**
```json
{
  "task_id": "task-042",
  "agent_output": "The final output text from the agent..."
}
```

**Response:**
```json
{
  "score": 85.5,
  "passed": true,
  "details": {
    "correctness": 90.0,
    "style": 80.0
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `score` | float | 0.0–100.0 scoring scale |
| `passed` | bool | Whether Harbor considers this a pass |
| `details` | object | Per-criterion breakdown (forward-compatible) |

## Error Handling

| Status | Meaning | Retry? |
|--------|---------|--------|
| 200 | Success | — |
| 401 | Invalid API key | No |
| 404 | Task not found | No |
| 429 | Rate limited | Yes (backoff) |
| 500-599 | Server error | Yes (2 retries, 2s delay) |

## Retry Policy

- **5xx errors:** 2 automatic retries with 2-second fixed delay
- **4xx errors:** No retry (immediate failure)
- **Network errors:** 2 retries with 2-second delay
- **`run_agent()` failures:** No retry (cost control; reps provide statistical coverage)

## Integration with claw-forge

The adapter translates Harbor tasks to `run_agent()` calls:

```
AblationConfig.edit_mode      → edit_mode parameter
AblationConfig.pre_completion → hooks["pre_completion_checklist"]
AblationConfig.loop_detection → hooks["loop_detection"]
HarborTask.working_dir        → cwd parameter
model flag                    → model parameter
```

The agent's final `ResultMessage.result` text is submitted back to Harbor for scoring.
