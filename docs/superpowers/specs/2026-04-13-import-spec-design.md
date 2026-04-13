# import-spec — Design Spec

**Date:** 2026-04-13
**Status:** Approved

## Summary

A new `claw-forge import <path>` CLI command and `/import-spec` slash command that converts
3rd-party harness tool output (BMAD, Linear, Jira, generic markdown) into a claw-forge
`app_spec.txt` or `additions_spec.xml` using a hybrid rule-based extraction + Claude conversion
pipeline.

---

## Goals

- Accept output from BMAD, Linear JSON export, Jira XML/CSV export, and generic markdown folders
- Auto-detect format with confirmation before proceeding
- Auto-detect greenfield vs brownfield output mode
- Rule-based extraction for structure; Claude-powered conversion for bullet writing
- CLI for scripted/automated use; slash command for interactive section-by-section review
- Full test coverage with fixture-based unit tests per format

---

## Architecture

### Module layout

```
claw_forge/importer/
├── __init__.py          # public API: detect(), extract(), convert(), import_spec()
├── detector.py          # inspects path → FormatResult
├── extractors/
│   ├── __init__.py
│   ├── base.py          # ExtractedSpec + Epic + Story dataclasses
│   ├── bmad.py          # prd.md + architecture.md + stories/**/*.md
│   ├── linear.py        # issues JSON export
│   ├── jira.py          # XML or CSV export
│   └── generic.py       # any folder of .md files
├── converter.py         # Claude-powered: ExtractedSpec → XML section dict
└── writer.py            # assembles and writes app_spec.txt / additions_spec.xml

claw_forge/cli.py        # new import_spec() command

.claude/commands/import-spec.md           # interactive slash command
claw_forge/commands_scaffold/import-spec.md  # seeded by claw-forge init

tests/importer/
├── fixtures/            # small anonymised sample exports per format
├── test_detector.py
├── test_extractor_bmad.py
├── test_extractor_linear.py
├── test_extractor_jira.py
├── test_extractor_generic.py
└── test_converter.py
```

### Data flow

```
<path>
  │
  ▼
detector.py ──→ FormatResult(format, confidence, artifacts, summary)
  │
  ▼
extractors/<format>.py ──→ ExtractedSpec(epics, stories, tech_stack, schema, …)
  │
  ▼
converter.py (Claude) ──→ dict of filled XML section strings
  │
  ▼
writer.py ──→ app_spec.txt          (greenfield — no brownfield_manifest.json)
          └─→ additions_spec.xml    (brownfield — brownfield_manifest.json exists)
```

---

## Format Detection (`detector.py`)

Returns a `FormatResult`:

```python
@dataclass
class FormatResult:
    format: Literal["bmad", "linear", "jira", "generic"]
    confidence: Literal["high", "medium", "low"]
    artifacts: list[Path]   # files the extractor should read
    summary: str            # e.g. "BMAD output with 3 epics, 14 stories"
```

Detection rules:

| Format  | Signals |
|---------|---------|
| BMAD    | `prd.md` present, OR `_bmad-output/` dir, OR `stories/` dir with `epic-*/` subdirs |
| Linear  | `.json` file with top-level `issues` array where items have `identifier` + `state` + `labels` |
| Jira    | `.xml` with `<rss>` or `<jira>` root, OR `.csv` with `Issue key` / `Summary` / `Epic Link` columns |
| Generic | Any folder of `.md` files that did not match the above |

Falls back to `generic` with `confidence: low` if nothing matches. Never silently picks the
wrong format — always shows detection result and asks for confirmation before proceeding.

---

## Extracted Spec (`extractors/base.py`)

The contract between all extractors and the converter. Every extractor produces one
`ExtractedSpec`; the converter never inspects `source_format`.

```python
@dataclass
class Story:
    title: str
    acceptance_criteria: str   # raw text, may be Gherkin — converter rewrites it
    phase_hint: str            # epic name or phase label from the source tool

@dataclass
class Epic:
    name: str
    stories: list[Story]

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
    existing_context: dict[str, str]   # stack, test_baseline, conventions
    integration_points: list[str]
    constraints: list[str]

    # metadata
    source_format: str
    source_path: Path
    epic_count: int
    story_count: int
```

Extractors never rewrite content — they extract. The converter does all rewriting.

---

## Extractor Behaviour Per Format

### BMAD (`bmad.py`)
- `prd.md` → `overview`, epic list
- `architecture.md` → `tech_stack_raw`, `database_tables_raw`, `api_endpoints_raw`
- `stories/epic-N/story-M.md` → one `Story` per file; frontmatter `title:` + body as `acceptance_criteria`

### Linear (`linear.py`)
- Top-level `issues` array → stories grouped by `labels[0]` (= epic)
- Issues with no labels fall into a synthetic `"General"` epic
- `title` → `Story.title`; `description` → `Story.acceptance_criteria`
- `project.name` → `project_name`; `project.description` → `overview`

### Jira (`jira.py`)
- XML: `<item>` elements; `<customfield name="Epic Link">` groups into epics
- CSV: rows grouped by `Epic Link` column; `Summary` → title; `Description` → criteria
- `<project>` element or CSV header → `project_name`

### Generic (`generic.py`)
- H1 headings → epic names; H2/H3 under them → story titles
- Bullet lists or paragraphs under each story → `acceptance_criteria`
- `## Tech Stack` / `## Architecture` sections → `tech_stack_raw`
- `## Database` / `## Schema` sections → `database_tables_raw`
- `## API` / `## Endpoints` sections → `api_endpoints_raw`

---

## Converter (`converter.py`)

One Claude call per section to keep prompts focused and avoid truncation on large specs.

| Call | Input | Output XML sections |
|------|-------|---------------------|
| 1 | `overview` + `tech_stack_raw` | `<overview>`, `<technology_stack>`, `<prerequisites>` |
| 2 | Per-epic stories + acceptance criteria | `<category name="…">` bullets (one call per epic) |
| 3 | `database_tables_raw` + `api_endpoints_raw` | `<database_schema>`, `<api_endpoints_summary>` |
| 4 | Epic names + phase hints | `<implementation_steps>`, `<success_criteria>`, `<ui_layout>` |

Each call's system prompt instructs Claude to:
- Output only the requested XML section (no surrounding prose)
- Write bullets as action-verb sentences: "User can…", "System returns…", "API validates…"
- Keep each bullet to one testable behaviour
- Use `&amp;` for `&` in XML content
- Target 8–15 bullets per category

The converter accumulates section strings; `writer.py` assembles the final XML.

Uses the model specified via `--model` (default `claude-opus-4-6`).

---

## Writer (`writer.py`)

- Checks for `brownfield_manifest.json` in project dir → selects output mode
- Greenfield: assembles full `app_spec.txt` from all sections using the template structure
- Brownfield: assembles `additions_spec.xml` using brownfield template, populates
  `<existing_context>` from manifest, `<features_to_add>` from converted bullets,
  `<integration_points>` and `<constraints>` from `ExtractedSpec`
- If output file already exists: CLI prompts to overwrite; slash command shows diff

---

## CLI Command (`claw-forge import`)

```
$ claw-forge import ./bmad-output

Scanning ./bmad-output...
✓ Detected: BMAD output — prd.md + architecture.md + 3 epics (14 stories)
  Confidence: high

Proceed with import? [Y/n]: Y

Extracting structure...  ✓  3 epics, 14 stories, FastAPI/React stack detected
Converting to spec via Claude...  ✓
Auto-detected: greenfield (no brownfield_manifest.json found)

✓ Written: app_spec.txt
  Features: 47 bullets across 3 categories
  Phases:   3 implementation steps
  Tables:   4 database tables
  Endpoints: 12 API endpoints

Next steps:
  1. Review app_spec.txt
  2. claw-forge validate-spec app_spec.txt
  3. claw-forge plan app_spec.txt
```

**Signature:**
```python
def import_spec(
    path: str = typer.Argument(..., help="Path to harness output folder or file."),
    project: str = typer.Option(".", "--project", "-p", help="Project directory."),
    model: str = typer.Option("claude-opus-4-6", "--model", "-m", help="Model for conversion."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    config: str = typer.Option("claw-forge.yaml", "--config", "-c"),
    out: str = typer.Option("", "--out", "-o", help="Output filename (default: auto)."),
) -> None:
```

---

## Slash Command (`/import-spec`)

Interactive section-by-section review before writing. Steps:

1. Run detector → show `FormatResult`, ask to confirm format
2. Run extractor → show summary table (epics, stories, tech stack found)
3. Show each converted section for approval:
   - `<overview>` + `<technology_stack>`
   - `<core_features>` category by category
   - `<database_schema>` + `<api_endpoints_summary>`
   - `<implementation_steps>` + `<success_criteria>`
4. Write file only after full approval
5. Suggest: `claw-forge validate-spec` → `claw-forge plan`

Seeded into new projects by `claw-forge init` via `commands_scaffold/import-spec.md`.

---

## Error Handling

| Failure | Behaviour |
|---------|-----------|
| Path not found | Error: "No files found at `<path>`" |
| Format undetected | Falls back to `generic` with `confidence: low`, warns user |
| Extractor finds 0 stories | Aborts: "No features extracted — check export contains stories/issues" |
| Claude call fails | Retries once; on second failure surfaces raw `ExtractedSpec` as readable summary |
| Output file exists | CLI prompts to overwrite; slash command shows diff |

---

## Testing

- `tests/importer/fixtures/` — small anonymised sample exports for each format
- Detector + extractor tests: pure unit tests, no Claude calls, assert `ExtractedSpec` fields
- Converter tests: mock Claude call, assert XML sections are well-formed
- One integration test per format: fixture → `import_spec()` → assert output parses via `spec/parser.py`
- Coverage gate: same 90% threshold as rest of codebase

---

## Out of Scope

- GitHub Issues, Asana, ClickUp exports (future formats — add extractor per format)
- Interactive bullet editing within CLI (slash command only)
- Automatic `claw-forge plan` after import (user runs it explicitly)
