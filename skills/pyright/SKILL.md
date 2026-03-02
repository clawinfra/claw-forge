# Python LSP — Pyright

## What this skill does
Runs static type checking on Python code and returns structured diagnostics the agent can act on.

## Installation check
```bash
pyright --version
```
If not installed:
```bash
uv tool install pyright
# or
npm install -g pyright
```

## Type checking / diagnostics
```bash
# Machine-readable JSON output (preferred for agent use)
pyright --outputjson path/to/file.py

# Human-readable, whole project
pyright --project .

# Single file, human-readable
pyright path/to/file.py
```
Output means:
- `error:` → must fix before committing
- `warning:` → review but non-blocking
- `note:` → informational

## Key flags
| Flag | Purpose |
|------|---------|
| `--outputjson` | Machine-readable JSON (use for agent parsing) |
| `--project .` | Use `pyrightconfig.json` in current dir |
| `--pythonversion 3.11` | Override Python version for type checking |
| `--stats` | Print summary stats (file count, error count) |
| `--ignoreexternal` | Skip type errors from third-party stubs |

## Config file
`pyrightconfig.json` — place in project root:
```json
{
  "typeCheckingMode": "standard",
  "pythonVersion": "3.11",
  "include": ["src"],
  "exclude": ["**/node_modules", "**/__pycache__"],
  "reportMissingImports": true,
  "reportMissingTypeStubs": false
}
```
Modes: `off` | `basic` | `standard` | `strict`

## Common errors and fixes
| Error | Cause | Fix |
|-------|-------|-----|
| `Import "X" could not be resolved` | Package not installed or wrong venv | `uv add X` or activate correct venv |
| `is not assignable to type` | Type mismatch | Fix annotation or add cast/narrowing |
| `possibly unbound` | Variable used before conditional assignment | Initialise variable before branch |
| `"X" is not a known attribute` | Typo or missing attribute | Check class definition, add attribute |
| `Return type "X" is incompatible` | Function return doesn't match annotation | Fix return value or update annotation |

## Integration with agent workflow
1. Run `pyright --outputjson .` after writing or modifying Python files.
2. Parse JSON: `result["generalDiagnostics"]` — each entry has `severity`, `message`, `file`, `range`.
3. Fix all `error` severity items before committing.
4. Re-run to confirm clean. `"errorCount": 0` in JSON summary = ready to commit.
