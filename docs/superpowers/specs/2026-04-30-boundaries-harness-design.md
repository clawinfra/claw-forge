# `claw-forge boundaries` — Plugin-Boundary Refactoring Harness

**Author:** Bowen Li (with Claude Opus 4.7)
**Date:** 2026-04-30
**Status:** Design — pending review

## Motivation

Concurrent agent runs conflict because multiple feature tasks need to modify the same logical surface — usually a CLI dispatcher, a router, a parser, or a similar central choke point. Spec-time overlap analysis (sub-project 1) prevents *known* overlaps via `depends_on` edges, but it doesn't fix the structural cause: the *target codebase* lacks extension points, so every new feature is forced to edit the same shared file.

`claw-forge boundaries` retrofits plugin boundaries into the target codebase. After it runs, features become "drop a new file in `plugins/`" instead of "edit `cli.py`'s if-chain." The scheduler can then parallelize them with no overlap risk by construction.

This is a one-shot, mostly-idempotent refactor — not part of every `claw-forge run`. Users invoke it explicitly when they identify (or `boundaries audit` identifies) a hotspot.

## Architecture

```
claw-forge boundaries
├── audit              read-only; emit boundaries_report.md
└── apply              modifies repo; serial subagent loop with test gating
    ├── --hotspot=NAME    apply only one named hotspot from the audit
    ├── --auto            no interactive confirmation; apply all hotspots
    └── (default)         interactive; user confirms each hotspot
```

Two phases. Audit is always safe and read-only. Apply is gated by tests and runs each refactor on its own feature branch with squash-merge on success or revert on failure.

## Phase A — Audit

### Inputs

- `project_dir` (defaults to CWD)
- Optional config (`claw-forge.yaml` → `boundaries: { ignore_paths: [...], min_hotspot_score: N }`)

### Pipeline

1. **Walk the codebase** under `project_dir`, respecting `.gitignore` and `boundaries.ignore_paths`. Index every source file with: line count, top-level function count, top-level branch count (`if/elif/else` chains and `match/case` blocks at module scope).
2. **Compute hotspot signals** per file:
   - `dispatch_score` — count of long `if cmd == 'X':` / `elif name == 'Y':` chains and `dict[str, callable]` lookups (suggests a built-in dispatcher pattern that should be a registry)
   - `import_centrality` — number of other source files that import this file (incoming references = high blast radius for any change here)
   - `recent_churn` — number of distinct branches that touched this file in the last 90 days of `git log` (proxy for "every feature edits this")
   - `function_centrality` — for each top-level function, count call sites across the codebase
3. **Score and rank** files. Composite score = weighted sum (defaults: dispatch 0.4, churn 0.3, centrality 0.2, function 0.1). Threshold above which a file is a "hotspot" is configurable.
4. **Classify the hotspot pattern** for each flagged file using a coding-subagent (claude-agent-sdk `query()`):
   - `if-chain dispatcher` → "extract plugin registry"
   - `mega-file with N domains` → "split by domain"
   - `god-class with mixed responsibilities` → "extract collaborators"
   - `parser/router with hardcoded routes` → "introduce route registry"
   - The subagent reads the top of the file and the surrounding tests to make this call
5. **Emit `boundaries_report.md`** in the project root with one section per hotspot: file path, score, signals, proposed pattern, estimated reduction in cross-task conflicts (qualitative).

The audit subagent is **read-only**. It uses the SDK's `can_use_tool` to deny all `Write`/`Edit`/`Bash` write-side calls. Output is the report file only, written by the parent process from the subagent's structured response.

### Output sketch

```markdown
# Boundaries Audit — myapp/

3 hotspots identified. Refactoring these would convert most concurrent feature
tasks from "edit shared file" to "drop new plugin file" — drastically lower
conflict surface.

## 1. cli/main.py  (score 8.7)
- 412 LOC, 23 top-level if/elif branches dispatching on `args.cmd`
- 14 commits across 9 distinct branches in the last 90 days
- Imported by 6 other modules

**Proposed pattern:** Plugin registry
**Refactor sketch:**
- Extract each `args.cmd == 'foo': do_foo()` branch into `cli/commands/foo.py`
- Add `cli/commands/__init__.py` with auto-discovery
- `main.py` becomes argument parsing + registry dispatch only

After: features that add a new command drop one file under
`cli/commands/`. No two features edit the same file.

## 2. parser.py  (score 6.2)  ...
## 3. routes.py   (score 5.8)  ...
```

## Phase B — Apply

### Pipeline

1. **Load** `boundaries_report.md`. Filter to hotspots the user named (or all, in `--auto`).
2. **For each hotspot, in score order:**
   1. Confirm with user (skipped under `--auto`)
   2. Create a feature branch: `boundaries/<hotspot-slug>` (using existing `git/slug.py`)
   3. Spawn a coding subagent via claude-agent-sdk `query()`:
      - Prompt: hotspot's report section + "convert this file to the proposed pattern. Preserve all behavior. Do not change tests. After your changes, the project's existing test suite must pass."
      - The subagent has `Edit`/`Write`/`Read` for files inside `project_dir`, sandboxed via the existing `make_can_use_tool` permission callback
      - `Bash` is allowed only for the test command configured in `claw-forge.yaml` (e.g., `pytest`, `npm test`); everything else is denied
   4. Run the project's test command (from `claw-forge.yaml` → `boundaries.test_command`, defaulting to a sensible per-language guess)
   5. **Test green** → squash-merge the branch to `main` with a `boundaries(<file>): extract <pattern>` commit message; remove the worktree
   6. **Test red** → roll back: `git reset --hard <pre-refactor-sha>`, delete the branch and worktree, mark hotspot as failed in the report
3. **Emit summary**: `N applied, M skipped, K failed` with per-hotspot detail.

### Why each hotspot is its own subagent

Refactoring `cli.py` to a registry might require ~30 file edits and ~5 new files. That's a single semantic operation but a lot of mechanical changes — exactly the kind of thing a coding subagent does well in one focused session. Putting them in separate sessions per hotspot keeps each agent's context bounded and lets a failure on hotspot 2 not poison hotspot 1's success.

### Why serial, not concurrent

Refactor B might depend on refactor A's output (e.g., extracting a `commands/` directory in cli.py first, then introducing a route registry that uses it). Concurrent execution would race on the same files. Serial execution is the right primitive.

### Resume / retry

If `apply` is interrupted (Ctrl-C, crash), the in-flight feature branch is preserved (existing claw-forge worktree behavior). Re-running `apply` skips already-completed hotspots (detected by checking whether the proposed file structure already matches) and resumes at the next pending one.

## CLI surface

```bash
claw-forge boundaries audit
  # Read-only. Writes boundaries_report.md in project root.

claw-forge boundaries apply
  # Interactive. Prompts before each hotspot.

claw-forge boundaries apply --hotspot cli/main.py
  # Apply only one named hotspot.

claw-forge boundaries apply --auto
  # No prompts. Apply all hotspots in score order.

claw-forge boundaries status
  # Show the last audit's hotspots and which have been applied.
```

## Module layout

```
claw_forge/boundaries/
├── __init__.py
├── audit.py           # walks code, computes signals, ranks hotspots
├── classifier.py      # subagent wrapper that classifies hotspot patterns
├── report.py          # emits/parses boundaries_report.md
├── apply.py           # the per-hotspot refactor loop
└── refactor_agent.py  # subagent prompt + can_use_tool wiring
tests/boundaries/
├── test_audit.py
├── test_report.py
└── test_apply.py      # end-to-end on a synthetic if-chain → registry refactor
```

`cli.py` adds: `app.add_typer(boundaries_app, name="boundaries")`. The Typer subapp registers `audit`, `apply`, `status`.

## Configuration (`claw-forge.yaml`)

```yaml
boundaries:
  ignore_paths: [".venv", "node_modules", "ui/dist"]
  min_hotspot_score: 5.0
  test_command: "uv run pytest tests/ -q"   # auto-detected if omitted
  weights:
    dispatch: 0.4
    churn: 0.3
    centrality: 0.2
    function: 0.1
```

All keys optional; sensible defaults if missing.

## Error handling

| Situation | Handling |
|---|---|
| `boundaries audit` finds zero hotspots | Print "no hotspots found above threshold N"; exit 0 |
| `apply` started without prior `audit` | Run `audit` automatically and proceed |
| Subagent's refactor leaves the working tree dirty but tests pass | Treat as success; squash-merge captures the dirty state |
| Subagent fails to produce any edits (just thinking) | Mark hotspot as failed with "subagent produced no changes"; do not retry automatically |
| Test command not configured and not detected | Refuse to `apply`; emit instructions to set `boundaries.test_command` |
| Test command takes > N minutes (configurable, default 30 min) | Kill subprocess, mark as failed, revert |
| Squash-merge to main conflicts with unrelated work in progress | Existing claw-forge merge logic handles this — boundaries leverages the same `squash_merge()` |
| User aborts mid-`apply` (Ctrl-C) | Honor the SIGINT handlers already in `cli.py`; emergency-commit the current worktree; exit cleanly |

## Testing

- **Unit (audit):** Each signal scorer (dispatch, churn, centrality, function) tested against a synthetic mini-codebase fixture. Threshold/score composition correctness.
- **Unit (report):** Round-trip emission/parsing of `boundaries_report.md`; backward compatibility when new fields are added.
- **Integration (apply):** End-to-end on a synthetic project: a 200-line `cli.py` with a 10-branch if-chain. Run `apply --auto`, assert the resulting structure matches a golden file layout (one `commands/<name>.py` per branch, plus a registry), assert the synthetic test suite still passes after refactor.
- **Failure modes:** Test-failing refactor reverts cleanly; partial run can be resumed.
- **Manual:** Run on `agent-trading-arena` itself to dogfood — the CLI and parser hotspots there are the motivating use case.

## Security

- Audit is read-only and runs no subprocesses other than `git log` (for churn).
- Apply runs subprocesses only for the configured test command and `git` operations. The subagent's `can_use_tool` denies all other `Bash` invocations and restricts `Write`/`Edit`/`Read` to within `project_dir` (existing `permissions.py` plumbing).
- No network calls. No data leaves the machine.

## Out of scope

- **Cross-language refactoring.** v1 supports the languages claw-forge already detects via `brownfield_manifest.json` (Python, JS/TS, Rust, Go). Other languages get audit support but not apply (the subagent prompt is language-specific).
- **Multi-hotspot fusion.** Some refactors are best done together (e.g., extract registry + simultaneously extract command type system). v1 treats every hotspot independently; if combined refactoring is needed, the user runs `apply --hotspot=A` then `apply --hotspot=B` and the second one operates on A's post-refactor state.
- **Auto-suggestion in `/create-spec`.** When a brownfield spec targets a file with high churn/centrality, eventually `/create-spec` could prompt: "this file is a hotspot — run `claw-forge boundaries audit` first?" Out of scope for v1; revisit after the first round of audits has data.
- **Reverting an applied refactor.** Users can `git revert` the squash-merge commit by hand. v1 doesn't ship a `boundaries undo` command.
- **Refactoring the test files themselves.** Tests are sacred — the apply subagent is explicitly forbidden from editing files under common test paths (`tests/`, `__tests__/`, `*_test.go`, `spec/`).

## Acceptance criteria

1. `claw-forge boundaries audit` produces a `boundaries_report.md` listing hotspots sorted by score, with a proposed pattern per hotspot
2. `claw-forge boundaries apply` runs each hotspot's refactor in a feature branch with test gating; green merges, red reverts
3. After applying the first hotspot of `agent-trading-arena`'s `cli.py`, the resulting structure has one file per command under `cli/commands/` and the existing `agent-trading-arena` test suite stays green
4. A subsequent `claw-forge run` against the refactored codebase produces zero merge conflicts on tasks that previously conflicted (validated against the existing log of failed merges)
5. Re-running `audit` on the post-refactor codebase no longer flags the refactored files as hotspots
