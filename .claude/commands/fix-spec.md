# Fix Spec Issues

Run `claw-forge validate-spec` on the project spec, then iteratively fix all reported issues
— errors **and** warnings — until the spec is fully clean. Rewrites only the offending bullets;
never restructures the spec.

## Step 1: Find the spec file

Look for the spec in the current directory:

```bash
ls app_spec.txt app_spec.xml additions_spec.xml 2>/dev/null | head -1
```

If multiple exist, prefer `app_spec.txt`, then `app_spec.xml`, then `additions_spec.xml`.
If none found, ask the user: "Which spec file should I fix?"

## Step 2: Run validate-spec

```bash
claw-forge validate-spec <spec-file> 2>&1
VALIDATE_EXIT=$?
```

Capture the full output. Count errors **and** warnings from the output.

If the output shows 0 errors and 0 warnings, report:
```
✅ <spec-file> is fully clean — nothing to fix.
```
and stop.

If the output shows only warnings (exit 0 but warnings present), continue — warnings are
quality issues worth fixing even though they don't block `claw-forge plan`.

## Step 3: Parse the issues

From the validator output, extract every reported issue. For each one note:
- **Severity** (ERROR `✗` or WARNING `⚠`)
- **Layer** (1 = structural, 2 = LLM eval, 3 = coverage gap)
- **Category** (e.g. `task-management`, `auth`)
- **Message** (what's wrong)
- **Suggestion** (the → line, if present)
- **Bullet** (the exact quoted bullet text, if present)

Fix errors first (they block planning), then warnings.

## Step 4: Fix the issues

Read the spec file. For each issue, rewrite only the affected bullet(s) using the rules below.
Do not reorder bullets, add new categories, or remove bullets that weren't flagged.

### Layer 1 fixes

| Issue type | Severity | Rule |
|---|---|---|
| Compound bullet (`contains "and"`) | ERROR | Split into two separate bullets on consecutive lines |
| Vague / no measurable outcome | WARNING | Add a concrete, testable outcome (status code, field name, count) |
| Not starting with action verb | WARNING | Rewrite to start with: User can / System / API / Admin |
| Too long (> ~25 words) | WARNING | Trim to the essential behaviour; move detail to a parenthetical |

**Examples:**

```
# BEFORE (compound — ERROR):
- User can create and edit a task

# AFTER (split):
- User can create a task with title, description, due_date, and priority (returns 201 with task_id)
- User can edit a task's title, description, due_date, or priority (returns 200 with updated fields)
```

```
# BEFORE (vague — WARNING):
- Handle errors appropriately

# AFTER:
- API returns 422 with a field-level errors array when request validation fails
```

```
# BEFORE (no verb — WARNING):
- Password reset link in email

# AFTER:
- System sends a password reset link to the user's email (link expires after 1 hour)
```

### Layer 2 fixes (LLM eval — low score on a dimension)

The LLM scored a category below the threshold. The message names the dimension and category.
Read all bullets in that category and apply targeted rewrites:

| Dimension | What to improve |
|---|---|
| Testability | Add observable outcomes: HTTP status, response fields, DB state, UI element |
| Atomicity | Each bullet = one action; split any that describe more than one |
| Specificity | Replace vague words (appropriate, correct, valid) with exact values |
| Error coverage | Add bullets for the main failure cases (invalid input, not found, unauthorized) |

Re-read the full category after rewrites to confirm it now clearly covers all four dimensions.

### Layer 3 fixes (coverage gaps)

A table, column, endpoint, or auth flow exists in the spec metadata but has no corresponding
bullet. Add the missing bullet(s) in the most relevant category:

```
# Gap: table "notifications" has no bullets
# Add to Notifications category:
- System creates a notification record when a task is assigned to a user
- User can list their notifications (paginated, 20 per page, newest first)
- User can mark a notification as read (sets read_at timestamp)
```

## Step 5: Write the fixed spec

Write the full corrected spec back to the same file. Preserve:
- All XML structure (tags, attributes, whitespace between sections)
- All non-flagged bullets verbatim
- Category order and names

## Step 6: Re-run validate-spec

```bash
claw-forge validate-spec <spec-file> 2>&1
```

Count errors and warnings in the output.

If both are zero: report success (see output format below).

If issues remain: go back to Step 4 for another pass. Repeat up to **3 times total**.

If issues still remain after 3 passes, list them and ask the user:
"These issues may require domain knowledge to resolve — should I attempt another pass,
or would you like to fix them manually?"

## Output format

On success:
```
✅ Spec fixed: <spec-file>

  Pass 1: 6 issues (3 errors, 3 warnings) → 2 remaining
  Pass 2: 2 issues (0 errors, 2 warnings) → 0 remaining

  Fixed:
    ✗ [task-management] Split compound bullet "User can create and edit a task"
    ✗ [auth] Rewrote compound bullet "User can register and then login"
    ✗ [api] Added action verb to "Error responses from the API"
    ⚠ [auth] Added measurable outcome to "Handle errors appropriately"
    ⚠ [notifications] Added 3 bullets for uncovered "notifications" table
    ⚠ [auth] Rewrote vague bullet "Password reset link in email"

Next: claw-forge plan <spec-file>
```

On partial fix (issues remain after 3 passes):
```
⚠ 2 issues remain after 3 fix passes:

  ⚠ [auth] Score 6.5 on Specificity — some bullets still use vague language
    → Consider adding exact field names, status codes, or error messages

  ⚠ [notifications] Coverage gap: endpoint POST /api/notifications/bulk-read
    → Add: "User can mark multiple notifications as read in one request (accepts array of ids)"

Fix these manually in <spec-file>, then re-run: claw-forge validate-spec <spec-file>
```
