"""Export session and task data from state.db.

Pure functions that read the SQLite database directly via ``sqlite3``
(no SQLAlchemy, no state-service dependency). Each function accepts a
DB path, an optional session filter, and an output path, and returns
the resolved output path.

See ``docs/superpowers/specs/2026-04-29-export-command-design.md``.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from claw_forge import __version__ as _CLAW_FORGE_VERSION

# Columns for the flat-CSV output, in spec order. Kept here so tests
# and callers can both reference the canonical schema.
CSV_FLAT_COLUMNS: tuple[str, ...] = (
    "session_id",
    "project_path",
    "session_status",
    "session_created_at",
    "task_id",
    "plugin_name",
    "description",
    "category",
    "status",
    "priority",
    "depends_on",
    "steps",
    "error_message",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "created_at",
    "started_at",
    "completed_at",
)

# Tables exported in CSV-split and SQL modes, in dependency order
# (sessions before tasks/events to satisfy FK constraints on import).
_EXPORT_TABLES: tuple[str, ...] = ("sessions", "tasks", "events")

# How each table is filtered when --scope session is used. The value is
# the column name to match against the target session id.
_SESSION_FILTER_COLUMN: dict[str, str] = {
    "sessions": "id",
    "tasks": "session_id",
    "events": "session_id",
}

# JSON-encoded list columns whose payloads are decoded back into lists
# in JSON export. Other JSON columns (manifest_json, result_json,
# events.payload) are preserved as-is — they may be dicts and have no
# canonical list shape.
_TASK_LIST_COLUMNS: frozenset[str] = frozenset({"depends_on", "steps"})


def _decode_json_list(raw: Any) -> list[str]:
    """Decode a JSON-encoded list column to a list of strings.

    Returns ``[]`` for None, empty strings, or malformed payloads.
    """
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if isinstance(decoded, list):
        return [str(item) for item in decoded]
    return []


def _decode_json_value(raw: Any) -> Any:
    """Decode a JSON-encoded column to its native value.

    Returns ``None`` for null/empty input or malformed payloads. Used
    for non-list JSON columns (manifest_json, result_json, payload).
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _semicolon_join(items: list[str]) -> str:
    """Join list items with ';' — matches spec's CSV serialization."""
    return ";".join(items)


def _format_cell(value: Any) -> str:
    """Format a cell value for CSV: None → '', everything else → str()."""
    if value is None:
        return ""
    return str(value)


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """Return column names for *table* in CREATE-TABLE order."""
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [row[1] for row in rows]


def export_csv_flat(
    db_path: Path,
    session_id: str | None,
    out: Path,
) -> Path:
    """Export sessions+tasks to a single flat CSV.

    One row per task with session fields denormalized into each row.
    ``depends_on`` and ``steps`` are serialized as ``;``-separated strings.
    Null values become empty strings.

    Returns *out*.
    """
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    query = (
        "SELECT "
        "  s.id, s.project_path, s.status, s.created_at, "
        "  t.id, t.plugin_name, t.description, t.category, t.status, t.priority, "
        "  t.depends_on, t.steps, t.error_message, "
        "  t.input_tokens, t.output_tokens, t.cost_usd, "
        "  t.created_at, t.started_at, t.completed_at "
        "FROM sessions s "
        "JOIN tasks t ON t.session_id = s.id "
    )
    params: tuple[Any, ...] = ()
    if session_id is not None:
        query += "WHERE s.id = ? "
        params = (session_id,)
    query += "ORDER BY s.created_at, t.created_at, t.id"

    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute(query, params).fetchall()

    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_FLAT_COLUMNS)
        for row in rows:
            (
                s_id,
                s_project,
                s_status,
                s_created,
                t_id,
                t_plugin,
                t_desc,
                t_cat,
                t_status,
                t_priority,
                t_depends,
                t_steps,
                t_err,
                t_in_tok,
                t_out_tok,
                t_cost,
                t_created,
                t_started,
                t_completed,
            ) = row
            writer.writerow([
                _format_cell(s_id),
                _format_cell(s_project),
                _format_cell(s_status),
                _format_cell(s_created),
                _format_cell(t_id),
                _format_cell(t_plugin),
                _format_cell(t_desc),
                _format_cell(t_cat),
                _format_cell(t_status),
                _format_cell(t_priority),
                _semicolon_join(_decode_json_list(t_depends)),
                _semicolon_join(_decode_json_list(t_steps)),
                _format_cell(t_err),
                _format_cell(t_in_tok),
                _format_cell(t_out_tok),
                _format_cell(t_cost),
                _format_cell(t_created),
                _format_cell(t_started),
                _format_cell(t_completed),
            ])

    return out


def export_csv_split(
    db_path: Path,
    session_id: str | None,
    out_dir: Path,
) -> Path:
    """Export sessions, tasks, events to one CSV per table in *out_dir*.

    Each CSV mirrors the table schema directly (no denormalization).
    When *session_id* is provided, rows are filtered to that session
    (sessions filtered by ``id``; tasks/events by ``session_id``).

    Returns *out_dir*.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(db_path)) as conn:
        for table in _EXPORT_TABLES:
            columns = _table_columns(conn, table)
            if not columns:
                # Table doesn't exist in this DB (older schema); skip.
                continue
            quoted_cols = ", ".join(f'"{c}"' for c in columns)
            query = f'SELECT {quoted_cols} FROM "{table}"'
            params: tuple[Any, ...] = ()
            if session_id is not None:
                filter_col = _SESSION_FILTER_COLUMN[table]
                query += f' WHERE "{filter_col}" = ?'
                params = (session_id,)
            rows = conn.execute(query, params).fetchall()

            csv_path = out_dir / f"{table}.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(columns)
                for row in rows:
                    writer.writerow([_format_cell(v) for v in row])

    return out_dir


def _patch_create_if_not_exists(line: str) -> str:
    """Rewrite ``CREATE TABLE/INDEX`` to add ``IF NOT EXISTS``.

    ``sqlite3.Connection.iterdump`` emits bare ``CREATE`` statements;
    the spec requires ``IF NOT EXISTS`` so the dump can be applied to a
    pre-seeded DB without aborting. Idempotent: a line that already
    contains ``IF NOT EXISTS`` is returned unchanged.
    """
    prefixes = (
        ("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS "),
        ("CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX IF NOT EXISTS "),
        ("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS "),
    )
    if "IF NOT EXISTS" in line:
        return line
    for old, new in prefixes:
        if line.startswith(old):
            return new + line[len(old):]
    return line


def _build_filtered_dump_db(
    src: sqlite3.Connection, session_id: str
) -> sqlite3.Connection:
    """Build an in-memory DB with rows filtered to *session_id*.

    Schema (CREATE TABLE/INDEX statements) is copied from *src* via
    ``sqlite_master``. Rows are copied from each table whose filter
    column matches *session_id*. Returns the in-memory connection so
    the caller can run ``iterdump()`` on it.
    """
    mem = sqlite3.connect(":memory:")

    # Copy all schema objects from the source. We exclude internal
    # SQLite tables (sqlite_*) and rows where ``sql`` is NULL (auto
    # indexes for primary keys).
    schema_rows = src.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE sql IS NOT NULL "
        "  AND name NOT LIKE 'sqlite_%' "
        "ORDER BY type DESC, name"
    ).fetchall()
    for (sql_stmt,) in schema_rows:
        mem.execute(sql_stmt)

    # Copy filtered data, table by table.
    for table in _EXPORT_TABLES:
        columns = _table_columns(src, table)
        if not columns:
            continue
        quoted_cols = ", ".join(f'"{c}"' for c in columns)
        placeholders = ", ".join("?" for _ in columns)
        filter_col = _SESSION_FILTER_COLUMN[table]
        rows = src.execute(
            f'SELECT {quoted_cols} FROM "{table}" '
            f'WHERE "{filter_col}" = ?',
            (session_id,),
        ).fetchall()
        if rows:
            mem.executemany(
                f'INSERT INTO "{table}" ({quoted_cols}) VALUES ({placeholders})',
                rows,
            )
    mem.commit()
    return mem


def export_sql(
    db_path: Path,
    session_id: str | None,
    out: Path,
) -> Path:
    """Export sessions+tasks+events as a SQL dump (CREATE+INSERT).

    Output is directly importable: ``sqlite3 newdb.db < out.sql``.

    When *session_id* is None, the entire database is dumped. Otherwise
    only rows matching that session are included (filtered through an
    in-memory copy that preserves schema).

    All ``CREATE TABLE`` / ``CREATE INDEX`` statements are rewritten to
    use ``IF NOT EXISTS`` so the dump can be applied to a pre-seeded
    DB without aborting.

    Returns *out*.
    """
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(db_path)) as src:
        if session_id is None:
            dump_iter = src.iterdump()
            with out.open("w", encoding="utf-8") as fh:
                for line in dump_iter:
                    fh.write(_patch_create_if_not_exists(line))
                    fh.write("\n")
        else:
            mem = _build_filtered_dump_db(src, session_id)
            try:
                with out.open("w", encoding="utf-8") as fh:
                    for line in mem.iterdump():
                        fh.write(_patch_create_if_not_exists(line))
                        fh.write("\n")
            finally:
                mem.close()

    return out


def _row_to_session_dict(
    row: sqlite3.Row,
    session_columns: list[str],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in session_columns:
        value = row[col]
        if col == "manifest_json":
            out[col] = _decode_json_value(value)
        else:
            out[col] = value
    return out


def _row_to_task_dict(
    row: sqlite3.Row,
    task_columns: list[str],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in task_columns:
        value = row[col]
        if col in _TASK_LIST_COLUMNS:
            out[col] = _decode_json_list(value)
        elif col == "result_json":
            out[col] = _decode_json_value(value)
        else:
            out[col] = value
    return out


def export_json(
    db_path: Path,
    session_id: str | None,
    out: Path,
) -> Path:
    """Export to a JSON file matching the state-service API shape.

    Top-level shape::

        {
          "exported_at": "<ISO 8601 UTC>",
          "claw_forge_version": "<x.y.z>",
          "scope": "session" | "all",
          "sessions": [
            {
              "id": "...", "project_path": "...", "status": "...",
              "created_at": "...", ...,
              "tasks": [ {...task...}, ... ]
            },
            ...
          ]
        }

    When *session_id* is None, every session is included (``scope=all``).
    Otherwise only the matching session and its tasks are emitted
    (``scope=session``).

    Returns *out*.
    """
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        session_columns = _table_columns(conn, "sessions")
        task_columns = _table_columns(conn, "tasks")
        session_cols_sql = ", ".join(f'"{c}"' for c in session_columns)
        task_cols_sql = ", ".join(f'"{c}"' for c in task_columns)

        if session_id is None:
            session_rows = conn.execute(
                f"SELECT {session_cols_sql} FROM sessions ORDER BY created_at"
            ).fetchall()
            scope = "all"
        else:
            session_rows = conn.execute(
                f"SELECT {session_cols_sql} FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchall()
            scope = "session"

        sessions_out: list[dict[str, Any]] = []
        for s_row in session_rows:
            session_dict = _row_to_session_dict(s_row, session_columns)
            task_rows = conn.execute(
                f"SELECT {task_cols_sql} FROM tasks "
                "WHERE session_id = ? ORDER BY created_at, id",
                (session_dict["id"],),
            ).fetchall()
            session_dict["tasks"] = [
                _row_to_task_dict(t_row, task_columns) for t_row in task_rows
            ]
            sessions_out.append(session_dict)

    payload = {
        "exported_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "claw_forge_version": _CLAW_FORGE_VERSION,
        "scope": scope,
        "sessions": sessions_out,
    }

    with out.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)

    return out
