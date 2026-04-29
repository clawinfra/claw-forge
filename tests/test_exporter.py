"""Tests for claw_forge.exporter."""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import pytest

from claw_forge.exporter import (
    CSV_FLAT_COLUMNS,
    _decode_json_list,
    _decode_json_value,
    _patch_create_if_not_exists,
    export_csv_flat,
    export_csv_split,
    export_json,
    export_sql,
)


def _build_state_db(db_path: Path) -> None:
    """Create a minimal sessions+tasks schema matching state/models.py.

    Mirrors the columns the exporter reads. Datetime columns are stored
    as TEXT (the SQLAlchemy default for SQLite), JSON list columns as
    TEXT containing JSON.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                project_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                project_paused INTEGER NOT NULL DEFAULT 0,
                created_at TEXT,
                updated_at TEXT,
                manifest_json TEXT
            );

            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                plugin_name TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                priority INTEGER NOT NULL DEFAULT 0,
                depends_on TEXT,
                category TEXT,
                steps TEXT NOT NULL DEFAULT '[]',
                result_json TEXT,
                error_message TEXT,
                human_question TEXT,
                human_answer TEXT,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd REAL NOT NULL DEFAULT 0.0,
                active_subagents INTEGER NOT NULL DEFAULT 0,
                parent_task_id TEXT,
                bugfix_retry_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );

            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                task_id TEXT,
                event_type TEXT NOT NULL,
                payload TEXT,
                created_at TEXT,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _seed_event(
    db_path: Path,
    session_id: str,
    *,
    task_id: str | None = None,
    event_type: str = "task_started",
    payload: dict | None = None,
    created_at: str = "2026-04-29T10:00:01",
) -> None:
    payload_str = json.dumps(payload) if payload is not None else None
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO events "
            "(session_id, task_id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, task_id, event_type, payload_str, created_at),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_session(
    db_path: Path,
    session_id: str,
    project_path: str = "/tmp/proj",
    status: str = "completed",
    created_at: str = "2026-04-29T10:00:00",
) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO sessions "
            "(id, project_path, status, project_paused, "
            "created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
            (session_id, project_path, status, created_at, created_at),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_task(
    db_path: Path,
    task_id: str,
    session_id: str,
    *,
    plugin_name: str = "coding",
    description: str | None = "do a thing",
    status: str = "completed",
    priority: int = 0,
    category: str | None = "auth",
    depends_on: list[str] | None = None,
    steps: list[str] | None = None,
    error_message: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    created_at: str | None = "2026-04-29T10:00:01",
    started_at: str | None = "2026-04-29T10:00:02",
    completed_at: str | None = "2026-04-29T10:00:03",
) -> None:
    depends_on_str = json.dumps(depends_on if depends_on is not None else [])
    steps_str = json.dumps(steps if steps is not None else [])
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO tasks "
            "(id, session_id, plugin_name, description, status, priority, "
            "depends_on, category, steps, error_message, "
            "input_tokens, output_tokens, cost_usd, "
            "created_at, started_at, completed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                session_id,
                plugin_name,
                description,
                status,
                priority,
                depends_on_str,
                category,
                steps_str,
                error_message,
                input_tokens,
                output_tokens,
                cost_usd,
                created_at,
                started_at,
                completed_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()


class TestDecodeJsonList:
    def test_none_returns_empty(self) -> None:
        assert _decode_json_list(None) == []

    def test_empty_string_returns_empty(self) -> None:
        assert _decode_json_list("") == []

    def test_valid_json_list(self) -> None:
        assert _decode_json_list('["a", "b"]') == ["a", "b"]

    def test_already_a_list(self) -> None:
        assert _decode_json_list(["x", "y"]) == ["x", "y"]

    def test_malformed_json_returns_empty(self) -> None:
        assert _decode_json_list("not json{") == []

    def test_non_list_json_returns_empty(self) -> None:
        assert _decode_json_list('{"key": "value"}') == []


class TestDecodeJsonValue:
    def test_none_returns_none(self) -> None:
        assert _decode_json_value(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _decode_json_value("") is None

    def test_dict_passthrough(self) -> None:
        assert _decode_json_value({"a": 1}) == {"a": 1}

    def test_list_passthrough(self) -> None:
        assert _decode_json_value([1, 2]) == [1, 2]

    def test_valid_json_dict(self) -> None:
        assert _decode_json_value('{"k": 1}') == {"k": 1}

    def test_malformed_returns_none(self) -> None:
        assert _decode_json_value("not json{") is None


class TestExportCsvFlat:
    def test_returns_output_path(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")
        _seed_task(db, "task-1", "sess-1")

        out = tmp_path / "export.csv"
        result = export_csv_flat(db, "sess-1", out)
        assert result == out
        assert out.exists()

    def test_columns_match_spec(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")
        _seed_task(db, "task-1", "sess-1")

        out = tmp_path / "export.csv"
        export_csv_flat(db, "sess-1", out)

        with out.open() as fh:
            reader = csv.reader(fh)
            header = next(reader)
        assert tuple(header) == CSV_FLAT_COLUMNS

    def test_one_row_per_task(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")
        _seed_task(db, "task-1", "sess-1")
        _seed_task(db, "task-2", "sess-1")
        _seed_task(db, "task-3", "sess-1")

        out = tmp_path / "export.csv"
        export_csv_flat(db, "sess-1", out)

        with out.open() as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 3
        ids = {r["task_id"] for r in rows}
        assert ids == {"task-1", "task-2", "task-3"}

    def test_session_fields_denormalized(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(
            db,
            "sess-1",
            project_path="/work/proj",
            status="completed",
            created_at="2026-04-29T08:00:00",
        )
        _seed_task(db, "task-1", "sess-1")
        _seed_task(db, "task-2", "sess-1")

        out = tmp_path / "export.csv"
        export_csv_flat(db, "sess-1", out)

        with out.open() as fh:
            rows = list(csv.DictReader(fh))
        # Every row carries the session fields.
        for row in rows:
            assert row["session_id"] == "sess-1"
            assert row["project_path"] == "/work/proj"
            assert row["session_status"] == "completed"
            assert row["session_created_at"] == "2026-04-29T08:00:00"

    def test_depends_on_and_steps_semicolon_joined(
        self, tmp_path: Path
    ) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")
        _seed_task(
            db,
            "task-1",
            "sess-1",
            depends_on=["a", "b", "c"],
            steps=["step one", "step two"],
        )

        out = tmp_path / "export.csv"
        export_csv_flat(db, "sess-1", out)

        with out.open() as fh:
            rows = list(csv.DictReader(fh))
        assert rows[0]["depends_on"] == "a;b;c"
        assert rows[0]["steps"] == "step one;step two"

    def test_empty_depends_on_and_steps(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")
        _seed_task(db, "task-1", "sess-1", depends_on=[], steps=[])

        out = tmp_path / "export.csv"
        export_csv_flat(db, "sess-1", out)

        with out.open() as fh:
            rows = list(csv.DictReader(fh))
        assert rows[0]["depends_on"] == ""
        assert rows[0]["steps"] == ""

    def test_null_values_become_empty_strings(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")
        _seed_task(
            db,
            "task-1",
            "sess-1",
            description=None,
            category=None,
            error_message=None,
            started_at=None,
            completed_at=None,
        )

        out = tmp_path / "export.csv"
        export_csv_flat(db, "sess-1", out)

        with out.open() as fh:
            rows = list(csv.DictReader(fh))
        row = rows[0]
        assert row["description"] == ""
        assert row["category"] == ""
        assert row["error_message"] == ""
        assert row["started_at"] == ""
        assert row["completed_at"] == ""

    def test_session_filter_excludes_other_sessions(
        self, tmp_path: Path
    ) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-A", created_at="2026-04-29T08:00:00")
        _seed_session(db, "sess-B", created_at="2026-04-29T09:00:00")
        _seed_task(db, "task-A1", "sess-A")
        _seed_task(db, "task-B1", "sess-B")
        _seed_task(db, "task-B2", "sess-B")

        out = tmp_path / "export.csv"
        export_csv_flat(db, "sess-A", out)

        with out.open() as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 1
        assert rows[0]["task_id"] == "task-A1"

    def test_session_id_none_dumps_all(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-A", created_at="2026-04-29T08:00:00")
        _seed_session(db, "sess-B", created_at="2026-04-29T09:00:00")
        _seed_task(db, "task-A1", "sess-A")
        _seed_task(db, "task-B1", "sess-B")

        out = tmp_path / "export.csv"
        export_csv_flat(db, None, out)

        with out.open() as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 2
        assert {r["task_id"] for r in rows} == {"task-A1", "task-B1"}

    def test_empty_session_writes_header_only(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-empty")

        out = tmp_path / "export.csv"
        export_csv_flat(db, "sess-empty", out)

        with out.open() as fh:
            lines = fh.read().splitlines()
        assert len(lines) == 1
        assert lines[0].split(",") == list(CSV_FLAT_COLUMNS)

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")
        _seed_task(db, "task-1", "sess-1")

        out = tmp_path / "nested" / "deeply" / "export.csv"
        export_csv_flat(db, "sess-1", out)
        assert out.exists()

    def test_numeric_fields_preserved(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")
        _seed_task(
            db,
            "task-1",
            "sess-1",
            priority=5,
            input_tokens=1234,
            output_tokens=567,
            cost_usd=0.0789,
        )

        out = tmp_path / "export.csv"
        export_csv_flat(db, "sess-1", out)

        with out.open() as fh:
            rows = list(csv.DictReader(fh))
        assert rows[0]["priority"] == "5"
        assert rows[0]["input_tokens"] == "1234"
        assert rows[0]["output_tokens"] == "567"
        # float repr is acceptable; just confirm the value parses
        assert float(rows[0]["cost_usd"]) == pytest.approx(0.0789)


class TestExportCsvSplit:
    def test_returns_output_dir(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")
        _seed_task(db, "task-1", "sess-1")

        out_dir = tmp_path / "split"
        result = export_csv_split(db, "sess-1", out_dir)
        assert result == out_dir
        assert out_dir.is_dir()

    def test_creates_one_csv_per_table(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")
        _seed_task(db, "task-1", "sess-1")
        _seed_event(db, "sess-1", task_id="task-1", event_type="started")

        out_dir = tmp_path / "split"
        export_csv_split(db, "sess-1", out_dir)

        assert (out_dir / "sessions.csv").exists()
        assert (out_dir / "tasks.csv").exists()
        assert (out_dir / "events.csv").exists()

    def test_filters_by_session(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-A")
        _seed_session(db, "sess-B")
        _seed_task(db, "task-A1", "sess-A")
        _seed_task(db, "task-B1", "sess-B")
        _seed_event(db, "sess-A", task_id="task-A1", event_type="started")
        _seed_event(db, "sess-B", task_id="task-B1", event_type="started")

        out_dir = tmp_path / "split"
        export_csv_split(db, "sess-A", out_dir)

        with (out_dir / "sessions.csv").open() as fh:
            sess_rows = list(csv.DictReader(fh))
        with (out_dir / "tasks.csv").open() as fh:
            task_rows = list(csv.DictReader(fh))
        with (out_dir / "events.csv").open() as fh:
            event_rows = list(csv.DictReader(fh))

        assert len(sess_rows) == 1
        assert sess_rows[0]["id"] == "sess-A"
        assert [r["id"] for r in task_rows] == ["task-A1"]
        assert [r["session_id"] for r in event_rows] == ["sess-A"]

    def test_session_id_none_dumps_all(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-A")
        _seed_session(db, "sess-B")
        _seed_task(db, "task-A1", "sess-A")
        _seed_task(db, "task-B1", "sess-B")

        out_dir = tmp_path / "split"
        export_csv_split(db, None, out_dir)

        with (out_dir / "sessions.csv").open() as fh:
            sess_rows = list(csv.DictReader(fh))
        with (out_dir / "tasks.csv").open() as fh:
            task_rows = list(csv.DictReader(fh))
        assert {r["id"] for r in sess_rows} == {"sess-A", "sess-B"}
        assert {r["id"] for r in task_rows} == {"task-A1", "task-B1"}

    def test_csv_columns_mirror_table_schema(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")
        _seed_task(db, "task-1", "sess-1")

        out_dir = tmp_path / "split"
        export_csv_split(db, "sess-1", out_dir)

        with (out_dir / "tasks.csv").open() as fh:
            header = next(csv.reader(fh))
        # The split-mode tasks CSV exposes raw columns including
        # parent_task_id and bugfix_retry_count, unlike the flat CSV.
        assert "parent_task_id" in header
        assert "bugfix_retry_count" in header
        assert "session_id" in header

    def test_creates_output_dir_if_missing(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")

        out_dir = tmp_path / "nested" / "deep" / "split"
        export_csv_split(db, "sess-1", out_dir)
        assert out_dir.is_dir()


class TestPatchCreateIfNotExists:
    def test_table(self) -> None:
        line = "CREATE TABLE foo (x INT);"
        assert (
            _patch_create_if_not_exists(line)
            == "CREATE TABLE IF NOT EXISTS foo (x INT);"
        )

    def test_index(self) -> None:
        line = "CREATE INDEX ix_foo ON foo(x);"
        assert (
            _patch_create_if_not_exists(line)
            == "CREATE INDEX IF NOT EXISTS ix_foo ON foo(x);"
        )

    def test_unique_index(self) -> None:
        line = "CREATE UNIQUE INDEX ux_foo ON foo(x);"
        assert (
            _patch_create_if_not_exists(line)
            == "CREATE UNIQUE INDEX IF NOT EXISTS ux_foo ON foo(x);"
        )

    def test_idempotent(self) -> None:
        line = "CREATE TABLE IF NOT EXISTS foo (x INT);"
        assert _patch_create_if_not_exists(line) == line

    def test_passthrough_for_other_lines(self) -> None:
        line = "INSERT INTO foo VALUES (1);"
        assert _patch_create_if_not_exists(line) == line


class TestExportSql:
    def test_returns_output_path(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")
        _seed_task(db, "task-1", "sess-1")

        out = tmp_path / "export.sql"
        result = export_sql(db, "sess-1", out)
        assert result == out
        assert out.exists()

    def test_uses_create_if_not_exists(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")

        out = tmp_path / "export.sql"
        export_sql(db, "sess-1", out)
        contents = out.read_text()
        assert "CREATE TABLE IF NOT EXISTS" in contents
        # Bare CREATE TABLE without IF NOT EXISTS should not appear.
        for line in contents.splitlines():
            if line.startswith("CREATE TABLE "):
                assert line.startswith("CREATE TABLE IF NOT EXISTS")

    def test_session_filter_excludes_other_sessions(
        self, tmp_path: Path
    ) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-A")
        _seed_session(db, "sess-B")
        _seed_task(db, "task-A1", "sess-A")
        _seed_task(db, "task-B1", "sess-B")

        out = tmp_path / "export.sql"
        export_sql(db, "sess-A", out)
        contents = out.read_text()
        assert "task-A1" in contents
        assert "task-B1" not in contents
        assert "sess-A" in contents
        assert "sess-B" not in contents

    def test_full_dump_when_session_id_none(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-A")
        _seed_session(db, "sess-B")
        _seed_task(db, "task-A1", "sess-A")
        _seed_task(db, "task-B1", "sess-B")

        out = tmp_path / "export.sql"
        export_sql(db, None, out)
        contents = out.read_text()
        assert "task-A1" in contents
        assert "task-B1" in contents
        assert "sess-A" in contents
        assert "sess-B" in contents

    def test_dump_is_importable(self, tmp_path: Path) -> None:
        """Round-trip: import the dump into a fresh DB and verify rows."""
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(
            db,
            "sess-1",
            project_path="/work/proj",
            status="completed",
        )
        _seed_task(
            db,
            "task-1",
            "sess-1",
            description="hello",
            depends_on=["dep-A"],
            steps=["s1", "s2"],
        )
        _seed_event(db, "sess-1", task_id="task-1", event_type="started")

        out = tmp_path / "export.sql"
        export_sql(db, "sess-1", out)

        # Apply the dump to a fresh DB.
        new_db = tmp_path / "imported.db"
        new_conn = sqlite3.connect(str(new_db))
        try:
            new_conn.executescript(out.read_text())
            sessions = new_conn.execute("SELECT id, project_path FROM sessions").fetchall()
            tasks = new_conn.execute(
                "SELECT id, description, depends_on, steps FROM tasks"
            ).fetchall()
            events = new_conn.execute(
                "SELECT session_id, event_type FROM events"
            ).fetchall()
        finally:
            new_conn.close()
        assert sessions == [("sess-1", "/work/proj")]
        assert len(tasks) == 1
        assert tasks[0][0] == "task-1"
        assert tasks[0][1] == "hello"
        assert json.loads(tasks[0][2]) == ["dep-A"]
        assert json.loads(tasks[0][3]) == ["s1", "s2"]
        assert events == [("sess-1", "started")]

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")

        out = tmp_path / "nested" / "deep" / "export.sql"
        export_sql(db, "sess-1", out)
        assert out.exists()


class TestExportJson:
    def test_returns_output_path(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")
        _seed_task(db, "task-1", "sess-1")

        out = tmp_path / "export.json"
        result = export_json(db, "sess-1", out)
        assert result == out
        assert out.exists()

    def test_top_level_shape(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")

        out = tmp_path / "export.json"
        export_json(db, "sess-1", out)
        payload = json.loads(out.read_text())
        assert "exported_at" in payload
        assert "claw_forge_version" in payload
        assert payload["scope"] == "session"
        assert isinstance(payload["sessions"], list)

    def test_scope_all_when_session_id_none(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-A")
        _seed_session(db, "sess-B")

        out = tmp_path / "export.json"
        export_json(db, None, out)
        payload = json.loads(out.read_text())
        assert payload["scope"] == "all"
        assert {s["id"] for s in payload["sessions"]} == {"sess-A", "sess-B"}

    def test_tasks_nested_under_sessions(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")
        _seed_task(db, "task-1", "sess-1")
        _seed_task(db, "task-2", "sess-1")

        out = tmp_path / "export.json"
        export_json(db, "sess-1", out)
        payload = json.loads(out.read_text())
        sess = payload["sessions"][0]
        assert sess["id"] == "sess-1"
        task_ids = {t["id"] for t in sess["tasks"]}
        assert task_ids == {"task-1", "task-2"}

    def test_depends_on_and_steps_are_lists(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")
        _seed_task(
            db,
            "task-1",
            "sess-1",
            depends_on=["a", "b"],
            steps=["s1", "s2"],
        )

        out = tmp_path / "export.json"
        export_json(db, "sess-1", out)
        payload = json.loads(out.read_text())
        task = payload["sessions"][0]["tasks"][0]
        assert task["depends_on"] == ["a", "b"]
        assert task["steps"] == ["s1", "s2"]

    def test_session_filter_excludes_other_sessions(
        self, tmp_path: Path
    ) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-A")
        _seed_session(db, "sess-B")
        _seed_task(db, "task-A1", "sess-A")
        _seed_task(db, "task-B1", "sess-B")

        out = tmp_path / "export.json"
        export_json(db, "sess-A", out)
        payload = json.loads(out.read_text())
        assert len(payload["sessions"]) == 1
        assert payload["sessions"][0]["id"] == "sess-A"
        task_ids = [t["id"] for t in payload["sessions"][0]["tasks"]]
        assert task_ids == ["task-A1"]

    def test_session_not_found_yields_empty_sessions(
        self, tmp_path: Path
    ) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-A")

        out = tmp_path / "export.json"
        export_json(db, "missing", out)
        payload = json.loads(out.read_text())
        assert payload["sessions"] == []

    def test_exported_at_is_iso_z(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")

        out = tmp_path / "export.json"
        export_json(db, "sess-1", out)
        payload = json.loads(out.read_text())
        # Spec example uses "Z" suffix, confirming UTC.
        assert payload["exported_at"].endswith("Z")

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        _build_state_db(db)
        _seed_session(db, "sess-1")

        out = tmp_path / "nested" / "deep" / "export.json"
        export_json(db, "sess-1", out)
        assert out.exists()


# ── CLI command tests ──────────────────────────────────────────────────────


def _setup_project_with_db(tmp_path: Path) -> tuple[Path, Path]:
    """Create a fake project layout with a populated state.db.

    Returns ``(project_dir, db_path)``. The DB has one session with two
    tasks and one event; the session's ``project_path`` matches the
    returned project directory so ``_resolve_latest_session`` finds it.
    """
    project_dir = tmp_path / "myproj"
    (project_dir / ".claw-forge").mkdir(parents=True)
    db_path = project_dir / ".claw-forge" / "state.db"
    _build_state_db(db_path)
    _seed_session(db_path, "sess-1234abcd", project_path=str(project_dir))
    _seed_task(db_path, "task-1", "sess-1234abcd")
    _seed_task(db_path, "task-2", "sess-1234abcd")
    _seed_event(db_path, "sess-1234abcd", task_id="task-1", event_type="started")
    return project_dir, db_path


class TestExportCli:
    def test_help_lists_all_flags(self) -> None:
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["export", "--help"])
        assert result.exit_code == 0
        assert "--format" in result.output
        assert "--scope" in result.output
        assert "--session" in result.output
        assert "--csv-mode" in result.output
        assert "--out" in result.output
        assert "--project" in result.output

    def test_default_csv_flat_writes_file(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        project_dir, _db = _setup_project_with_db(tmp_path)
        out = tmp_path / "out.csv"

        result = runner.invoke(
            app,
            [
                "export",
                "--project", str(project_dir),
                "--out", str(out),
            ],
        )
        assert result.exit_code == 0, result.output
        assert out.exists()
        with out.open() as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 2
        assert {r["task_id"] for r in rows} == {"task-1", "task-2"}

    def test_format_sql_produces_dump(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        project_dir, _db = _setup_project_with_db(tmp_path)
        out = tmp_path / "out.sql"

        result = runner.invoke(
            app,
            [
                "export",
                "--format", "sql",
                "--project", str(project_dir),
                "--out", str(out),
            ],
        )
        assert result.exit_code == 0, result.output
        contents = out.read_text()
        assert "CREATE TABLE IF NOT EXISTS" in contents
        assert "task-1" in contents

    def test_format_json_produces_json(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        project_dir, _db = _setup_project_with_db(tmp_path)
        out = tmp_path / "out.json"

        result = runner.invoke(
            app,
            [
                "export",
                "--format", "json",
                "--project", str(project_dir),
                "--out", str(out),
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(out.read_text())
        assert payload["scope"] == "session"
        assert len(payload["sessions"]) == 1

    def test_scope_all_exports_all_sessions(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        project_dir, db_path = _setup_project_with_db(tmp_path)
        # Add a second session for a *different* project — scope=all
        # should still pick it up.
        _seed_session(db_path, "sess-other", project_path="/other/proj")
        _seed_task(db_path, "task-other", "sess-other")

        out = tmp_path / "out.json"
        result = runner.invoke(
            app,
            [
                "export",
                "--format", "json",
                "--scope", "all",
                "--project", str(project_dir),
                "--out", str(out),
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(out.read_text())
        assert payload["scope"] == "all"
        assert {s["id"] for s in payload["sessions"]} == {
            "sess-1234abcd",
            "sess-other",
        }

    def test_csv_mode_split_creates_directory(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        project_dir, _db = _setup_project_with_db(tmp_path)
        out_dir = tmp_path / "split"

        result = runner.invoke(
            app,
            [
                "export",
                "--csv-mode", "split",
                "--project", str(project_dir),
                "--out", str(out_dir),
            ],
        )
        assert result.exit_code == 0, result.output
        assert (out_dir / "sessions.csv").exists()
        assert (out_dir / "tasks.csv").exists()
        assert (out_dir / "events.csv").exists()

    def test_auto_generated_filename_session_scope(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        project_dir, _db = _setup_project_with_db(tmp_path)
        # Run from a temporary cwd so auto-generated filenames land here.
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)

        result = runner.invoke(
            app,
            [
                "export",
                "--project", str(project_dir),
            ],
        )
        assert result.exit_code == 0, result.output
        # Filename pattern: claw-forge-export-<id8>-<YYYYMMDD-HHMMSS>.csv
        produced = list(cwd.glob("claw-forge-export-sess-123-*.csv"))
        assert len(produced) == 1, f"got: {list(cwd.iterdir())}"

    def test_auto_generated_filename_all_scope(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        project_dir, _db = _setup_project_with_db(tmp_path)
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)

        result = runner.invoke(
            app,
            [
                "export",
                "--scope", "all",
                "--format", "json",
                "--project", str(project_dir),
            ],
        )
        assert result.exit_code == 0, result.output
        produced = list(cwd.glob("claw-forge-export-all-*.json"))
        assert len(produced) == 1

    def test_auto_generated_split_directory_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        project_dir, _db = _setup_project_with_db(tmp_path)
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)

        result = runner.invoke(
            app,
            ["export", "--csv-mode", "split", "--project", str(project_dir)],
        )
        assert result.exit_code == 0, result.output
        # Directory has no extension.
        produced = [p for p in cwd.iterdir() if p.is_dir()]
        assert len(produced) == 1
        assert produced[0].name.startswith("claw-forge-export-sess-123-")

    def test_db_not_found_errors(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        empty_project = tmp_path / "empty"
        empty_project.mkdir()

        result = runner.invoke(
            app,
            ["export", "--project", str(empty_project)],
        )
        assert result.exit_code == 1
        assert "State database not found" in result.output

    def test_session_not_found_lists_available(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        project_dir, _db = _setup_project_with_db(tmp_path)

        result = runner.invoke(
            app,
            [
                "export",
                "--session", "no-such-session",
                "--project", str(project_dir),
            ],
        )
        assert result.exit_code == 1
        assert "not found" in result.output
        # The available-sessions hint should include the real session id.
        assert "sess-1234abcd" in result.output

    def test_no_sessions_for_project_errors(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        # Set up a project_dir with a DB whose only session belongs to a
        # *different* project. _resolve_latest_session should return ''.
        project_dir = tmp_path / "myproj"
        (project_dir / ".claw-forge").mkdir(parents=True)
        db_path = project_dir / ".claw-forge" / "state.db"
        _build_state_db(db_path)
        _seed_session(db_path, "sess-other", project_path="/elsewhere")
        _seed_task(db_path, "task-other", "sess-other")

        result = runner.invoke(
            app,
            ["export", "--project", str(project_dir)],
        )
        assert result.exit_code == 1
        assert "No session found" in result.output

    def test_invalid_format_rejected(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        project_dir, _db = _setup_project_with_db(tmp_path)

        result = runner.invoke(
            app,
            [
                "export",
                "--format", "xml",
                "--project", str(project_dir),
            ],
        )
        assert result.exit_code == 1
        assert "Unknown --format" in result.output

    def test_invalid_scope_rejected(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        project_dir, _db = _setup_project_with_db(tmp_path)

        result = runner.invoke(
            app,
            [
                "export",
                "--scope", "everything",
                "--project", str(project_dir),
            ],
        )
        assert result.exit_code == 1
        assert "Unknown --scope" in result.output

    def test_invalid_csv_mode_rejected(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        project_dir, _db = _setup_project_with_db(tmp_path)

        result = runner.invoke(
            app,
            [
                "export",
                "--csv-mode", "merged",
                "--project", str(project_dir),
            ],
        )
        assert result.exit_code == 1
        assert "Unknown --csv-mode" in result.output

    def test_summary_prints_counts_and_path(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        project_dir, _db = _setup_project_with_db(tmp_path)
        out = tmp_path / "out.csv"

        result = runner.invoke(
            app,
            [
                "export",
                "--project", str(project_dir),
                "--out", str(out),
            ],
        )
        assert result.exit_code == 0, result.output
        # 2 tasks were seeded for the session.
        assert "Exported 2 task" in result.output
        assert "CSV (flat)" in result.output
        assert "out.csv" in result.output

