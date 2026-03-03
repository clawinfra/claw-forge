# Using claw-forge with BMAD Method

BMAD Method excels at structured planning — PRDs, architecture docs, epics, and stories with
human review at every gate. claw-forge excels at autonomous execution — taking a feature list
and building it in parallel with minimal hand-holding.

They complement each other well: **BMAD plans, claw-forge builds.**

---

## The Integration Pattern

```
BMAD Output                    →   claw-forge Input
─────────────────────────────────────────────────────
PRD (product requirements)     →   <overview> + <core_features>
Architecture doc               →   <technology_stack> + <database_schema>
Epic list                      →   Phase groupings in <implementation_steps>
Story acceptance criteria      →   Individual feature bullets
UX doc                         →   <ui_layout> + <design_system>
```

---

## Step-by-Step: BMAD Epics → app_spec

### 1. After BMAD planning is done

You have (in `_bmad-output/`):
- `prd.md` — product requirements + epics
- `architecture.md` — tech stack, data models, API design
- `stories/epic-1/story-1.md` … `story-N.md` — acceptance criteria

### 2. Map BMAD artifacts to spec sections

**From `prd.md`** → extract for `<overview>` and `<core_features>`:

```
BMAD story acceptance criteria:
  "Given a logged-in user, when they click 'New Project', 
   then a modal appears with name and description fields"

↓ becomes claw-forge feature bullet:

  User can create a new project by clicking 'New Project' button which opens a modal
  Modal contains name field (required, max 100 chars) and description field (optional)
  System saves project and redirects to project dashboard on submit
  System shows inline validation error if name is empty or too long
```

**From `architecture.md`** → extract for `<technology_stack>` and `<database_schema>`:

```
BMAD architecture:
  "PostgreSQL for persistence, FastAPI backend, React frontend, Redis for sessions"

↓ becomes:

<technology_stack>
  Backend: FastAPI (Python 3.11+)
  Frontend: React 18 + TypeScript + Vite
  Database: PostgreSQL 15
  Cache/Sessions: Redis 7
  Auth: JWT with refresh tokens
</technology_stack>
```

**From `stories/epic-N/story-M.md`** → each story maps to a phase in `<implementation_steps>`:

```
BMAD Epic 1: Authentication
  Story 1.1: User registration
  Story 1.2: Login/logout
  Story 1.3: Password reset

↓ becomes Phase 1 in <implementation_steps>:

<phase name="Authentication">
  User can register with email and password
  System validates email format and password strength (min 8 chars, 1 uppercase, 1 number)
  System sends verification email on registration
  User can log in with verified email and password
  System returns JWT access token (15min) and refresh token (7 days)
  User can log out, which invalidates the refresh token
  User can request password reset via email
  System sends reset link valid for 1 hour
  User can set new password using valid reset token
</phase>
```

### 3. Assemble the spec file

Create `app_spec.xml` (or `app_spec.txt` for plain format):

```xml
<project_specification>
  <project_name>Your Project Name</project_name>

  <overview>
    <!-- Paste your BMAD PRD executive summary here -->
  </overview>

  <technology_stack>
    <!-- From BMAD architecture.md -->
  </technology_stack>

  <database_schema>
    <!-- From BMAD architecture.md data models section -->
    Users table: id, email, password_hash, verified_at, created_at
    Projects table: id, owner_id, name, description, created_at
    Sessions table: id, user_id, refresh_token_hash, expires_at
  </database_schema>

  <api_endpoints_summary>
    <!-- From BMAD architecture.md API design section -->
    POST /auth/register — create account
    POST /auth/login — get tokens
    POST /auth/logout — invalidate refresh token
    POST /auth/refresh — get new access token
    POST /auth/reset-password — request reset
    PATCH /auth/reset-password/:token — apply reset
  </api_endpoints_summary>

  <core_features>
    <!-- One bullet per story acceptance criterion -->
    <!-- Group by epic for readability -->

    <!-- Epic 1: Authentication -->
    User can register with email and password
    System validates email format and password strength
    ...

    <!-- Epic 2: Projects -->
    User can create a new project with name and description
    ...
  </core_features>

  <ui_layout>
    <!-- From BMAD UX doc -->
  </ui_layout>

  <implementation_steps>
    <!-- One <phase> per BMAD epic, in dependency order -->
    <phase name="Authentication">...</phase>
    <phase name="Projects">...</phase>
    <phase name="Collaboration">...</phase>
  </implementation_steps>

  <success_criteria>
    <!-- From BMAD PRD success metrics -->
    All authentication flows work end-to-end
    API response time under 200ms at p95
    Test coverage above 90%
  </success_criteria>
</project_specification>
```

### 4. Initialize claw-forge

```bash
claw-forge plan app_spec.xml
claw-forge run
```

claw-forge reads the spec, creates features for each bullet (grouped by phase for dependency
ordering), and begins parallel agent execution.

---

## Converting Story Format

### BMAD story → feature bullets

BMAD stories use Gherkin-style acceptance criteria. Convert each `Given/When/Then` block to
plain action-verb sentences:

| BMAD (Gherkin) | claw-forge (feature bullet) |
|---|---|
| `Given user is logged in, When they visit /dashboard, Then they see their projects` | `Authenticated user sees their projects listed on the dashboard` |
| `Given a project exists, When user clicks Delete, Then system asks for confirmation` | `User sees a confirmation dialog before deleting a project` |
| `Given confirmation, When user clicks Confirm, Then project is soft-deleted` | `System soft-deletes the project and removes it from the dashboard list` |

**Rule of thumb**: 1 story ≈ 3–8 feature bullets. Each acceptance criterion becomes 1–2 bullets.

---

## When to Use Which Tool

| Situation | Recommendation |
|-----------|---------------|
| Greenfield, solo dev, no stakeholders | Skip BMAD — use `claw-forge /create-spec` directly |
| Team project, PM needs sign-off | BMAD for planning → claw-forge for execution |
| Client project, need formal PRD | BMAD all phases → export stories to claw-forge |
| Prototype / spike | claw-forge Quick Flow (plain English, no XML needed) |
| Regulated industry (security/compliance) | BMAD Enterprise → claw-forge with security phase first |
| Already have a BMAD PRD | Convert epics/stories using this guide → `claw-forge run` |

---

## Tips

**Keep feature bullets atomic** — each bullet should be implementable in one agent turn.
"User authentication system" is too broad. "User can log in with email and password, system
returns JWT" is right-sized.

**Phase order = dependency order** — claw-forge infers that Phase 2 features depend on Phase 1.
Mirror your BMAD epic order (foundation → features → polish).

**Don't duplicate BMAD's planning work** — if your architecture doc specifies PostgreSQL, put
it in `<technology_stack>`. Don't repeat it as feature bullets ("System uses PostgreSQL") —
that's implementation detail, not a feature.

**Story estimates don't map to claw-forge** — BMAD story points measure human dev time.
claw-forge agents run in parallel and don't use estimates; they work through features until done.
