# Create Project Spec (XML)

Generate an AutoForge-compatible XML project specification for claw-forge. This produces 100-300+
granular feature bullets that become individual agent tasks.

Supports two modes:
- **Greenfield**: building a new project from scratch → produces `app_spec.txt`
- **Brownfield**: adding features to an existing project → produces `additions_spec.xml`

---

## Auto-Detect Mode

**First**: check if `brownfield_manifest.json` exists in the current working directory.

```bash
test -f brownfield_manifest.json && echo "BROWNFIELD" || echo "GREENFIELD"
```

- If it exists → run the **Brownfield Flow** below
- If it does not exist → run the **Greenfield Flow** below

---

## Brownfield Flow

> Use when adding features to an existing codebase.

### Step 1: Load manifest

Read `brownfield_manifest.json` and extract:
- `stack` (language, framework, database)
- `test_baseline` (N tests, X% coverage)
- `conventions` (naming style, patterns, etc.)

These will be auto-populated into `<existing_context>`.

### Step 2: Gather addition details

Ask the user (one at a time):

1. **What are you adding?** Give it a name and one-sentence summary.
   - Example: "Stripe payments — let users subscribe to Pro plan via Stripe Checkout"

2. **Which parts of the existing code does it touch?**
   - Models, routers, services, background jobs, tests, etc.
   - Example: "Extends User model, adds /payments router, new StripeService class"

3. **What must NOT change?** List any constraints.
   - Example: "Must not modify auth flow. All 47 existing tests must stay green."

4. **List the features to add in plain English** (one per line, action-verb format):
   - Example: "User can add a payment method via Stripe Elements"
   - Aim for 10–50 features for a medium addition.

5. **Break them into implementation phases** (optional — offer to auto-group):
   - Example: Phase 1: Stripe integration / Phase 2: Subscription UI / Phase 3: Webhooks

### Step 3: Generate `additions_spec.xml`

Use the brownfield template (`skills/app_spec.brownfield.template.xml`) and fill in:
- `<project_name>` from the addition name
- `<addition_summary>` from the summary
- `<existing_context>` from `brownfield_manifest.json` (manifest values win)
- `<features_to_add>` from the feature list
- `<integration_points>` from the code-touch areas
- `<constraints>` from the "must not change" list
- `<implementation_steps>` from the phases

Write the file as `additions_spec.xml` in the project root.

### Step 4: Show next steps

```
✅ Brownfield spec created: additions_spec.xml

📊 Summary:
  Features to add: <N>
  Phases: <K>
  Integration points: <M>
  Constraints: <C>

Next steps:
  1. Review additions_spec.xml — add/remove features as needed
  2. Run: claw-forge add --spec additions_spec.xml

💡 Tip: Be specific about constraints — agents will treat them as hard rules.
   "All existing tests must stay green" = agents run tests before committing.
```

### Example: Brownfield spec for Stripe payments

```xml
<project_specification mode="brownfield">
  <project_name>MyApp — Stripe Payments</project_name>
  <addition_summary>
    Add Stripe Checkout integration so users can subscribe to the Pro plan.
    Handles subscription lifecycle, webhooks, and billing portal access.
  </addition_summary>
  <existing_context>
    <stack>Python / FastAPI / PostgreSQL</stack>
    <test_baseline>47 tests passing, 87% coverage</test_baseline>
    <conventions>snake_case, async handlers, pydantic v2 models</conventions>
  </existing_context>
  <features_to_add>
    - User can add a payment method via Stripe Elements
    - User can subscribe to Pro plan via Stripe Checkout
    - System creates Stripe customer on first payment attempt
    - Webhook handler processes subscription.created events
    - User can access billing portal to manage subscription
  </features_to_add>
  <integration_points>
    Extends User model with stripe_customer_id field
    Adds /payments router alongside existing /auth and /projects routers
    New StripeService class in services/stripe_service.py
  </integration_points>
  <constraints>
    Must not modify existing auth flow
    All 47 existing tests must stay green
    Follow existing async handler pattern in routers/
  </constraints>
  <implementation_steps>
    <phase name="Stripe Integration">
      User can add a payment method via Stripe Elements
      System creates Stripe customer on first payment attempt
    </phase>
    <phase name="Subscription Flow">
      User can subscribe to Pro plan via Stripe Checkout
      Webhook handler processes subscription.created events
      User can access billing portal to manage subscription
    </phase>
  </implementation_steps>
  <success_criteria>
    All new features implemented and tested
    Existing test suite still 100% green
    Coverage maintained above 87%
  </success_criteria>
</project_specification>
```

---

## Greenfield Flow

> Use when building a new project from scratch.

### Phase 1: Project Identity

Ask the user (one at a time, conversationally):

1. **What are you building?** Get the project name and a 2-3 sentence description.
2. **Who is it for?** Target audience / users.
3. **What problem does it solve?** The core value proposition.

Summarize back: "So we're building **X** — a tool that helps **Y** by **Z**. Sound right?"

---

### Phase 2: Quick vs Detailed

Ask the user:

> **How detailed do you want to go?**
>
> - **Quick** (5 min): I'll derive the tech stack, database schema, and API from your features.
>   Good for MVPs.
> - **Detailed** (15 min): We'll go through tech stack, database design, API structure, and UI
>   layout together. Better for production apps.

Wait for their choice.

---

### Phase 3: Core Features (Conversational)

This is the most important phase. Ask the user to describe their app's main functionality in
natural language. Guide them through categories:

> **Let's map out what your app does.** Describe the main things a user can do — I'll turn each
> one into specific, testable feature bullets.
>
> Let's start with: **What happens when a user first opens your app?**
> (Registration, onboarding, landing page?)

After each response, derive granular bullets and confirm:

```
From what you described, I'm generating these features:

**Authentication & User Management (5 bullets)**  →  XML: <category name="Authentication &amp; User Management">
- User can register with email and password (returns 201 with user_id)
- User can login and receive JWT access_token and refresh_token
- ...

Does this capture it? Anything to add or change?
```

The heading name in bold becomes the `name` attribute of `<category name="...">` in `<core_features>`.
Keep a note of each confirmed heading — you will use them verbatim as `name` attributes in Phase 5.

Continue through categories:
- **Authentication & user management**
- **Core functionality** (the main thing the app does)
- **Data management** (CRUD, search, filtering, pagination)
- **UI/UX** (responsive design, loading states, error handling, notifications)
- **API layer** (validation, error responses, pagination format)
- **Admin features** (if applicable)
- **Integrations** (third-party services, webhooks, notifications)

**Target: 100-300 bullets total.** Each bullet should be a testable behavior starting with an
action verb:
- "User can..." / "System returns..." / "API validates..." / "UI displays..."

---

### Phase 4: Technical Details (Detailed mode only)

If the user chose **Detailed**, ask about:

1. **Tech stack preferences:**
   - Frontend: React/Vue/Svelte/Next.js? Styling: Tailwind/CSS modules?
   - Backend: Python (FastAPI/Django) / Node (Express/Fastify) / Go / Rust?
   - Database: SQLite/PostgreSQL/MySQL/MongoDB?

2. **Database schema:** Walk through the main tables/collections based on the features.

3. **API structure:** REST vs GraphQL? Authentication method (JWT, session, OAuth)?

4. **UI layout:** Dashboard style? Sidebar navigation? Single page or multi-page?

For **Quick** mode, derive sensible defaults from the features (React + Vite, FastAPI,
SQLite for dev / PostgreSQL for prod, JWT auth, REST API).

---

### Phase 5: Generate the Spec

Generate two files:

#### `app_spec.txt` (XML format)

Use the template structure from `claw_forge/spec/app_spec.template.xml` but filled with the
user's project details. The XML must include:

- `<project_specification>` root element
- `<project_name>`, `<overview>`
- `<technology_stack>` with frontend/backend/communication
- `<prerequisites>` with environment setup
- `<core_features>` with categorized bullet lists (this is the bulk — 100-300 bullets)
- `<database_schema>` with `<tables>` containing column definitions
- `<api_endpoints_summary>` categorized by domain
- `<ui_layout>` with main structure
- `<design_system>` with color palette, typography, animations
- `<key_interactions>` with numbered user flows
- `<implementation_steps>` with 4-6 phased steps
- `<success_criteria>` with functionality, UX, and technical quality

**Important:** Use `&amp;` for `&` in XML content. Each bullet in `<core_features>` becomes one
agent task.

**CRITICAL — `<core_features>` category format:**
Each category group inside `<core_features>` MUST use `<category name="...">` with a
**descriptive human-readable name**. The `name` attribute becomes the task category shown in
the Kanban board and used for routing and filtering.

✅ Correct — use `<category name="...">` with readable names (spaces and `&amp;` allowed):
```xml
<core_features>
  <category name="Authentication &amp; User Management">...</category>
  <category name="Receipt Scanning">...</category>
  <category name="Payment Processing">...</category>
  <category name="Notifications">...</category>
</core_features>
```

❌ Wrong — never use bare snake_case element names:
```xml
<core_features>
  <authentication>...</authentication>     <!-- BAD: old format, no spaces allowed -->
  <receipt_scanning>...</receipt_scanning> <!-- BAD: renders as "Receipt_scanning" -->
</core_features>
```

❌ Also wrong — never use the generic `<category>` tag without a name attribute:
```xml
<core_features>
  <category>...</category>  <!-- BAD: becomes "Category" for every task -->
</core_features>
```

Derive the name from the feature group heading you used in Phase 3. The name can contain
spaces, ampersands (`&amp;`), slashes, and any readable characters.

#### `claw-forge.yaml`

```yaml
project:
  name: <project-name>
  path: .

providers:
  - name: claude-oauth
    type: oauth
    enabled: true
    priority: 10

orchestrator:
  max_concurrent: 5
  retry_attempts: 3
  retry_delay_seconds: 5

features:
  # Generated by: claw-forge plan app_spec.txt
```

Show both files to the user and ask: "Does this look right? I'll write these files now."

Then write:
```bash
# Write app_spec.txt to project root
# Write claw-forge.yaml to project root
```

---

### Phase 6: Next Steps

After writing files, show:

```
✅ Project spec created!

📊 Summary:
  Features: <N> across <M> categories
  Phases: <K> implementation steps
  Tables: <T> database tables
  Endpoints: <E> API endpoints

Next steps:
  1. Review app_spec.txt — add/remove features as needed
  2. Run: claw-forge plan app_spec.txt
  3. Run: claw-forge run --concurrency 5

💡 Tip: Each feature bullet = one agent task. More specific bullets = better agent output.
   Aim for 100-300 bullets for a full application.
```
