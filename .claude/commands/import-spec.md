# /import-spec

Convert a 3rd-party harness tool export (BMAD, Linear, Jira, or generic markdown)
into a claw-forge spec file through interactive section-by-section review.

## Usage

/import-spec <path-to-export>

Example: /import-spec ./bmad-output
Example: /import-spec ./linear-export.md --model claude-sonnet-4-6
Example: /import-spec ./jira-export --project ./myapp

## What this command does

1. **Detect format** — scans the path and identifies the export format
2. **Extract structure** — pulls epics, stories, tech stack from the files
3. **Convert section by section** — presents each XML section for your review before writing
4. **Write spec** — only after you approve all sections

---

## Instructions for Claude

When this command is invoked with a path argument, follow these steps exactly.

### Step 1: Format Detection

Run the detector:

```python
from pathlib import Path
from claw_forge.importer import detect

result = detect(Path("<path>"))
print(result)
```

Show the user a summary:

```
Detected format: <format_name>
Confidence:      <confidence_level>
Epics found:     <epic_count>
Stories found:   <story_count>
Artifacts:       <list of files scanned>
```

Ask: "Does this look correct? Should I proceed with **[format]** extraction? [Y/n]"

- If the user says no or specifies a different format, ask: "Which format should I use?
  Options: bmad, linear, jira, markdown"
  Then re-run `detect()` with `format_hint=<chosen_format>` if the importer supports it,
  or pass `format_override=<chosen_format>` to `extract()`.
- If the user confirms, proceed to Step 2.

---

### Step 2: Extraction

Run the extractor:

```python
from claw_forge.importer import extract

spec = extract(result)
print(spec)
```

Show a summary table:

```
| Epic                    | Stories |
|-------------------------|---------|
| Authentication          |       3 |
| Task Management         |       5 |
| ...                     |     ... |

Total: <N> stories across <M> epics
Tech stack: <tech_stack if found, else "not detected">
```

If `story_count == 0`, stop and tell the user:
"No features found — please check your export path and try again.
Common causes: wrong directory, unsupported export format, or empty export."

Otherwise, proceed to Step 3.

---

### Step 3: Section-by-Section Conversion

Convert the extracted spec to claw-forge XML format section by section. For each group,
generate the XML content using the extracted data, show it to the user, and ask for approval
before moving on.

Use this approval prompt pattern:
"Approve this section? [approve / edit / skip]"

- **approve**: accept as-is and move to the next section
- **edit**: ask the user what to change, revise the section, show it again
- **skip**: use the section as-is without review (treat same as approve)

Repeat edit cycles until the user approves or skips.

#### Section Group A: Overview + Tech Stack

Generate and show:

```xml
<overview>
  ...
</overview>

<technology_stack>
  <frontend>...</frontend>
  <backend>...</backend>
  <database>...</database>
  <communication>...</communication>
  <infrastructure>...</infrastructure>
</technology_stack>
```

Derive `<overview>` from the project name and any description found in the export.
Derive `<technology_stack>` from detected stack fields, or mark as "To be determined" if absent.

Ask: "Does this look right? [approve/edit/skip]"

---

#### Section Group B: Core Features (one epic at a time)

For each epic in the extracted spec, generate a `<category>` block and show it:

```xml
<category name="Authentication">
  - User can register with email and password (returns 201 with user_id)
  - User can log in and receive a JWT access_token (returns 200)
  - ...
</category>
```

Ask: "Approve this category (**[epic name]**, [N] stories)? [approve/edit/skip]"

Process all epics one by one. Collect all approved/skipped `<category>` blocks into
the final `<core_features>` section.

---

#### Section Group C: Database Schema + API Endpoints

Generate and show:

```xml
<database_schema>
  <tables>
    <table name="users">
      <column>id UUID PRIMARY KEY DEFAULT gen_random_uuid()</column>
      <column>email VARCHAR(255) UNIQUE NOT NULL</column>
      ...
    </table>
    ...
  </tables>
</database_schema>

<api_endpoints_summary>
  <domain name="Authentication">
    POST   /api/auth/register   - Register new user account
    POST   /api/auth/login      - Log in and receive JWT tokens
    ...
  </domain>
  ...
</api_endpoints_summary>
```

Derive tables and endpoints from the stories and detected schema in the export.
If the export does not include schema information, infer reasonable defaults from the epics.

Ask: "Approve these sections (Database Schema + API Endpoints)? [approve/edit/skip]"

---

#### Section Group D: Implementation Steps + Success Criteria

Generate and show:

```xml
<implementation_steps>
  <phase name="Phase 1: Foundation">
    Set up project structure and tooling
    Implement core data models
    ...
  </phase>
  <phase name="Phase 2: Core Features">
    ...
  </phase>
</implementation_steps>

<success_criteria>
  <functionality>
    - All features implemented and covered by tests
    ...
  </functionality>
  <ux>
    - ...
  </ux>
  <technical_quality>
    - ...
  </technical_quality>
</success_criteria>
```

Group phases by epic or natural progression. Derive success criteria from the stories.

Ask: "Approve these sections (Implementation Steps + Success Criteria)? [approve/edit/skip]"

---

### Step 4: Write the Spec File

After all sections are approved:

1. Detect greenfield vs brownfield:

```bash
test -f brownfield_manifest.json && echo "BROWNFIELD" || echo "GREENFIELD"
```

2. Choose the output filename:
   - Greenfield → `app_spec.txt`
   - Brownfield → `additions_spec.xml`

3. Assemble the full XML document from all approved sections:

```xml
<project_specification>
  <project_name>...</project_name>
  <overview>...</overview>
  <technology_stack>...</technology_stack>
  <core_features>
    <category name="...">...</category>
    ...
  </core_features>
  <database_schema>...</database_schema>
  <api_endpoints_summary>...</api_endpoints_summary>
  <implementation_steps>...</implementation_steps>
  <success_criteria>...</success_criteria>
</project_specification>
```

4. Write the file to the project root (or `--project` path if specified).

5. Confirm to the user:

```
Written: <filename>

Summary:
  Stories:    <N> across <M> categories
  DB tables:  <T>
  Endpoints:  <E>
  Phases:     <P>
```

---

### Step 5: Next Steps

After writing the file, suggest:

```
Next steps:
  1. Review <filename> and adjust any sections manually
  2. claw-forge validate-spec <filename>
     Issues? Run /fix-spec, then re-run validate-spec until clean
  3. claw-forge plan <filename>
  4. claw-forge run --concurrency 5
```

---

## Options

- `--model <model-id>` — override the Claude model used for section generation
- `--project <path>` — write the output spec to this directory instead of cwd
- If neither is provided, defaults apply (current model, current directory)

## Notes

- The converter uses one Claude call per section group to avoid context truncation
- If an export is very large (100+ epics), offer to batch epics in groups of 10
- Preserve original story text as-is in bullets where it is already action-verb formatted;
  rewrite only vague or passive-voice stories
- Use `&amp;` for `&` in XML content
