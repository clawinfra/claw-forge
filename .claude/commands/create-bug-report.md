---
description: Create a structured bug report for claw-forge fix --report
argument-hint: [brief bug description]
allowed-tools: [Read, Write, Bash]
---

# /create-bug-report

Guide the user through creating a structured bug_report.md, then run the fix.

## Flow

### Phase 1 — Title & symptoms
Ask: "What's broken? Describe the symptom in one sentence."
Ask: "Any other symptoms? (error messages, affected users, frequency)"

### Phase 2 — Reproduction
Ask: "What are the exact steps to reproduce this bug?"
Ask: "Does it happen every time, or intermittently?"

### Phase 3 — Expected vs actual
Ask: "What should happen instead?"

### Phase 4 — Scope & constraints
Check existing files: `ls src/ lib/ app/ 2>/dev/null | head -20` to suggest affected areas.
Ask: "Which files or modules do you suspect? (or 'unknown')"
Ask: "What must NOT change while fixing this? (e.g. API contract, auth flow)"

### Phase 5 — Generate bug_report.md
Write the file to the project root.
Show a summary of what was captured.

### Phase 6 — Run fix
Ask: "Ready to fix? (yes/no)"
If yes: run `claw-forge fix --report bug_report.md`
Show expected output.
