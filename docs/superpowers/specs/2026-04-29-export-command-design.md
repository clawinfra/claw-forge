# Export Command Design

**Date:** 2026-04-29
**Status:** Approved

## Purpose

Add `claw-forge export` command to export session and task data from the state
database in CSV, SQL, or JSON format for audit/reporting, migration, and
integration use cases.

## Command Signature

```
claw-forge export [--format csv|sql|json] [--scope session|all]
                  [--session UUID] [--csv-mode flat|split] [--out PATH]
                  [--project .] [--config claw-forge.yaml]
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--format`, `-f` | `csv` | Output format: `csv`, `sql`, `json` |
| `--scope` | `session` | `session` = one session, `all` = entire DB |
| `--session`, `-s` | latest for project | Override session UUID |
| `--csv-mode` | `flat` | `flat` = one denormalized file, `split` = one file per table |
| `--out`, `-o` | auto-generated | Output path (file or directory for split mode) |
| `--project`, `-p` | `.` | Project directory (to find `.claw-forge/state.db`) |
| `--config`, `-c` | `claw-forge.yaml` | Config file path |

## Output Formats

### CSV flat (default)

Single file with one row per task and session fields denormalized into each row.
Designed for opening in Excel/Google Sheets.

Columns:

```
session_id, project_path, session_status, session_created_at,
task_id, plugin_name, description, category, status, priority,
depends_on, steps, error_message,
input_tokens, output_tokens, cost_usd,
created_at, started_at, completed_at
```

- `depends_on` and `steps` are serialized as semicolon-separated strings
  (`;` delimiter avoids conflicts with CSV commas).
- Null values are empty strings.

### CSV split

Directory containing one CSV per table:

```
claw-forge-export-{id_short}-{timestamp}/
  sessions.csv
  tasks.csv
  events.csv
```

Each CSV mirrors the table schema directly (no denormalization).

### SQL

Standard SQLite dump output — `CREATE TABLE IF NOT EXISTS` + `INSERT`
statements. Directly importable:

```bash
sqlite3 newdb.db < export.sql
```

When `--scope session`, the dump includes only rows matching the selected
session. When `--scope all`, it dumps the full database.

### JSON

Mirrors the state service API response shape:

```json
{
  "exported_at": "2026-04-29T12:00:00Z",
  "claw_forge_version": "0.5.23",
  "scope": "session",
  "sessions": [
    {
      "id": "uuid",
      "project_path": "/path",
      "status": "completed",
      "created_at": "...",
      "tasks": [
        {
          "id": "uuid",
          "plugin_name": "coding",
          "description": "...",
          "category": "...",
          "status": "completed",
          "priority": 0,
          "depends_on": ["task-id-1"],
          "steps": ["step1", "step2"],
          "error_message": null,
          "input_tokens": 1000,
          "output_tokens": 500,
          "cost_usd": 0.05,
          "created_at": "...",
          "started_at": "...",
          "completed_at": "..."
        }
      ]
    }
  ]
}
```

## Auto-generated Filenames

When `--out` is not provided:

```
# session scope
claw-forge-export-{session_id[:8]}-{YYYYMMDD-HHMMSS}.{csv|sql|json}

# all scope
claw-forge-export-all-{YYYYMMDD-HHMMSS}.{csv|sql|json}

# csv split mode — directory
claw-forge-export-{session_id[:8]}-{YYYYMMDD-HHMMSS}/
```

## Architecture

### Module: `claw_forge/exporter.py`

Pure functions that read the SQLite database directly (no state service
dependency). Each function accepts a DB path, optional session filter, and
output path:

```python
def export_csv_flat(db_path: Path, session_id: str | None, out: Path) -> Path
def export_csv_split(db_path: Path, session_id: str | None, out_dir: Path) -> Path
def export_sql(db_path: Path, session_id: str | None, out: Path) -> Path
def export_json(db_path: Path, session_id: str | None, out: Path) -> Path
```

All functions return the output path for confirmation printing.

### CLI: `claw-forge export` in `cli.py`

The Typer command handles:

1. Resolve project path and DB path
2. Resolve session ID (explicit `--session` → `_resolve_latest_session` fallback)
3. Generate output path if not specified
4. Call the appropriate exporter function
5. Print confirmation with path and row counts

### Dependencies

- `sqlite3` (stdlib) — direct DB reads, no SQLAlchemy needed
- `csv` (stdlib) — CSV writing
- `json` (stdlib) — JSON writing
- No new third-party dependencies

## Session Resolution

Reuses the existing `_resolve_latest_session(db_path, project_path)` function
which filters by `project_path` to avoid picking up stale test sessions.

When `--scope all`, session resolution is skipped — all sessions are exported
regardless of project path.

## Error Handling

- DB file not found → clear error with path and hint to run `claw-forge run`
- Session not found → error with available session IDs listed
- Output path already exists → overwrite with warning (no `--force` flag needed)
- Empty result set → warning, still writes file with headers only (CSV) or
  empty array (JSON)

## What's NOT Included

- **No training data format** — the stored data is audit metadata (task
  descriptions, statuses, costs), not conversation transcripts. Full
  prompt/completion pairs would require a conversation capture layer in
  `run_agent()`, which is a separate feature.
- **No import-from-export round-trip** — SQL dump already covers migration.
- **No streaming/pagination** — state databases are small enough to load fully.
- **No event export in flat CSV mode** — events are only included in split CSV
  and SQL formats. The flat CSV focuses on the session→task relationship.

## Console Output

```
$ claw-forge export --format csv --scope session

  Exported 365 tasks from session 8d304d81…
  Format:  CSV (flat)
  Output:  claw-forge-export-8d304d81-20260429-120000.csv

$ claw-forge export --format json --scope all

  Exported 3 sessions, 892 tasks
  Format:  JSON
  Output:  claw-forge-export-all-20260429-120000.json
```
