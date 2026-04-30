# Spec-Time Overlap Analysis (`/create-spec` Phase 3.5)

**Author:** Bowen Li (with Claude Opus 4.7)
**Date:** 2026-04-30
**Status:** Design — pending review

## Motivation

Today, `/create-spec` produces feature bullets with no awareness of which features will compete for the same code. The runtime DAG scheduler (`claw_forge/state/scheduler.py`) honors `depends_on` edges, but it has nothing to schedule — `/create-spec` only emits ordering through implementation **phases** (sequential groups), not pairwise edges.

Result: every feature in a phase runs in parallel. When two features both modify the CLI argument parser, they conflict, the squash merge fails, and one branch is stranded for manual resolution. The merge pipeline (v0.5.24, v0.5.26, v0.5.27) now reports those conflicts honestly, but the conflict itself is preventable upstream.

This design adds a single new step to `/create-spec` that asks the LLM to flag pairs of features that will touch the same code surface, and lets the user serialize them by adding `depends_on` edges to the emitted XML.

## Architecture

```
/create-spec workflow:
  Phase 1   Project Identity
  Phase 2   Quick / Detailed
  Phase 3   Core Features  → 100-300 bullets
  Phase 3.5 Overlap Analysis  ← NEW
  Phase 4   Technical Details (Detailed mode)
  Phase 5   Generate XML
  Phase 6   Next Steps
```

Phase 3.5 runs after Phase 3's bullets are confirmed, before Phase 4's tech-stack questions. It only operates on the bullet list; no other state is needed.

## Phase 3.5 walkthrough

### Step 1 — Detect overlap (LLM)

The slash-command runtime (Claude itself, executing `/create-spec`) feeds the bullet list into a self-contained analysis prompt:

> Below are N feature bullets. Find pairs that will modify the same logical code surface (same file, same function, same module-level concern). For each pair, return:
> - Feature indices (matching the original numbering)
> - The shared surface (file or concept)
> - One-sentence rationale
>
> A pair is "overlapping" only if changing one without the other would force a merge conflict on the same hunk. Do not flag features that simply belong to the same category but write to different files.
>
> Return JSON: `[{"a": 14, "b": 18, "surface": "cli/main.py", "rationale": "..."}]`. Empty list `[]` if no overlaps.

The output is a list of pairwise overlaps.

### Step 2 — Present and resolve (interactive)

For each pair the LLM flagged, prompt the user:

```
Overlap detected:
  #14  System displays parse errors on stderr
  #18  System displays side-by-side diff in terminal
  Shared surface: cli/main.py (display layer)
  Rationale: Both add output paths through the same render function.

Resolution? [s] serialize (#18 depends on #14)  [k] keep parallel  [q] quit
> _
```

- `s` adds `depends_on` from the second feature to the first (the order is determined by feature index — earlier-numbered feature runs first).
- `k` records that the user explicitly accepted the overlap; that pair is not asked about again on retry.
- `q` aborts the spec generation (escape hatch for users who realize their feature list needs more work).

`m` (merge into one feature) is **out of scope for v1** — see "Out of scope" below.

### Step 3 — Persist edges

Edges are recorded against feature indices in memory. When Phase 5 emits the XML, each `<feature>` that received an `s` decision gets a `depends_on="<index>"` attribute (or `depends_on="14,15"` for multiple).

## Output format

The existing `<core_features>` schema becomes:

```xml
<core_features>
  <category name="DSL Compiler">
    <feature index="14">System displays parse errors on stderr</feature>
    <feature index="18" depends_on="14">System displays side-by-side diff in terminal</feature>
  </category>
</core_features>
```

`<feature>` is a new element wrapper. Bullets without explicit indices/edges fall back to the legacy plain-text bullet form for backwards compatibility:

```xml
<category name="Receipts">
  - User can upload a receipt image
  - User can list receipts
</category>
```

Both forms are accepted by the parser.

## Parser changes (`claw_forge/spec/parser.py`)

`FeatureItem.depends_on_indices: list[int]` already exists. Two changes:

1. When the parser encounters `<feature index="N" depends_on="M,O,P">`, populate `depends_on_indices` with `[M, O, P]`.
2. Map `depends_on_indices` (1-based feature numbers) onto the runtime `TaskNode.depends_on` (string IDs) when the spec is loaded into the state service. The `index` → task ID mapping is built at load time from the feature emission order.

The runtime scheduler is unchanged — it already does the right thing once `depends_on` is populated.

## Slash-command changes (`.claude/commands/create-spec.md`)

Insert a new section between the existing "Phase 3" and "Phase 4" headings titled "Phase 3.5 — Overlap Analysis," containing the prompt template and the interactive resolution loop. The section reuses the existing markdown-driven instructions style (no new Python harness needed; the slash command is interpreted by Claude inline).

## Error handling

| Situation | Handling |
|---|---|
| LLM returns malformed JSON | Re-prompt once with the schema; if still malformed, skip Phase 3.5 with a warning ("could not analyze overlaps; emitting spec with no edges") |
| LLM returns empty list | Skip directly to Phase 4 with a one-line confirmation |
| User picks `q` | Abort `/create-spec` cleanly; no files written |
| User has 0 features (Phase 3 produced nothing) | Skip Phase 3.5; downstream "no features" check handles the rest |
| Conflicting `depends_on` resolutions (cycle) | Detected by the existing `Scheduler.validate_no_cycles()` at runtime; `claw-forge plan` will surface the cycle before the user runs |

## Testing

- **Unit (parser):** `<feature index="N" depends_on="M">` correctly populates `FeatureItem.depends_on_indices`. Mixed legacy bullets + new `<feature>` elements coexist in the same `<category>`.
- **Unit (load):** Loading a spec with feature-index edges into the state service produces `TaskNode.depends_on` strings that match the actual created task IDs.
- **Integration:** A small fixture spec with one declared overlap gets emitted with the correct `depends_on` attribute; running `claw-forge plan` on it produces two waves (the dependent feature in wave 2).
- **Manual:** Run `/create-spec` end-to-end with 5-10 sample bullets that have a known overlap; confirm the prompt fires, the user resolution flows, and the emitted XML is valid.

## Out of scope (defer to v2 or never)

- **Auto-merge of overlapping features.** Always ask the user. Merging two bullets into one is a content rewrite, harder to undo, and easier to get wrong than a serialization edge.
- **3+ way overlaps.** v1 reports them as multiple pairwise overlaps; user resolves each. A future version could detect strongly-connected groups and propose batched serialization.
- **Cross-spec edges.** Brownfield specs that depend on greenfield-baseline features. Out of scope; those projects have other coordination problems.
- **Hotspot analysis of the *target* codebase.** That's sub-project 2 (`claw-forge boundaries`).

## Future work

Once Phase 3.5 has run on enough specs, mine the user's `[k] keep parallel` decisions for false-positive patterns the LLM keeps flagging unnecessarily, and tune the analysis prompt to suppress them. Anonymized aggregation only; no per-spec feedback.

## Acceptance criteria

1. `/create-spec` runs Phase 3.5 between Phase 3 and Phase 4 for any user with ≥ 2 features
2. Pairwise overlaps surfaced by the LLM are presented to the user with `s/k/q` options
3. `s` decisions emit valid XML containing `depends_on` attributes; legacy specs without `<feature>` elements still parse
4. The state service loads the spec and `Scheduler.get_execution_order()` places dependent features in later waves
5. End-to-end: a contrived spec with two overlapping CLI features, after Phase 3.5 with `s`, produces a `claw-forge run` execution order that runs them serially with no manual intervention
