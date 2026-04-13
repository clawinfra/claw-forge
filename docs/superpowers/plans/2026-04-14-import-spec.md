# import-spec Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `claw-forge import <path>` CLI command and `/import-spec` slash command that converts BMAD, Linear, Jira, and generic markdown exports into `app_spec.txt` or `additions_spec.xml` via a hybrid rule+Claude pipeline.

**Architecture:** A new `claw_forge/importer/` package runs three stages — format detection (rules), structure extraction (rules, per-format), and spec writing (Claude). Each stage is independently testable. The CLI calls the full pipeline; the slash command drives the same pipeline interactively.

**Tech Stack:** Python stdlib (`xml.etree`, `csv`, `json`, `pathlib`), `anthropic` SDK (already a dependency), `typer` + `rich` for CLI output.

---

## File Map

**Create:**
- `claw_forge/importer/__init__.py` — public API: `detect()`, `extract()`, `convert()`, `import_spec()`
- `claw_forge/importer/detector.py` — `FormatResult` dataclass + detection logic
- `claw_forge/importer/extractors/__init__.py` — re-exports `extract()`
- `claw_forge/importer/extractors/base.py` — `Story`, `Epic`, `ExtractedSpec` dataclasses
- `claw_forge/importer/extractors/bmad.py` — BMAD folder extractor
- `claw_forge/importer/extractors/linear.py` — Linear JSON extractor
- `claw_forge/importer/extractors/jira.py` — Jira XML/CSV extractor
- `claw_forge/importer/extractors/generic.py` — generic markdown extractor
- `claw_forge/importer/converter.py` — `ConvertedSections` dataclass + Claude conversion
- `claw_forge/importer/writer.py` — assembles and writes final spec file
- `tests/importer/__init__.py`
- `tests/importer/fixtures/bmad/prd.md`
- `tests/importer/fixtures/bmad/architecture.md`
- `tests/importer/fixtures/bmad/stories/epic-1-auth/story-1.md`
- `tests/importer/fixtures/bmad/stories/epic-1-auth/story-2.md`
- `tests/importer/fixtures/bmad/stories/epic-2-tasks/story-1.md`
- `tests/importer/fixtures/linear/issues.json`
- `tests/importer/fixtures/jira/export.xml`
- `tests/importer/fixtures/jira/export.csv`
- `tests/importer/fixtures/generic/prd.md`
- `tests/importer/test_detector.py`
- `tests/importer/test_extractor_bmad.py`
- `tests/importer/test_extractor_linear.py`
- `tests/importer/test_extractor_jira.py`
- `tests/importer/test_extractor_generic.py`
- `tests/importer/test_converter.py`
- `tests/importer/test_writer.py`
- `tests/importer/test_integration.py`
- `.claude/commands/import-spec.md`
- `claw_forge/commands_scaffold/import-spec.md`

**Modify:**
- `claw_forge/cli.py` — add `import_spec()` command after `plan()` (around line 2178)

---

## Task 1: Test Fixtures

**Files:**
- Create: `tests/importer/__init__.py`
- Create: `tests/importer/fixtures/bmad/prd.md`
- Create: `tests/importer/fixtures/bmad/architecture.md`
- Create: `tests/importer/fixtures/bmad/stories/epic-1-auth/story-1.md`
- Create: `tests/importer/fixtures/bmad/stories/epic-1-auth/story-2.md`
- Create: `tests/importer/fixtures/bmad/stories/epic-2-tasks/story-1.md`
- Create: `tests/importer/fixtures/linear/issues.json`
- Create: `tests/importer/fixtures/jira/export.xml`
- Create: `tests/importer/fixtures/jira/export.csv`
- Create: `tests/importer/fixtures/generic/prd.md`

- [ ] **Step 1: Create the test package init and fixture directories**

```bash
mkdir -p tests/importer/fixtures/bmad/stories/epic-1-auth
mkdir -p tests/importer/fixtures/bmad/stories/epic-2-tasks
mkdir -p tests/importer/fixtures/linear
mkdir -p tests/importer/fixtures/jira
mkdir -p tests/importer/fixtures/generic
touch tests/importer/__init__.py
```

- [ ] **Step 2: Write `tests/importer/fixtures/bmad/prd.md`**

```markdown
# TaskTracker PRD

## Overview
TaskTracker is a task management app for small teams that need to track work across sprints.

## Target Audience
Software teams of 3–15 people managing feature development.

## Epics

### Epic 1: Authentication
User identity and access management.

### Epic 2: Task Management
Core task creation, assignment, and tracking.
```

- [ ] **Step 3: Write `tests/importer/fixtures/bmad/architecture.md`**

```markdown
# Architecture

## Tech Stack
- Backend: Python 3.12 with FastAPI
- Frontend: React 18 + TypeScript + Vite
- Database: PostgreSQL 15
- Auth: JWT with refresh tokens

## Database Schema
users table: id UUID PK, email VARCHAR(255) UNIQUE NOT NULL, password_hash VARCHAR NOT NULL, created_at TIMESTAMP
tasks table: id UUID PK, owner_id UUID FK users.id, title VARCHAR(200) NOT NULL, status VARCHAR(20) DEFAULT 'todo', created_at TIMESTAMP

## API Endpoints
POST /api/auth/register - Register new user
POST /api/auth/login    - Login and receive tokens
GET  /api/tasks         - List user's tasks
POST /api/tasks         - Create a task
```

- [ ] **Step 4: Write story files**

`tests/importer/fixtures/bmad/stories/epic-1-auth/story-1.md`:
```markdown
---
title: User Registration
---
Given a visitor on the registration page,
When they submit email and password,
Then the system creates an account and returns 201 with user_id.
When they submit a duplicate email,
Then the system returns 409 with "Email already registered".
```

`tests/importer/fixtures/bmad/stories/epic-1-auth/story-2.md`:
```markdown
---
title: User Login
---
Given a registered user,
When they submit valid credentials,
Then the system returns JWT access_token (15min) and refresh_token (7 days).
When they submit invalid credentials,
Then the system returns 401 with "Invalid credentials".
```

`tests/importer/fixtures/bmad/stories/epic-2-tasks/story-1.md`:
```markdown
---
title: Create Task
---
Given an authenticated user,
When they POST to /api/tasks with a title,
Then the system creates a task and returns 201 with task_id.
When the title is missing,
Then the system returns 422 with field-level validation error.
```

- [ ] **Step 5: Write `tests/importer/fixtures/linear/issues.json`**

```json
{
  "project": {
    "name": "TaskTracker",
    "description": "A task management app for small teams."
  },
  "issues": [
    {
      "identifier": "TT-1",
      "title": "User Registration",
      "description": "Given a visitor, when they submit email and password, then system creates account and returns 201.",
      "state": "Todo",
      "labels": ["Authentication"]
    },
    {
      "identifier": "TT-2",
      "title": "User Login",
      "description": "Given a registered user, when they submit valid credentials, then system returns JWT tokens.",
      "state": "Todo",
      "labels": ["Authentication"]
    },
    {
      "identifier": "TT-3",
      "title": "Create Task",
      "description": "Given an authenticated user, when they POST a task title, then system creates task and returns 201.",
      "state": "Todo",
      "labels": ["Task Management"]
    },
    {
      "identifier": "TT-4",
      "title": "Unlabelled story",
      "description": "Some story with no label assigned.",
      "state": "Todo",
      "labels": []
    }
  ]
}
```

- [ ] **Step 6: Write `tests/importer/fixtures/jira/export.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="0.92">
  <channel>
    <title>TaskTracker</title>
    <item>
      <summary>User Registration</summary>
      <description>User submits email and password to register.</description>
      <customfields>
        <customfield id="customfield_10014" key="com.pyxis.greenhopper.jira:gh-epic-link">
          <customfieldname>Epic Link</customfieldname>
          <customfieldvalues>
            <customfieldvalue>Authentication</customfieldvalue>
          </customfieldvalues>
        </customfield>
      </customfields>
    </item>
    <item>
      <summary>Create Task</summary>
      <description>Authenticated user creates a new task with a title.</description>
      <customfields>
        <customfield id="customfield_10014" key="com.pyxis.greenhopper.jira:gh-epic-link">
          <customfieldname>Epic Link</customfieldname>
          <customfieldvalues>
            <customfieldvalue>Task Management</customfieldvalue>
          </customfieldvalues>
        </customfield>
      </customfields>
    </item>
  </channel>
</rss>
```

- [ ] **Step 7: Write `tests/importer/fixtures/jira/export.csv`**

```
Issue key,Summary,Description,Epic Link
TT-1,User Registration,User submits email and password to register.,Authentication
TT-2,User Login,User submits credentials to receive JWT tokens.,Authentication
TT-3,Create Task,Authenticated user creates a task with a title.,Task Management
```

- [ ] **Step 8: Write `tests/importer/fixtures/generic/prd.md`**

```markdown
# TaskTracker

A task management app for small teams.

## Tech Stack
Python FastAPI backend, React TypeScript frontend, PostgreSQL database.

## Authentication

### User Registration
Users provide email and password to create an account.
- System validates email format
- System rejects duplicate emails with error
- System hashes password before storing

### User Login
Users submit credentials to receive access tokens.
- System returns JWT on valid credentials
- System returns 401 on invalid credentials

## Task Management

### Create Task
Authenticated users create tasks with a title.
- System validates title is not empty
- System returns created task with id
```

- [ ] **Step 9: Commit fixtures**

```bash
git add tests/importer/
git commit -m "test(importer): add fixture files for all 4 formats"
```

---

## Task 2: Dataclasses — `extractors/base.py` and `FormatResult`

**Files:**
- Create: `claw_forge/importer/__init__.py`
- Create: `claw_forge/importer/extractors/__init__.py`
- Create: `claw_forge/importer/extractors/base.py`
- Create: `claw_forge/importer/detector.py` (dataclass only, no logic yet)
- Test: `tests/importer/test_detector.py` (partial — dataclass tests only)

- [ ] **Step 1: Write failing test for `ExtractedSpec` construction**

```python
# tests/importer/test_detector.py
from __future__ import annotations
from pathlib import Path
from claw_forge.importer.detector import FormatResult
from claw_forge.importer.extractors.base import Epic, ExtractedSpec, Story


def test_format_result_fields():
    fr = FormatResult(
        format="bmad",
        confidence="high",
        artifacts=[Path("prd.md")],
        summary="BMAD output with 2 epics",
    )
    assert fr.format == "bmad"
    assert fr.confidence == "high"
    assert len(fr.artifacts) == 1
    assert "2 epics" in fr.summary


def test_extracted_spec_counts():
    epics = [
        Epic(name="Auth", stories=[
            Story(title="Register", acceptance_criteria="user registers", phase_hint="Auth"),
            Story(title="Login", acceptance_criteria="user logs in", phase_hint="Auth"),
        ]),
        Epic(name="Tasks", stories=[
            Story(title="Create", acceptance_criteria="user creates task", phase_hint="Tasks"),
        ]),
    ]
    spec = ExtractedSpec(
        project_name="TestApp",
        overview="A test app.",
        epics=epics,
        tech_stack_raw="FastAPI + React",
        database_tables_raw="users, tasks",
        api_endpoints_raw="POST /auth/register",
        existing_context={},
        integration_points=[],
        constraints=[],
        source_format="bmad",
        source_path=Path("."),
        epic_count=2,
        story_count=3,
    )
    assert spec.epic_count == 2
    assert spec.story_count == 3
    assert len(spec.epics[0].stories) == 2
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
uv run pytest tests/importer/test_detector.py -v
```
Expected: `ModuleNotFoundError: No module named 'claw_forge.importer'`

- [ ] **Step 3: Create package skeleton and dataclasses**

`claw_forge/importer/__init__.py`:
```python
"""claw-forge import pipeline — converts 3rd-party harness output to app_spec."""
from __future__ import annotations
```

`claw_forge/importer/extractors/__init__.py`:
```python
"""Format-specific extractors — each returns an ExtractedSpec."""
from __future__ import annotations
```

`claw_forge/importer/extractors/base.py`:
```python
"""Shared dataclasses for the extraction → conversion pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Story:
    title: str
    acceptance_criteria: str  # raw text, may be Gherkin — converter rewrites
    phase_hint: str           # epic name or phase label from source tool


@dataclass
class Epic:
    name: str
    stories: list[Story] = field(default_factory=list)


@dataclass
class ExtractedSpec:
    # identity
    project_name: str
    overview: str

    # features
    epics: list[Epic]

    # tech context (empty string if format does not carry it)
    tech_stack_raw: str
    database_tables_raw: str
    api_endpoints_raw: str

    # brownfield context
    existing_context: dict[str, str]  # stack, test_baseline, conventions
    integration_points: list[str]
    constraints: list[str]

    # metadata
    source_format: str
    source_path: Path
    epic_count: int
    story_count: int
```

`claw_forge/importer/detector.py` (dataclass only for now):
```python
"""Format detector — inspects a path and returns a FormatResult."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class FormatResult:
    format: Literal["bmad", "linear", "jira", "generic"]
    confidence: Literal["high", "medium", "low"]
    artifacts: list[Path] = field(default_factory=list)
    summary: str = ""
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/importer/test_detector.py -v
```
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add claw_forge/importer/ tests/importer/test_detector.py
git commit -m "feat(importer): add ExtractedSpec, Epic, Story, FormatResult dataclasses"
```

---

## Task 3: Format Detector

**Files:**
- Modify: `claw_forge/importer/detector.py` — add `detect()` function
- Test: `tests/importer/test_detector.py` — add detection tests

- [ ] **Step 1: Write failing detection tests**

Add to `tests/importer/test_detector.py`:

```python
from claw_forge.importer.detector import detect

FIXTURES = Path(__file__).parent / "fixtures"


def test_detect_bmad(tmp_path):
    # BMAD: prd.md present
    (tmp_path / "prd.md").write_text("# PRD")
    (tmp_path / "architecture.md").write_text("# Arch")
    result = detect(tmp_path)
    assert result.format == "bmad"
    assert result.confidence == "high"
    assert any(p.name == "prd.md" for p in result.artifacts)


def test_detect_bmad_stories_dir(tmp_path):
    stories = tmp_path / "stories" / "epic-1-auth"
    stories.mkdir(parents=True)
    (stories / "story-1.md").write_text("story")
    result = detect(tmp_path)
    assert result.format == "bmad"
    assert result.confidence == "high"


def test_detect_linear(tmp_path):
    (tmp_path / "issues.json").write_text(
        '{"issues": [{"identifier": "TT-1", "state": "Todo", "labels": []}], '
        '"project": {"name": "X", "description": "Y"}}'
    )
    result = detect(tmp_path)
    assert result.format == "linear"
    assert result.confidence == "high"


def test_detect_jira_xml(tmp_path):
    (tmp_path / "export.xml").write_text(
        '<?xml version="1.0"?><rss version="0.92"><channel></channel></rss>'
    )
    result = detect(tmp_path)
    assert result.format == "jira"
    assert result.confidence == "high"


def test_detect_jira_csv(tmp_path):
    (tmp_path / "export.csv").write_text("Issue key,Summary,Description,Epic Link\nTT-1,foo,bar,Auth\n")
    result = detect(tmp_path)
    assert result.format == "jira"
    assert result.confidence == "high"


def test_detect_generic_markdown(tmp_path):
    (tmp_path / "spec.md").write_text("# MyApp\n\n## Feature\nSome feature.")
    result = detect(tmp_path)
    assert result.format == "generic"
    assert result.confidence == "low"


def test_detect_fixture_bmad():
    result = detect(FIXTURES / "bmad")
    assert result.format == "bmad"
    assert result.confidence == "high"


def test_detect_fixture_linear():
    result = detect(FIXTURES / "linear")
    assert result.format == "linear"


def test_detect_fixture_jira_xml():
    result = detect(FIXTURES / "jira")
    assert result.format == "jira"


def test_detect_fixture_generic():
    result = detect(FIXTURES / "generic")
    assert result.format == "generic"


def test_detect_summary_contains_format():
    result = detect(FIXTURES / "bmad")
    assert result.summary  # non-empty


def test_detect_nonexistent_path_raises():
    import pytest
    with pytest.raises(FileNotFoundError):
        detect(Path("/nonexistent/path"))
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run pytest tests/importer/test_detector.py -v
```
Expected: multiple `ImportError` or `AttributeError` failures

- [ ] **Step 3: Implement `detect()` in `detector.py`**

```python
"""Format detector — inspects a path and returns a FormatResult."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class FormatResult:
    format: Literal["bmad", "linear", "jira", "generic"]
    confidence: Literal["high", "medium", "low"]
    artifacts: list[Path] = field(default_factory=list)
    summary: str = ""


def detect(path: Path) -> FormatResult:
    """Inspect *path* (file or directory) and return a FormatResult.

    Raises FileNotFoundError if path does not exist.
    Falls back to 'generic' with confidence 'low' when no format matched.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No files found at {path}")

    # Collect all files to inspect
    if path.is_file():
        files = [path]
        search_root = path.parent
    else:
        files = list(path.rglob("*"))
        search_root = path

    # ── BMAD detection ───────────────────────────────────────────────────────
    prd_md = search_root / "prd.md"
    arch_md = search_root / "architecture.md"
    stories_dir = search_root / "stories"
    bmad_output_dir = search_root / "_bmad-output"

    has_prd = prd_md.exists()
    has_arch = arch_md.exists()
    has_stories = stories_dir.is_dir() and any(
        d.is_dir() and d.name.startswith("epic-")
        for d in stories_dir.iterdir()
    ) if stories_dir.exists() else False
    has_bmad_dir = bmad_output_dir.is_dir()

    if has_prd or has_stories or has_bmad_dir:
        artifacts: list[Path] = []
        root = bmad_output_dir if has_bmad_dir else search_root
        if (root / "prd.md").exists():
            artifacts.append(root / "prd.md")
        if (root / "architecture.md").exists():
            artifacts.append(root / "architecture.md")
        if (root / "stories").is_dir():
            artifacts += sorted((root / "stories").rglob("*.md"))
        epic_count = sum(
            1 for d in (root / "stories").iterdir() if d.is_dir()
        ) if (root / "stories").is_dir() else 0
        story_count = len([p for p in artifacts if "stories" in str(p)])
        summary = f"BMAD output — {epic_count} epic(s), {story_count} story file(s)"
        return FormatResult(
            format="bmad",
            confidence="high",
            artifacts=artifacts,
            summary=summary,
        )

    # ── Linear detection ─────────────────────────────────────────────────────
    for f in files:
        if f.suffix == ".json":
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(data.get("issues"), list) and data["issues"]:
                first = data["issues"][0]
                if "identifier" in first and "state" in first:
                    count = len(data["issues"])
                    return FormatResult(
                        format="linear",
                        confidence="high",
                        artifacts=[f],
                        summary=f"Linear export — {count} issue(s)",
                    )

    # ── Jira detection ───────────────────────────────────────────────────────
    for f in files:
        if f.suffix == ".xml":
            try:
                root_el = ET.fromstring(f.read_text(encoding="utf-8"))
            except ET.ParseError:
                continue
            if root_el.tag in ("rss", "jira"):
                items = root_el.findall(".//item")
                return FormatResult(
                    format="jira",
                    confidence="high",
                    artifacts=[f],
                    summary=f"Jira XML export — {len(items)} item(s)",
                )
        if f.suffix == ".csv":
            try:
                header = f.read_text(encoding="utf-8").splitlines()[0]
            except (OSError, IndexError):
                continue
            if "Issue key" in header and "Epic Link" in header:
                import csv as _csv
                with f.open(encoding="utf-8") as fh:
                    rows = list(_csv.DictReader(fh))
                return FormatResult(
                    format="jira",
                    confidence="high",
                    artifacts=[f],
                    summary=f"Jira CSV export — {len(rows)} row(s)",
                )

    # ── Generic markdown fallback ────────────────────────────────────────────
    md_files = [f for f in files if f.suffix == ".md"]
    return FormatResult(
        format="generic",
        confidence="low",
        artifacts=md_files,
        summary=f"Generic markdown — {len(md_files)} file(s) (format unrecognised)",
    )
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/importer/test_detector.py -v
```
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add claw_forge/importer/detector.py tests/importer/test_detector.py
git commit -m "feat(importer): implement format detector for bmad/linear/jira/generic"
```

---

## Task 4: BMAD Extractor

**Files:**
- Create: `claw_forge/importer/extractors/bmad.py`
- Test: `tests/importer/test_extractor_bmad.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/importer/test_extractor_bmad.py
from __future__ import annotations

from pathlib import Path

import pytest

from claw_forge.importer.detector import detect
from claw_forge.importer.extractors.bmad import extract_bmad

FIXTURE = Path(__file__).parent / "fixtures" / "bmad"


def test_extract_bmad_project_name():
    result = detect(FIXTURE)
    spec = extract_bmad(result)
    assert spec.project_name == "TaskTracker"


def test_extract_bmad_overview():
    result = detect(FIXTURE)
    spec = extract_bmad(result)
    assert "task management" in spec.overview.lower()


def test_extract_bmad_epics():
    result = detect(FIXTURE)
    spec = extract_bmad(result)
    assert spec.epic_count == 2
    epic_names = [e.name for e in spec.epics]
    assert "Authentication" in epic_names
    assert "Task Management" in epic_names


def test_extract_bmad_stories():
    result = detect(FIXTURE)
    spec = extract_bmad(result)
    assert spec.story_count == 3
    auth_epic = next(e for e in spec.epics if e.name == "Authentication")
    assert len(auth_epic.stories) == 2


def test_extract_bmad_story_titles():
    result = detect(FIXTURE)
    spec = extract_bmad(result)
    auth_epic = next(e for e in spec.epics if e.name == "Authentication")
    titles = [s.title for s in auth_epic.stories]
    assert "User Registration" in titles
    assert "User Login" in titles


def test_extract_bmad_acceptance_criteria_not_empty():
    result = detect(FIXTURE)
    spec = extract_bmad(result)
    for epic in spec.epics:
        for story in epic.stories:
            assert story.acceptance_criteria.strip()


def test_extract_bmad_tech_stack():
    result = detect(FIXTURE)
    spec = extract_bmad(result)
    assert "FastAPI" in spec.tech_stack_raw


def test_extract_bmad_database_raw():
    result = detect(FIXTURE)
    spec = extract_bmad(result)
    assert "users" in spec.database_tables_raw.lower()


def test_extract_bmad_api_endpoints():
    result = detect(FIXTURE)
    spec = extract_bmad(result)
    assert "/api/auth" in spec.api_endpoints_raw


def test_extract_bmad_source_format():
    result = detect(FIXTURE)
    spec = extract_bmad(result)
    assert spec.source_format == "bmad"
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run pytest tests/importer/test_extractor_bmad.py -v
```
Expected: `ImportError: cannot import name 'extract_bmad'`

- [ ] **Step 3: Implement `claw_forge/importer/extractors/bmad.py`**

```python
"""BMAD extractor — reads prd.md, architecture.md, stories/**/*.md."""
from __future__ import annotations

import re
from pathlib import Path

from claw_forge.importer.detector import FormatResult
from claw_forge.importer.extractors.base import Epic, ExtractedSpec, Story


def extract_bmad(result: FormatResult) -> ExtractedSpec:
    """Extract structure from BMAD artifacts into an ExtractedSpec."""
    prd_path = next((p for p in result.artifacts if p.name == "prd.md"), None)
    arch_path = next((p for p in result.artifacts if p.name == "architecture.md"), None)
    story_paths = sorted(p for p in result.artifacts if "stories" in str(p) and p.suffix == ".md")

    project_name, overview = _parse_prd(prd_path)
    tech_stack_raw, database_tables_raw, api_endpoints_raw = _parse_architecture(arch_path)
    epics = _parse_stories(story_paths)

    story_count = sum(len(e.stories) for e in epics)
    source_path = prd_path.parent if prd_path else result.artifacts[0].parent

    return ExtractedSpec(
        project_name=project_name,
        overview=overview,
        epics=epics,
        tech_stack_raw=tech_stack_raw,
        database_tables_raw=database_tables_raw,
        api_endpoints_raw=api_endpoints_raw,
        existing_context={},
        integration_points=[],
        constraints=[],
        source_format="bmad",
        source_path=source_path,
        epic_count=len(epics),
        story_count=story_count,
    )


def _parse_prd(prd_path: Path | None) -> tuple[str, str]:
    """Return (project_name, overview) from prd.md."""
    if prd_path is None or not prd_path.exists():
        return "Unnamed Project", ""

    text = prd_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Project name: first H1
    project_name = "Unnamed Project"
    for line in lines:
        if line.startswith("# "):
            project_name = line.lstrip("# ").strip()
            break

    # Overview: first paragraph under ## Overview (or first non-heading paragraph)
    overview = ""
    in_overview = False
    for line in lines:
        if re.match(r"^## Overview", line, re.IGNORECASE):
            in_overview = True
            continue
        if in_overview:
            if line.startswith("#"):
                break
            if line.strip():
                overview += line.strip() + " "

    if not overview:
        # Fallback: first non-empty non-heading paragraph
        for line in lines:
            if line.strip() and not line.startswith("#"):
                overview = line.strip()
                break

    return project_name, overview.strip()


def _parse_architecture(arch_path: Path | None) -> tuple[str, str, str]:
    """Return (tech_stack_raw, database_tables_raw, api_endpoints_raw)."""
    if arch_path is None or not arch_path.exists():
        return "", "", ""

    text = arch_path.read_text(encoding="utf-8")

    tech_stack_raw = _extract_section(text, ["Tech Stack", "Technology Stack", "Stack"])
    database_tables_raw = _extract_section(text, ["Database Schema", "Database", "Schema"])
    api_endpoints_raw = _extract_section(text, ["API Endpoints", "API", "Endpoints"])

    return tech_stack_raw, database_tables_raw, api_endpoints_raw


def _extract_section(text: str, headings: list[str]) -> str:
    """Extract text under the first matching H2/H3 heading."""
    lines = text.splitlines()
    in_section = False
    collected: list[str] = []

    for line in lines:
        stripped = line.lstrip("#").strip()
        if line.startswith("#") and any(h.lower() in stripped.lower() for h in headings):
            in_section = True
            continue
        if in_section:
            if line.startswith("## "):  # new H2 section ends this one
                break
            collected.append(line)

    return "\n".join(collected).strip()


def _parse_stories(story_paths: list[Path]) -> list[Epic]:
    """Group story files into Epics by their parent directory name."""
    epic_map: dict[str, list[Story]] = {}

    for path in story_paths:
        epic_dir = path.parent.name  # e.g. "epic-1-auth"
        # Convert dir name to human-readable: "epic-1-auth" → "Auth"
        epic_name = _dir_to_epic_name(epic_dir)

        title, criteria = _parse_story_file(path)
        story = Story(title=title, acceptance_criteria=criteria, phase_hint=epic_name)

        epic_map.setdefault(epic_name, []).append(story)

    return [Epic(name=name, stories=stories) for name, stories in epic_map.items()]


def _dir_to_epic_name(dir_name: str) -> str:
    """'epic-1-auth' → 'Auth', 'epic-2-task-management' → 'Task Management'."""
    parts = dir_name.split("-")
    # Drop "epic" and numeric prefix
    name_parts = [p for p in parts if p.lower() != "epic" and not p.isdigit()]
    return " ".join(p.capitalize() for p in name_parts)


def _parse_story_file(path: Path) -> tuple[str, str]:
    """Return (title, acceptance_criteria) from a story markdown file.

    Title comes from YAML frontmatter 'title:' field or first H1/H2.
    Acceptance criteria is the body after the frontmatter.
    """
    text = path.read_text(encoding="utf-8")

    title = path.stem.replace("-", " ").replace("_", " ").title()
    body = text

    # Parse YAML frontmatter (--- ... ---)
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            frontmatter = text[3:end]
            body = text[end + 3:].strip()
            for line in frontmatter.splitlines():
                if line.lower().startswith("title:"):
                    title = line.split(":", 1)[1].strip().strip('"\'')
                    break

    # Fallback: first heading in body
    if not title or title == path.stem:
        for line in body.splitlines():
            if line.startswith("#"):
                title = line.lstrip("#").strip()
                break

    return title, body.strip()
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/importer/test_extractor_bmad.py -v
```
Expected: all 10 tests pass

- [ ] **Step 5: Commit**

```bash
git add claw_forge/importer/extractors/bmad.py tests/importer/test_extractor_bmad.py
git commit -m "feat(importer): implement BMAD extractor"
```

---

## Task 5: Linear Extractor

**Files:**
- Create: `claw_forge/importer/extractors/linear.py`
- Test: `tests/importer/test_extractor_linear.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/importer/test_extractor_linear.py
from __future__ import annotations

from pathlib import Path

from claw_forge.importer.detector import detect
from claw_forge.importer.extractors.linear import extract_linear

FIXTURE = Path(__file__).parent / "fixtures" / "linear"


def test_extract_linear_project_name():
    result = detect(FIXTURE)
    spec = extract_linear(result)
    assert spec.project_name == "TaskTracker"


def test_extract_linear_overview():
    result = detect(FIXTURE)
    spec = extract_linear(result)
    assert "task management" in spec.overview.lower()


def test_extract_linear_epic_count():
    result = detect(FIXTURE)
    spec = extract_linear(result)
    # 2 labelled epics + 1 General fallback epic
    assert spec.epic_count == 3


def test_extract_linear_story_count():
    result = detect(FIXTURE)
    spec = extract_linear(result)
    assert spec.story_count == 4


def test_extract_linear_labelled_epics():
    result = detect(FIXTURE)
    spec = extract_linear(result)
    epic_names = [e.name for e in spec.epics]
    assert "Authentication" in epic_names
    assert "Task Management" in epic_names


def test_extract_linear_general_fallback_epic():
    result = detect(FIXTURE)
    spec = extract_linear(result)
    epic_names = [e.name for e in spec.epics]
    assert "General" in epic_names


def test_extract_linear_story_titles():
    result = detect(FIXTURE)
    spec = extract_linear(result)
    auth = next(e for e in spec.epics if e.name == "Authentication")
    titles = [s.title for s in auth.stories]
    assert "User Registration" in titles
    assert "User Login" in titles


def test_extract_linear_acceptance_criteria():
    result = detect(FIXTURE)
    spec = extract_linear(result)
    auth = next(e for e in spec.epics if e.name == "Authentication")
    reg = next(s for s in auth.stories if s.title == "User Registration")
    assert "201" in reg.acceptance_criteria


def test_extract_linear_source_format():
    result = detect(FIXTURE)
    spec = extract_linear(result)
    assert spec.source_format == "linear"
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run pytest tests/importer/test_extractor_linear.py -v
```
Expected: `ImportError: cannot import name 'extract_linear'`

- [ ] **Step 3: Implement `claw_forge/importer/extractors/linear.py`**

```python
"""Linear extractor — reads a Linear JSON issues export."""
from __future__ import annotations

import json
from pathlib import Path

from claw_forge.importer.detector import FormatResult
from claw_forge.importer.extractors.base import Epic, ExtractedSpec, Story

_GENERAL_EPIC = "General"


def extract_linear(result: FormatResult) -> ExtractedSpec:
    """Extract structure from a Linear JSON export."""
    json_path = result.artifacts[0]
    data = json.loads(json_path.read_text(encoding="utf-8"))

    project_name = data.get("project", {}).get("name", "Unnamed Project")
    overview = data.get("project", {}).get("description", "")

    epics = _group_issues(data.get("issues", []))
    story_count = sum(len(e.stories) for e in epics)

    return ExtractedSpec(
        project_name=project_name,
        overview=overview,
        epics=epics,
        tech_stack_raw="",
        database_tables_raw="",
        api_endpoints_raw="",
        existing_context={},
        integration_points=[],
        constraints=[],
        source_format="linear",
        source_path=json_path,
        epic_count=len(epics),
        story_count=story_count,
    )


def _group_issues(issues: list[dict]) -> list[Epic]:
    """Group issues into Epics by their first label; unlabelled → General."""
    epic_map: dict[str, list[Story]] = {}

    for issue in issues:
        labels = issue.get("labels", [])
        epic_name = labels[0] if labels else _GENERAL_EPIC
        title = issue.get("title", "Untitled")
        criteria = issue.get("description", "")
        story = Story(title=title, acceptance_criteria=criteria, phase_hint=epic_name)
        epic_map.setdefault(epic_name, []).append(story)

    return [Epic(name=name, stories=stories) for name, stories in epic_map.items()]
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/importer/test_extractor_linear.py -v
```
Expected: all 9 tests pass

- [ ] **Step 5: Commit**

```bash
git add claw_forge/importer/extractors/linear.py tests/importer/test_extractor_linear.py
git commit -m "feat(importer): implement Linear JSON extractor"
```

---

## Task 6: Jira Extractor

**Files:**
- Create: `claw_forge/importer/extractors/jira.py`
- Test: `tests/importer/test_extractor_jira.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/importer/test_extractor_jira.py
from __future__ import annotations

from pathlib import Path

import pytest

from claw_forge.importer.detector import detect, FormatResult
from claw_forge.importer.extractors.jira import extract_jira

FIXTURE = Path(__file__).parent / "fixtures" / "jira"


def test_extract_jira_xml_epic_count():
    xml_file = FIXTURE / "export.xml"
    result = FormatResult(format="jira", confidence="high", artifacts=[xml_file])
    spec = extract_jira(result)
    assert spec.epic_count == 2


def test_extract_jira_xml_story_count():
    xml_file = FIXTURE / "export.xml"
    result = FormatResult(format="jira", confidence="high", artifacts=[xml_file])
    spec = extract_jira(result)
    assert spec.story_count == 2


def test_extract_jira_xml_epic_names():
    xml_file = FIXTURE / "export.xml"
    result = FormatResult(format="jira", confidence="high", artifacts=[xml_file])
    spec = extract_jira(result)
    names = [e.name for e in spec.epics]
    assert "Authentication" in names
    assert "Task Management" in names


def test_extract_jira_xml_story_titles():
    xml_file = FIXTURE / "export.xml"
    result = FormatResult(format="jira", confidence="high", artifacts=[xml_file])
    spec = extract_jira(result)
    auth = next(e for e in spec.epics if e.name == "Authentication")
    assert auth.stories[0].title == "User Registration"


def test_extract_jira_csv_epic_count():
    csv_file = FIXTURE / "export.csv"
    result = FormatResult(format="jira", confidence="high", artifacts=[csv_file])
    spec = extract_jira(result)
    assert spec.epic_count == 2


def test_extract_jira_csv_story_count():
    csv_file = FIXTURE / "export.csv"
    result = FormatResult(format="jira", confidence="high", artifacts=[csv_file])
    spec = extract_jira(result)
    assert spec.story_count == 3


def test_extract_jira_csv_epic_names():
    csv_file = FIXTURE / "export.csv"
    result = FormatResult(format="jira", confidence="high", artifacts=[csv_file])
    spec = extract_jira(result)
    names = [e.name for e in spec.epics]
    assert "Authentication" in names
    assert "Task Management" in names


def test_extract_jira_source_format():
    xml_file = FIXTURE / "export.xml"
    result = FormatResult(format="jira", confidence="high", artifacts=[xml_file])
    spec = extract_jira(result)
    assert spec.source_format == "jira"


def test_extract_jira_acceptance_criteria_not_empty():
    xml_file = FIXTURE / "export.xml"
    result = FormatResult(format="jira", confidence="high", artifacts=[xml_file])
    spec = extract_jira(result)
    for epic in spec.epics:
        for story in epic.stories:
            assert story.acceptance_criteria.strip()
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run pytest tests/importer/test_extractor_jira.py -v
```
Expected: `ImportError: cannot import name 'extract_jira'`

- [ ] **Step 3: Implement `claw_forge/importer/extractors/jira.py`**

```python
"""Jira extractor — reads Jira XML or CSV export."""
from __future__ import annotations

import csv
import xml.etree.ElementTree as ET
from pathlib import Path

from claw_forge.importer.detector import FormatResult
from claw_forge.importer.extractors.base import Epic, ExtractedSpec, Story

_GENERAL_EPIC = "General"


def extract_jira(result: FormatResult) -> ExtractedSpec:
    """Extract structure from a Jira XML or CSV export."""
    artifact = result.artifacts[0]
    if artifact.suffix == ".xml":
        project_name, epics = _parse_xml(artifact)
    else:
        project_name, epics = _parse_csv(artifact)

    story_count = sum(len(e.stories) for e in epics)
    return ExtractedSpec(
        project_name=project_name,
        overview="",
        epics=epics,
        tech_stack_raw="",
        database_tables_raw="",
        api_endpoints_raw="",
        existing_context={},
        integration_points=[],
        constraints=[],
        source_format="jira",
        source_path=artifact,
        epic_count=len(epics),
        story_count=story_count,
    )


def _parse_xml(path: Path) -> tuple[str, list[Epic]]:
    root = ET.fromstring(path.read_text(encoding="utf-8"))

    channel = root.find("channel")
    project_name = "Unnamed Project"
    if channel is not None:
        title_el = channel.find("title")
        if title_el is not None and title_el.text:
            project_name = title_el.text.strip()

    epic_map: dict[str, list[Story]] = {}
    items = root.findall(".//item")
    for item in items:
        summary_el = item.find("summary")
        desc_el = item.find("description")
        title = summary_el.text.strip() if summary_el is not None and summary_el.text else "Untitled"
        criteria = desc_el.text.strip() if desc_el is not None and desc_el.text else ""

        epic_name = _GENERAL_EPIC
        for cf in item.findall(".//customfield"):
            cf_name = cf.find("customfieldname")
            if cf_name is not None and cf_name.text and "Epic Link" in cf_name.text:
                val = cf.find(".//customfieldvalue")
                if val is not None and val.text:
                    epic_name = val.text.strip()
                    break

        story = Story(title=title, acceptance_criteria=criteria, phase_hint=epic_name)
        epic_map.setdefault(epic_name, []).append(story)

    return project_name, [Epic(name=n, stories=s) for n, s in epic_map.items()]


def _parse_csv(path: Path) -> tuple[str, list[Epic]]:
    epic_map: dict[str, list[Story]] = {}
    project_name = path.stem.replace("-", " ").replace("_", " ").title()

    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            title = row.get("Summary", "Untitled").strip()
            criteria = row.get("Description", "").strip()
            epic_name = row.get("Epic Link", "").strip() or _GENERAL_EPIC
            story = Story(title=title, acceptance_criteria=criteria, phase_hint=epic_name)
            epic_map.setdefault(epic_name, []).append(story)

    return project_name, [Epic(name=n, stories=s) for n, s in epic_map.items()]
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/importer/test_extractor_jira.py -v
```
Expected: all 9 tests pass

- [ ] **Step 5: Commit**

```bash
git add claw_forge/importer/extractors/jira.py tests/importer/test_extractor_jira.py
git commit -m "feat(importer): implement Jira XML/CSV extractor"
```

---

## Task 7: Generic Markdown Extractor

**Files:**
- Create: `claw_forge/importer/extractors/generic.py`
- Test: `tests/importer/test_extractor_generic.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/importer/test_extractor_generic.py
from __future__ import annotations

from pathlib import Path

from claw_forge.importer.detector import detect
from claw_forge.importer.extractors.generic import extract_generic

FIXTURE = Path(__file__).parent / "fixtures" / "generic"


def test_extract_generic_project_name():
    result = detect(FIXTURE)
    spec = extract_generic(result)
    assert spec.project_name == "TaskTracker"


def test_extract_generic_overview():
    result = detect(FIXTURE)
    spec = extract_generic(result)
    assert "task management" in spec.overview.lower()


def test_extract_generic_epic_count():
    result = detect(FIXTURE)
    spec = extract_generic(result)
    # prd.md has ## Authentication and ## Task Management
    assert spec.epic_count == 2


def test_extract_generic_epic_names():
    result = detect(FIXTURE)
    spec = extract_generic(result)
    names = [e.name for e in spec.epics]
    assert "Authentication" in names
    assert "Task Management" in names


def test_extract_generic_story_count():
    result = detect(FIXTURE)
    spec = extract_generic(result)
    # Auth has 2 stories (### User Registration, ### User Login)
    # Tasks has 1 story (### Create Task)
    assert spec.story_count == 3


def test_extract_generic_stories_under_auth():
    result = detect(FIXTURE)
    spec = extract_generic(result)
    auth = next(e for e in spec.epics if e.name == "Authentication")
    assert len(auth.stories) == 2


def test_extract_generic_tech_stack():
    result = detect(FIXTURE)
    spec = extract_generic(result)
    assert "FastAPI" in spec.tech_stack_raw


def test_extract_generic_source_format():
    result = detect(FIXTURE)
    spec = extract_generic(result)
    assert spec.source_format == "generic"


def test_extract_generic_acceptance_criteria():
    result = detect(FIXTURE)
    spec = extract_generic(result)
    auth = next(e for e in spec.epics if e.name == "Authentication")
    reg = next(s for s in auth.stories if "Registration" in s.title)
    assert reg.acceptance_criteria.strip()
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run pytest tests/importer/test_extractor_generic.py -v
```
Expected: `ImportError: cannot import name 'extract_generic'`

- [ ] **Step 3: Implement `claw_forge/importer/extractors/generic.py`**

```python
"""Generic markdown extractor — heuristic parsing of any .md folder."""
from __future__ import annotations

import re
from pathlib import Path

from claw_forge.importer.detector import FormatResult
from claw_forge.importer.extractors.base import Epic, ExtractedSpec, Story

_TECH_HEADINGS = {"tech stack", "technology stack", "stack", "architecture", "technologies"}
_DB_HEADINGS = {"database schema", "database", "schema", "data model"}
_API_HEADINGS = {"api endpoints", "api", "endpoints", "routes"}


def extract_generic(result: FormatResult) -> ExtractedSpec:
    """Extract structure from generic markdown files using heading heuristics."""
    all_text = "\n\n".join(
        p.read_text(encoding="utf-8") for p in result.artifacts if p.exists()
    )
    lines = all_text.splitlines()

    project_name = _extract_h1(lines) or "Unnamed Project"
    overview = _extract_overview(lines)
    tech_stack_raw = _extract_section_by_headings(lines, _TECH_HEADINGS)
    database_tables_raw = _extract_section_by_headings(lines, _DB_HEADINGS)
    api_endpoints_raw = _extract_section_by_headings(lines, _API_HEADINGS)
    epics = _extract_epics(lines)

    story_count = sum(len(e.stories) for e in epics)
    source_path = result.artifacts[0].parent if result.artifacts else Path(".")

    return ExtractedSpec(
        project_name=project_name,
        overview=overview,
        epics=epics,
        tech_stack_raw=tech_stack_raw,
        database_tables_raw=database_tables_raw,
        api_endpoints_raw=api_endpoints_raw,
        existing_context={},
        integration_points=[],
        constraints=[],
        source_format="generic",
        source_path=source_path,
        epic_count=len(epics),
        story_count=story_count,
    )


def _extract_h1(lines: list[str]) -> str:
    for line in lines:
        if line.startswith("# ") and not line.startswith("## "):
            return line[2:].strip()
    return ""


def _extract_overview(lines: list[str]) -> str:
    """First non-empty, non-heading paragraph."""
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def _extract_section_by_headings(lines: list[str], headings: set[str]) -> str:
    collected: list[str] = []
    in_section = False
    for line in lines:
        if line.startswith("## "):
            heading_text = line[3:].strip().lower()
            if heading_text in headings:
                in_section = True
                continue
            elif in_section:
                break
        if in_section:
            collected.append(line)
    return "\n".join(collected).strip()


def _extract_epics(lines: list[str]) -> list[Epic]:
    """H2 headings (not matching tech/db/api) become epics; H3 under them become stories."""
    _skip = _TECH_HEADINGS | _DB_HEADINGS | _API_HEADINGS

    epics: list[Epic] = []
    current_epic: Epic | None = None
    current_story_title: str | None = None
    current_story_lines: list[str] = []

    def _flush_story() -> None:
        if current_epic is not None and current_story_title is not None:
            criteria = "\n".join(current_story_lines).strip()
            current_epic.stories.append(Story(
                title=current_story_title,
                acceptance_criteria=criteria,
                phase_hint=current_epic.name,
            ))

    for line in lines:
        if line.startswith("## ") and not line.startswith("### "):
            _flush_story()
            current_story_title = None
            current_story_lines = []
            heading = line[3:].strip()
            if heading.lower() not in _skip:
                current_epic = Epic(name=heading)
                epics.append(current_epic)
            else:
                current_epic = None
        elif line.startswith("### ") and current_epic is not None:
            _flush_story()
            current_story_title = line[4:].strip()
            current_story_lines = []
        elif current_epic is not None and current_story_title is not None:
            current_story_lines.append(line)

    _flush_story()
    return epics
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/importer/test_extractor_generic.py -v
```
Expected: all 9 tests pass

- [ ] **Step 5: Commit**

```bash
git add claw_forge/importer/extractors/generic.py tests/importer/test_extractor_generic.py
git commit -m "feat(importer): implement generic markdown extractor"
```

---

## Task 8: Converter

**Files:**
- Create: `claw_forge/importer/converter.py`
- Test: `tests/importer/test_converter.py`

- [ ] **Step 1: Write failing tests (mocking Claude)**

```python
# tests/importer/test_converter.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claw_forge.importer.extractors.base import Epic, ExtractedSpec, Story
from claw_forge.importer.converter import ConvertedSections, convert


def _make_spec() -> ExtractedSpec:
    return ExtractedSpec(
        project_name="TaskTracker",
        overview="A task management app.",
        epics=[
            Epic(name="Authentication", stories=[
                Story(
                    title="User Registration",
                    acceptance_criteria="Given a visitor, when they register, then account is created.",
                    phase_hint="Authentication",
                ),
            ]),
            Epic(name="Task Management", stories=[
                Story(
                    title="Create Task",
                    acceptance_criteria="Given auth user, when they post a task, then task is created.",
                    phase_hint="Task Management",
                ),
            ]),
        ],
        tech_stack_raw="FastAPI + React",
        database_tables_raw="users table: id, email\ntasks table: id, owner_id, title",
        api_endpoints_raw="POST /api/auth/register\nPOST /api/tasks",
        existing_context={},
        integration_points=[],
        constraints=[],
        source_format="bmad",
        source_path=Path("."),
        epic_count=2,
        story_count=2,
    )


def _mock_message(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=content)]
    return msg


def test_convert_returns_converted_sections():
    spec = _make_spec()
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_message(
        "<overview>A task app.</overview>"
    )
    with patch("claw_forge.importer.converter._make_client", return_value=fake_client):
        result = convert(spec, model="claude-haiku-4-5-20251001")
    assert isinstance(result, ConvertedSections)


def test_convert_overview_populated():
    spec = _make_spec()
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_message(
        "<overview>A task app.</overview>"
    )
    with patch("claw_forge.importer.converter._make_client", return_value=fake_client):
        result = convert(spec, model="claude-haiku-4-5-20251001")
    assert result.overview


def test_convert_core_features_has_one_per_epic():
    spec = _make_spec()
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_message(
        '<category name="Auth">- User can register</category>'
    )
    with patch("claw_forge.importer.converter._make_client", return_value=fake_client):
        result = convert(spec, model="claude-haiku-4-5-20251001")
    assert len(result.core_features) == 2  # one per epic


def test_convert_no_api_key_raises():
    spec = _make_spec()
    with patch("claw_forge.importer.converter._make_client", side_effect=EnvironmentError("no key")):
        with pytest.raises(EnvironmentError):
            convert(spec, model="claude-haiku-4-5-20251001")


def test_convert_retries_on_failure():
    spec = _make_spec()
    fake_client = MagicMock()
    call_count = 0

    def _side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("transient error")
        return _mock_message("<overview>ok</overview>")

    fake_client.messages.create.side_effect = _side_effect
    with patch("claw_forge.importer.converter._make_client", return_value=fake_client):
        result = convert(spec, model="claude-haiku-4-5-20251001")
    assert call_count >= 2


def test_converted_sections_dataclass():
    s = ConvertedSections(
        overview="<overview>x</overview>",
        technology_stack="<technology_stack/>",
        prerequisites="<prerequisites/>",
        core_features=["<category name='A'>- bullet</category>"],
        database_schema="<database_schema/>",
        api_endpoints="<api_endpoints_summary/>",
        implementation_steps="<implementation_steps/>",
        success_criteria="<success_criteria/>",
        ui_layout="<ui_layout/>",
    )
    assert len(s.core_features) == 1
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run pytest tests/importer/test_converter.py -v
```
Expected: `ImportError: cannot import name 'ConvertedSections'`

- [ ] **Step 3: Implement `claw_forge/importer/converter.py`**

```python
"""Claude-powered converter: ExtractedSpec → ConvertedSections (XML strings)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from claw_forge.importer.extractors.base import ExtractedSpec


@dataclass
class ConvertedSections:
    overview: str
    technology_stack: str
    prerequisites: str
    core_features: list[str]  # one <category name="…">…</category> per epic
    database_schema: str
    api_endpoints: str
    implementation_steps: str
    success_criteria: str
    ui_layout: str = ""


def convert(spec: ExtractedSpec, model: str = "claude-opus-4-6") -> ConvertedSections:
    """Convert an ExtractedSpec to ConvertedSections using Claude.

    Makes 3 + len(spec.epics) API calls — one per section group.
    Raises EnvironmentError if ANTHROPIC_API_KEY is not set.
    """
    client = _make_client()

    overview, technology_stack, prerequisites = _convert_overview(client, model, spec)
    core_features = _convert_features(client, model, spec)
    database_schema, api_endpoints = _convert_schema(client, model, spec)
    implementation_steps, success_criteria, ui_layout = _convert_phases(client, model, spec)

    return ConvertedSections(
        overview=overview,
        technology_stack=technology_stack,
        prerequisites=prerequisites,
        core_features=core_features,
        database_schema=database_schema,
        api_endpoints=api_endpoints,
        implementation_steps=implementation_steps,
        success_criteria=success_criteria,
        ui_layout=ui_layout,
    )


def _make_client():
    """Return an anthropic.Anthropic client. Raises EnvironmentError if key absent."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY is not set. "
            "Export it to use claw-forge import."
        )
    try:
        import anthropic
    except ImportError as exc:
        raise ImportError("'anthropic' package is required for claw-forge import.") from exc
    return anthropic.Anthropic(api_key=api_key)


def _call(client, model: str, prompt: str, max_tokens: int = 2048) -> str:
    """Make one Claude call with one retry on transient failure."""
    for attempt in range(2):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception:
            if attempt == 1:
                raise


def _convert_overview(client, model: str, spec: ExtractedSpec) -> tuple[str, str, str]:
    prompt = f"""\
Convert this project information into claw-forge XML sections.

Project name: {spec.project_name}
Overview: {spec.overview}
Tech stack: {spec.tech_stack_raw or "Not specified — infer sensible defaults."}

Output ONLY these three XML sections with no surrounding prose:

<overview>
  [2-3 sentence project overview]
</overview>
<technology_stack>
  <frontend><framework>...</framework><language>...</language></frontend>
  <backend><framework>...</framework><orm>...</orm></backend>
  <database><primary>...</primary></database>
</technology_stack>
<prerequisites>
  - [prerequisite 1]
  - [prerequisite 2]
</prerequisites>

Use &amp; for & in XML content. Output nothing outside these tags."""

    text = _call(client, model, prompt)
    overview = _extract_tag(text, "overview")
    tech = _extract_tag(text, "technology_stack")
    prereqs = _extract_tag(text, "prerequisites")
    return (
        f"<overview>{overview}</overview>",
        f"<technology_stack>{tech}</technology_stack>",
        f"<prerequisites>{prereqs}</prerequisites>",
    )


def _convert_features(client, model: str, spec: ExtractedSpec) -> list[str]:
    sections: list[str] = []
    for epic in spec.epics:
        stories_block = "\n\n".join(
            f"Story: {s.title}\nAcceptance criteria:\n{s.acceptance_criteria}"
            for s in epic.stories
        )
        prompt = f"""\
Convert these stories into claw-forge feature bullets for the "{epic.name}" category.

{stories_block}

Output ONLY this XML section:
<category name="{epic.name}">
  - [action-verb bullet]
  - [action-verb bullet]
</category>

Rules:
- Start each bullet with: "User can", "System returns", "API validates", "Admin can"
- One testable behaviour per bullet — no compound bullets with "and"
- 8–15 bullets total
- Use &amp; for & in XML attribute values
- Output nothing outside the <category> tags"""

        text = _call(client, model, prompt, max_tokens=1024)
        # Preserve the full <category ...>...</category> block
        if "<category" in text:
            start = text.index("<category")
            end = text.index("</category>") + len("</category>")
            sections.append(text[start:end])
        else:
            sections.append(text.strip())

    return sections


def _convert_schema(client, model: str, spec: ExtractedSpec) -> tuple[str, str]:
    if not spec.database_tables_raw and not spec.api_endpoints_raw:
        return "<database_schema><tables/></database_schema>", "<api_endpoints_summary/>"

    prompt = f"""\
Convert this database and API information into claw-forge XML sections.

Database info:
{spec.database_tables_raw or "Not provided."}

API info:
{spec.api_endpoints_raw or "Not provided."}

Output ONLY these two XML sections:
<database_schema>
  <tables>
    <table name="...">
      <column>id UUID PRIMARY KEY</column>
    </table>
  </tables>
</database_schema>
<api_endpoints_summary>
  <domain name="...">
    POST   /api/path   - description
  </domain>
</api_endpoints_summary>

Use &amp; for & in XML content. Output nothing outside these tags."""

    text = _call(client, model, prompt)
    schema = _extract_tag(text, "database_schema")
    endpoints = _extract_tag(text, "api_endpoints_summary")
    return (
        f"<database_schema>{schema}</database_schema>",
        f"<api_endpoints_summary>{endpoints}</api_endpoints_summary>",
    )


def _convert_phases(client, model: str, spec: ExtractedSpec) -> tuple[str, str, str]:
    epic_names = "\n".join(f"- {e.name}" for e in spec.epics)
    prompt = f"""\
Create implementation phases, success criteria, and UI layout for this project.

Project: {spec.project_name}
Overview: {spec.overview}
Epics (in order):
{epic_names}

Output ONLY these three XML sections:
<implementation_steps>
  <phase name="Phase 1: ...">
    Task description
  </phase>
</implementation_steps>
<success_criteria>
  <functionality>All features implemented and tested</functionality>
  <ux>Responsive on mobile and desktop</ux>
  <technical_quality>Test coverage &gt;= 90%</technical_quality>
</success_criteria>
<ui_layout>
  <structure>
    Root layout description
  </structure>
</ui_layout>

Use &amp; for & and &gt; for > in XML content. Output nothing outside these tags."""

    text = _call(client, model, prompt)
    steps = _extract_tag(text, "implementation_steps")
    criteria = _extract_tag(text, "success_criteria")
    ui = _extract_tag(text, "ui_layout")
    return (
        f"<implementation_steps>{steps}</implementation_steps>",
        f"<success_criteria>{criteria}</success_criteria>",
        f"<ui_layout>{ui}</ui_layout>",
    )


def _extract_tag(text: str, tag: str) -> str:
    """Extract inner content of the first <tag>…</tag> occurrence."""
    open_tag = f"<{tag}"
    close_tag = f"</{tag}>"
    start = text.find(open_tag)
    end = text.find(close_tag)
    if start == -1 or end == -1:
        return text.strip()
    # Find the > that closes the opening tag
    inner_start = text.index(">", start) + 1
    return text[inner_start:end].strip()
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/importer/test_converter.py -v
```
Expected: all 6 tests pass

- [ ] **Step 5: Commit**

```bash
git add claw_forge/importer/converter.py tests/importer/test_converter.py
git commit -m "feat(importer): implement Claude-powered converter"
```

---

## Task 9: Writer

**Files:**
- Create: `claw_forge/importer/writer.py`
- Test: `tests/importer/test_writer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/importer/test_writer.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from claw_forge.importer.converter import ConvertedSections
from claw_forge.importer.writer import write_spec
from claw_forge.spec.parser import ProjectSpec


def _sections() -> ConvertedSections:
    return ConvertedSections(
        overview="<overview>A task app for teams.</overview>",
        technology_stack=(
            "<technology_stack>"
            "<frontend><framework>React</framework></frontend>"
            "<backend><framework>FastAPI</framework></backend>"
            "<database><primary>PostgreSQL</primary></database>"
            "</technology_stack>"
        ),
        prerequisites="<prerequisites>- Python 3.12+</prerequisites>",
        core_features=[
            '<category name="Authentication">\n  - User can register\n  - User can login\n</category>',
            '<category name="Task Management">\n  - User can create a task\n</category>',
        ],
        database_schema=(
            "<database_schema><tables>"
            '<table name="users"><column>id UUID PRIMARY KEY</column></table>'
            "</tables></database_schema>"
        ),
        api_endpoints=(
            "<api_endpoints_summary>"
            '<domain name="Auth">POST /api/auth/register - Register</domain>'
            "</api_endpoints_summary>"
        ),
        implementation_steps=(
            "<implementation_steps>"
            '<phase name="Phase 1: Auth">Set up auth</phase>'
            "</implementation_steps>"
        ),
        success_criteria=(
            "<success_criteria>"
            "<functionality>All features pass</functionality>"
            "</success_criteria>"
        ),
        ui_layout="<ui_layout><structure>Dashboard layout</structure></ui_layout>",
    )


def test_write_spec_creates_file(tmp_path):
    sections = _sections()
    out = write_spec(sections, project_name="TaskTracker", project_path=tmp_path)
    assert out.exists()
    assert out.name == "app_spec.txt"


def test_write_spec_greenfield_when_no_manifest(tmp_path):
    sections = _sections()
    out = write_spec(sections, project_name="TaskTracker", project_path=tmp_path)
    content = out.read_text()
    assert 'mode="greenfield"' in content


def test_write_spec_brownfield_when_manifest_exists(tmp_path):
    manifest = {"stack": "FastAPI", "test_baseline": "47 tests", "conventions": "snake_case"}
    (tmp_path / "brownfield_manifest.json").write_text(json.dumps(manifest))
    sections = _sections()
    out = write_spec(sections, project_name="TaskTracker", project_path=tmp_path)
    assert out.name == "additions_spec.xml"
    content = out.read_text()
    assert 'mode="brownfield"' in content


def test_write_spec_contains_project_name(tmp_path):
    sections = _sections()
    out = write_spec(sections, project_name="TaskTracker", project_path=tmp_path)
    assert "TaskTracker" in out.read_text()


def test_write_spec_contains_feature_bullets(tmp_path):
    sections = _sections()
    out = write_spec(sections, project_name="TaskTracker", project_path=tmp_path)
    content = out.read_text()
    assert "User can register" in content
    assert "User can create a task" in content


def test_write_spec_parseable_by_parser(tmp_path):
    sections = _sections()
    out = write_spec(sections, project_name="TaskTracker", project_path=tmp_path)
    spec = ProjectSpec.from_file(out)
    assert spec.project_name == "TaskTracker"
    assert len(spec.features) >= 3


def test_write_spec_custom_out_path(tmp_path):
    sections = _sections()
    custom = tmp_path / "my_spec.xml"
    out = write_spec(sections, project_name="TaskTracker", project_path=tmp_path, out=custom)
    assert out == custom
    assert out.exists()


def test_write_spec_brownfield_contains_existing_context(tmp_path):
    manifest = {"stack": "FastAPI", "test_baseline": "47 tests", "conventions": "snake_case"}
    (tmp_path / "brownfield_manifest.json").write_text(json.dumps(manifest))
    sections = _sections()
    out = write_spec(sections, project_name="TaskTracker", project_path=tmp_path)
    content = out.read_text()
    assert "FastAPI" in content
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run pytest tests/importer/test_writer.py -v
```
Expected: `ImportError: cannot import name 'write_spec'`

- [ ] **Step 3: Implement `claw_forge/importer/writer.py`**

```python
"""Assembles ConvertedSections into app_spec.txt or additions_spec.xml."""
from __future__ import annotations

import json
from pathlib import Path

from claw_forge.importer.converter import ConvertedSections

_GREENFIELD_TEMPLATE = """\
<project_specification mode="greenfield">
  <project_name>{project_name}</project_name>
  {overview}
  <target_audience>
    See project overview.
  </target_audience>
  {technology_stack}
  {prerequisites}
  <core_features>
    {core_features}
  </core_features>
  {database_schema}
  {api_endpoints}
  {ui_layout}
  <design_system>
    <color_palette>Define your color palette here.</color_palette>
    <typography>Font family: Inter, system-ui, sans-serif</typography>
  </design_system>
  {implementation_steps}
  {success_criteria}
</project_specification>
"""

_BROWNFIELD_TEMPLATE = """\
<project_specification mode="brownfield">
  <project_name>{project_name}</project_name>
  <addition_summary>
    {overview_text}
  </addition_summary>
  <existing_context>
    <stack>{stack}</stack>
    <test_baseline>{test_baseline}</test_baseline>
    <conventions>{conventions}</conventions>
  </existing_context>
  <features_to_add>
    {feature_bullets}
  </features_to_add>
  <integration_points>
    See architecture documentation.
  </integration_points>
  <constraints>
    All existing tests must stay green.
  </constraints>
  {implementation_steps}
  {success_criteria}
</project_specification>
"""


def write_spec(
    sections: ConvertedSections,
    project_name: str,
    project_path: Path,
    out: Path | None = None,
) -> Path:
    """Assemble sections into a spec file and write it.

    Auto-detects greenfield vs brownfield from brownfield_manifest.json.
    Returns the path of the written file.
    """
    manifest_path = project_path / "brownfield_manifest.json"
    is_brownfield = manifest_path.exists()

    if is_brownfield:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        content = _assemble_brownfield(sections, project_name, manifest)
        default_name = "additions_spec.xml"
    else:
        content = _assemble_greenfield(sections, project_name)
        default_name = "app_spec.txt"

    dest = out if out else project_path / default_name
    dest.write_text(content, encoding="utf-8")
    return dest


def _assemble_greenfield(sections: ConvertedSections, project_name: str) -> str:
    core_features_block = "\n    ".join(sections.core_features)
    return _GREENFIELD_TEMPLATE.format(
        project_name=project_name,
        overview=sections.overview,
        technology_stack=sections.technology_stack,
        prerequisites=sections.prerequisites,
        core_features=core_features_block,
        database_schema=sections.database_schema,
        api_endpoints=sections.api_endpoints,
        ui_layout=sections.ui_layout,
        implementation_steps=sections.implementation_steps,
        success_criteria=sections.success_criteria,
    )


def _assemble_brownfield(
    sections: ConvertedSections,
    project_name: str,
    manifest: dict,
) -> str:
    # Extract plain text from <overview> tag
    overview_text = sections.overview
    if "<overview>" in overview_text:
        overview_text = overview_text.replace("<overview>", "").replace("</overview>", "").strip()

    # Flatten core_features to plain bullet lines
    import re as _re
    bullet_lines: list[str] = []
    for block in sections.core_features:
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                bullet_lines.append(stripped)
    feature_bullets = "\n    ".join(bullet_lines)

    return _BROWNFIELD_TEMPLATE.format(
        project_name=project_name,
        overview_text=overview_text,
        stack=manifest.get("stack", ""),
        test_baseline=manifest.get("test_baseline", ""),
        conventions=manifest.get("conventions", ""),
        feature_bullets=feature_bullets,
        implementation_steps=sections.implementation_steps,
        success_criteria=sections.success_criteria,
    )
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/importer/test_writer.py -v
```
Expected: all 8 tests pass

- [ ] **Step 5: Commit**

```bash
git add claw_forge/importer/writer.py tests/importer/test_writer.py
git commit -m "feat(importer): implement spec writer (greenfield + brownfield)"
```

---

## Task 10: Public API + CLI Command

**Files:**
- Modify: `claw_forge/importer/__init__.py` — add `extract()`, `import_spec()` public API
- Modify: `claw_forge/cli.py` — add `import_spec` command after `plan()`

- [ ] **Step 1: Write failing test for public API**

```python
# tests/importer/test_integration.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claw_forge.importer import detect, extract
from claw_forge.importer.converter import ConvertedSections

FIXTURE_BMAD = Path(__file__).parent / "fixtures" / "bmad"
FIXTURE_LINEAR = Path(__file__).parent / "fixtures" / "linear"
FIXTURE_JIRA = Path(__file__).parent / "fixtures" / "jira"
FIXTURE_GENERIC = Path(__file__).parent / "fixtures" / "generic"


def test_detect_re_exported():
    result = detect(FIXTURE_BMAD)
    assert result.format == "bmad"


def test_extract_bmad_via_public_api():
    result = detect(FIXTURE_BMAD)
    spec = extract(result)
    assert spec.project_name == "TaskTracker"
    assert spec.epic_count == 2


def test_extract_linear_via_public_api():
    result = detect(FIXTURE_LINEAR)
    spec = extract(result)
    assert spec.source_format == "linear"
    assert spec.story_count == 4


def test_extract_jira_via_public_api():
    result = detect(FIXTURE_JIRA)
    spec = extract(result)
    assert spec.source_format == "jira"


def test_extract_generic_via_public_api():
    result = detect(FIXTURE_GENERIC)
    spec = extract(result)
    assert spec.source_format == "generic"
    assert spec.epic_count == 2


def _fake_sections() -> ConvertedSections:
    return ConvertedSections(
        overview="<overview>A task app.</overview>",
        technology_stack="<technology_stack><frontend><framework>React</framework></frontend><backend><framework>FastAPI</framework></backend><database><primary>PostgreSQL</primary></database></technology_stack>",
        prerequisites="<prerequisites>- Python 3.12+</prerequisites>",
        core_features=['<category name="Auth">\n  - User can register\n  - User can login\n</category>'],
        database_schema="<database_schema><tables><table name='users'><column>id UUID PK</column></table></tables></database_schema>",
        api_endpoints="<api_endpoints_summary><domain name='Auth'>POST /api/auth/register - Register</domain></api_endpoints_summary>",
        implementation_steps="<implementation_steps><phase name='Phase 1: Auth'>Set up auth</phase></implementation_steps>",
        success_criteria="<success_criteria><functionality>All features pass</functionality></success_criteria>",
        ui_layout="<ui_layout><structure>Dashboard</structure></ui_layout>",
    )


def test_full_pipeline_greenfield(tmp_path):
    from claw_forge.importer import import_spec
    from claw_forge.spec.parser import ProjectSpec

    with patch("claw_forge.importer.converter.convert", return_value=_fake_sections()):
        out = import_spec(path=FIXTURE_BMAD, project_path=tmp_path)

    assert out.exists()
    assert out.name == "app_spec.txt"
    spec = ProjectSpec.from_file(out)
    assert spec.project_name == "TaskTracker"
    assert len(spec.features) >= 2
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run pytest tests/importer/test_integration.py -v
```
Expected: `ImportError` — `detect`, `extract`, `import_spec` not yet exported

- [ ] **Step 3: Implement `claw_forge/importer/__init__.py`**

```python
"""claw-forge import pipeline — converts 3rd-party harness output to app_spec."""
from __future__ import annotations

from pathlib import Path

from claw_forge.importer.converter import ConvertedSections, convert
from claw_forge.importer.detector import FormatResult, detect
from claw_forge.importer.extractors.base import Epic, ExtractedSpec, Story
from claw_forge.importer.writer import write_spec


def extract(result: FormatResult) -> ExtractedSpec:
    """Dispatch to the correct extractor based on result.format."""
    if result.format == "bmad":
        from claw_forge.importer.extractors.bmad import extract_bmad
        return extract_bmad(result)
    if result.format == "linear":
        from claw_forge.importer.extractors.linear import extract_linear
        return extract_linear(result)
    if result.format == "jira":
        from claw_forge.importer.extractors.jira import extract_jira
        return extract_jira(result)
    from claw_forge.importer.extractors.generic import extract_generic
    return extract_generic(result)


def import_spec(
    path: Path,
    project_path: Path,
    model: str = "claude-opus-4-6",
    out: Path | None = None,
) -> Path:
    """Full pipeline: detect → extract → convert → write.

    Returns the path of the written spec file.
    """
    result = detect(path)
    spec = extract(result)
    sections = convert(spec, model=model)
    return write_spec(sections, project_name=spec.project_name, project_path=project_path, out=out)


__all__ = [
    "detect",
    "extract",
    "convert",
    "import_spec",
    "FormatResult",
    "ExtractedSpec",
    "Epic",
    "Story",
    "ConvertedSections",
]
```

- [ ] **Step 4: Run integration tests — expect pass**

```bash
uv run pytest tests/importer/test_integration.py -v
```
Expected: all 7 tests pass

- [ ] **Step 5: Add `import_spec` CLI command to `claw_forge/cli.py`**

Insert after the closing of the `plan()` function (after line ~2178). Add this new command:

```python
@app.command("import")
def import_spec_cmd(
    path: str = typer.Argument(..., help="Path to harness output folder or file (BMAD, Linear, Jira, markdown)."),
    project: str = typer.Option(".", "--project", "-p", help="Project directory."),
    model: str = typer.Option(
        "claude-opus-4-6", "--model", "-m",
        help="Model to use for spec conversion.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    config: str = typer.Option("claw-forge.yaml", "--config", "-c", help="Path to claw-forge.yaml."),
    out: str = typer.Option("", "--out", "-o", help="Output filename (default: auto-detected)."),
) -> None:
    """Convert 3rd-party harness output to a claw-forge spec file.

    Auto-detects format (BMAD, Linear JSON, Jira XML/CSV, generic markdown),
    extracts structure with rules, then uses Claude to write clean feature bullets.
    Auto-detects greenfield vs brownfield from brownfield_manifest.json.

    Examples:

        # Import BMAD output
        claw-forge import ./bmad-output

        # Import Linear JSON export
        claw-forge import ./linear-export.json

        # Skip confirmation prompt (for CI)
        claw-forge import ./bmad-output --yes
    """
    from claw_forge.importer import detect, extract, import_spec
    from claw_forge.importer.converter import convert
    from claw_forge.importer.writer import write_spec

    input_path = Path(path).resolve()
    project_path = Path(project).resolve()
    out_path = Path(out).resolve() if out else None

    # ── Detect ───────────────────────────────────────────────────────────────
    console.print(f"\nScanning [bold]{input_path}[/bold]...")
    try:
        result = detect(input_path)
    except FileNotFoundError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(1) from None

    confidence_color = {"high": "green", "medium": "yellow", "low": "red"}[result.confidence]
    console.print(
        f"[{confidence_color}]✓ Detected:[/{confidence_color}] "
        f"[bold]{result.format.upper()}[/bold] — {result.summary}"
    )
    console.print(f"  Confidence: [{confidence_color}]{result.confidence}[/{confidence_color}]")

    if result.confidence == "low":
        console.print(
            "[yellow]⚠ Low confidence — treating as generic markdown.[/yellow]"
        )

    # ── Confirm ──────────────────────────────────────────────────────────────
    if not yes:
        confirmed = typer.confirm("\nProceed with import?", default=True)
        if not confirmed:
            console.print("[dim]Aborted.[/dim]")
            raise typer.Exit(0)

    # ── Extract ──────────────────────────────────────────────────────────────
    console.print("\nExtracting structure...", end=" ")
    from claw_forge.importer import extract as _extract
    spec = _extract(result)

    if spec.story_count == 0:
        console.print(
            "\n[red]✗ No features extracted.[/red] "
            "Check that your export contains stories or issues."
        )
        raise typer.Exit(1) from None

    console.print(
        f"[green]✓[/green]  "
        f"{spec.epic_count} epic(s), {spec.story_count} story/stories"
        + (f", tech stack detected" if spec.tech_stack_raw else "")
    )

    # ── Detect output mode ───────────────────────────────────────────────────
    manifest_path = project_path / "brownfield_manifest.json"
    mode = "brownfield" if manifest_path.exists() else "greenfield"
    console.print(f"Auto-detected: [bold]{mode}[/bold]"
                  + ("" if mode == "greenfield" else " (brownfield_manifest.json found)"))

    # ── Convert ──────────────────────────────────────────────────────────────
    console.print("Converting to spec via Claude...", end=" ")
    try:
        sections = convert(spec, model=model)
        console.print("[green]✓[/green]")
    except EnvironmentError as exc:
        console.print(f"\n[red]✗ {exc}[/red]")
        raise typer.Exit(1) from None
    except Exception as exc:
        console.print(f"\n[red]✗ Conversion failed: {exc}[/red]")
        raise typer.Exit(1) from None

    # ── Write ────────────────────────────────────────────────────────────────
    default_name = "additions_spec.xml" if mode == "brownfield" else "app_spec.txt"
    dest = out_path or project_path / default_name

    if dest.exists() and not yes:
        overwrite = typer.confirm(f"\n{dest.name} already exists. Overwrite?", default=False)
        if not overwrite:
            console.print("[dim]Aborted.[/dim]")
            raise typer.Exit(0)

    out_file = write_spec(
        sections,
        project_name=spec.project_name,
        project_path=project_path,
        out=out_path,
    )

    # ── Summary ──────────────────────────────────────────────────────────────
    from claw_forge.spec.parser import ProjectSpec
    try:
        parsed = ProjectSpec.from_file(out_file)
        feature_count = len(parsed.features)
        category_count = len({f.category for f in parsed.features})
        phase_count = len(parsed.implementation_phases)
        table_count = len(parsed.database_tables)
        endpoint_count = sum(len(v) for v in parsed.api_endpoints.values())
    except Exception:
        feature_count = category_count = phase_count = table_count = endpoint_count = 0

    console.print(f"\n[green]✓ Written:[/green] [bold]{out_file.name}[/bold]")
    if feature_count:
        console.print(f"  Features:  {feature_count} bullets across {category_count} categories")
    if phase_count:
        console.print(f"  Phases:    {phase_count} implementation steps")
    if table_count:
        console.print(f"  Tables:    {table_count} database tables")
    if endpoint_count:
        console.print(f"  Endpoints: {endpoint_count} API endpoints")

    console.print(
        f"\n[bold cyan]Next steps:[/bold cyan]"
        f"\n  1. Review [bold]{out_file.name}[/bold]"
        f"\n  2. [bold]claw-forge validate-spec {out_file.name}[/bold]"
        f"\n  3. [bold]claw-forge plan {out_file.name}[/bold]"
    )
```

- [ ] **Step 6: Verify CLI command is registered**

```bash
uv run claw-forge --help | grep import
```
Expected: `import  Convert 3rd-party harness output to a claw-forge spec file.`

- [ ] **Step 7: Commit**

```bash
git add claw_forge/importer/__init__.py claw_forge/cli.py tests/importer/test_integration.py
git commit -m "feat(importer): public API + claw-forge import CLI command"
```

---

## Task 11: Slash Commands

**Files:**
- Create: `.claude/commands/import-spec.md`
- Create: `claw_forge/commands_scaffold/import-spec.md`

- [ ] **Step 1: Write `.claude/commands/import-spec.md`**

```markdown
# Import Spec from Harness Tool

Convert 3rd-party harness tool output (BMAD, Linear, Jira, or generic markdown) into a
claw-forge `app_spec.txt` or `additions_spec.xml` interactively.

---

## Step 1: Detect format

Run the detector on the path the user provides:

```bash
uv run python -c "
from claw_forge.importer import detect
from pathlib import Path
import sys
result = detect(Path(sys.argv[1]))
print(f'Format: {result.format}')
print(f'Confidence: {result.confidence}')
print(f'Summary: {result.summary}')
print(f'Artifacts: {len(result.artifacts)} file(s)')
" <PATH>
```

Show the result to the user:
```
Detected: BMAD — prd.md + architecture.md + 3 epics (14 stories)
Confidence: high
```

Ask: "Does this look right? (y/n)"

- If no: ask the user which format it actually is (bmad/linear/jira/generic) and override
- If yes: proceed to Step 2

---

## Step 2: Extract structure

```bash
uv run python -c "
from claw_forge.importer import detect, extract
from pathlib import Path
import sys
result = detect(Path(sys.argv[1]))
spec = extract(result)
print(f'Project: {spec.project_name}')
print(f'Epics ({spec.epic_count}):')
for epic in spec.epics:
    print(f'  - {epic.name} ({len(epic.stories)} stories)')
print(f'Tech stack: {spec.tech_stack_raw[:80] if spec.tech_stack_raw else \"not detected\"}')
" <PATH>
```

Show a summary table:

```
Project:  TaskTracker
Epics:    3
  • Authentication (2 stories)
  • Task Management (3 stories)
  • API Layer (2 stories)
Tech stack:  FastAPI + React (detected from architecture.md)
```

If 0 stories extracted: "No stories found in the export. Please check the file format and try again."

Ask: "Does this structure look right? (y/n)"

---

## Step 3: Convert section by section

Run the converter one section at a time and show each to the user for approval.

### Section A: Overview + Tech Stack

```bash
uv run python -c "
from claw_forge.importer import detect, extract
from claw_forge.importer.converter import _make_client, _convert_overview
from pathlib import Path
import sys

result = detect(Path(sys.argv[1]))
spec = extract(result)
client = _make_client()
overview, tech, prereqs = _convert_overview(client, 'claude-opus-4-6', spec)
print(overview)
print(tech)
print(prereqs)
" <PATH>
```

Show the output. Ask: "Does this look right? If not, describe changes and I'll regenerate."

If changes requested: incorporate feedback into a revised prompt and regenerate.

### Section B: Core Features (one epic at a time)

For each epic:
```bash
uv run python -c "
from claw_forge.importer import detect, extract
from claw_forge.importer.converter import _make_client, _call
from pathlib import Path
import sys

result = detect(Path(sys.argv[1]))
spec = extract(result)
client = _make_client()
epic = spec.epics[int(sys.argv[2])]
stories_block = '\n\n'.join(
    f'Story: {s.title}\nAcceptance criteria:\n{s.acceptance_criteria}'
    for s in epic.stories
)
prompt = f'''Convert these stories into claw-forge feature bullets for \"{epic.name}\".
{stories_block}
Output ONLY: <category name=\"{epic.name}\">...</category>
Rules: action verbs, one testable behaviour per bullet, 8-15 bullets.'''
print(_call(client, 'claude-opus-4-6', prompt, max_tokens=1024))
" <PATH> <EPIC_INDEX>
```

Show each category block. Ask for approval or changes before moving to the next epic.

### Section C: Database Schema + API Endpoints

Run `_convert_schema()` with the same pattern, show output, ask for approval.

### Section D: Implementation Phases + Success Criteria

Run `_convert_phases()`, show output, ask for approval.

---

## Step 4: Write the file

Once all sections approved, assemble and write:

```bash
uv run claw-forge import <PATH> --project . --yes
```

Or write manually from the approved sections using the writer:
```bash
uv run python -c "
from claw_forge.importer.writer import write_spec
from claw_forge.importer.converter import ConvertedSections
# ... populate from approved sections ...
out = write_spec(sections, project_name='...', project_path=Path('.'))
print(f'Written: {out}')
"
```

Show the written file path.

---

## Step 5: Validate and plan

```
✅ Spec written: app_spec.txt

Next steps:
  1. claw-forge validate-spec app_spec.txt
  2. claw-forge plan app_spec.txt
  3. claw-forge run --concurrency 5
```

Run validate-spec automatically and show any issues.
```

- [ ] **Step 2: Copy to commands_scaffold**

The scaffold copy must be identical so `claw-forge init` seeds it into new projects:

```bash
cp .claude/commands/import-spec.md claw_forge/commands_scaffold/import-spec.md
```

- [ ] **Step 3: Verify scaffold copy exists**

```bash
ls claw_forge/commands_scaffold/
```
Expected: `example.md  import-spec.md`

- [ ] **Step 4: Commit**

```bash
git add .claude/commands/import-spec.md claw_forge/commands_scaffold/import-spec.md
git commit -m "feat(importer): add /import-spec slash command + scaffold"
```

---

## Task 12: Full Test Suite + Coverage

**Files:**
- Test: `tests/importer/` — run all tests, check coverage

- [ ] **Step 1: Run the full importer test suite**

```bash
uv run pytest tests/importer/ -v
```
Expected: all tests pass

- [ ] **Step 2: Run full suite with coverage**

```bash
uv run pytest tests/ -q --cov=claw_forge --cov-report=term-missing 2>&1 | tail -20
```
Expected: coverage >= 90% (the gate in `pyproject.toml`)

- [ ] **Step 3: Run lint**

```bash
uv run ruff check claw_forge/importer/ tests/importer/
```
Expected: `All checks passed!`

- [ ] **Step 4: Run mypy**

```bash
uv run mypy claw_forge/importer/ --ignore-missing-imports
```
Expected: `Success: no issues found`

- [ ] **Step 5: Fix any lint or type errors found in steps 3–4, then re-run to confirm clean**

- [ ] **Step 6: Final commit**

```bash
git add -u
git commit -m "feat(importer): import-spec pipeline complete — BMAD/Linear/Jira/generic"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ BMAD extractor — Task 4
- ✅ Linear extractor — Task 5
- ✅ Jira XML + CSV extractor — Task 6
- ✅ Generic markdown extractor — Task 7
- ✅ Format detector with all 4 formats — Task 3
- ✅ Converter with Claude calls + retry — Task 8
- ✅ Writer greenfield + brownfield — Task 9
- ✅ Auto-detect greenfield/brownfield — Task 9
- ✅ Public API `detect()`, `extract()`, `import_spec()` — Task 10
- ✅ CLI `claw-forge import` command — Task 10
- ✅ Confirmation prompt + `--yes` bypass — Task 10
- ✅ Zero-story abort — Task 10
- ✅ Existing file overwrite prompt — Task 10
- ✅ `/import-spec` slash command — Task 11
- ✅ `commands_scaffold` copy — Task 11
- ✅ Test fixtures for all 4 formats — Task 1
- ✅ Integration test full pipeline — Task 10
- ✅ Coverage gate — Task 12

**Type consistency across tasks:**
- `FormatResult.format` — `Literal["bmad","linear","jira","generic"]` — defined Task 2, used Tasks 3-7, 10
- `ExtractedSpec.epics` — `list[Epic]` — defined Task 2, used Tasks 4-10
- `ConvertedSections.core_features` — `list[str]` — defined Task 8, used Tasks 9, 10
- `convert(spec, model)` — defined Task 8, called in Task 10 `import_spec()`
- `write_spec(sections, project_name, project_path, out)` — defined Task 9, called Task 10
- `_make_client()` — defined Task 8, patched in tests Task 8
