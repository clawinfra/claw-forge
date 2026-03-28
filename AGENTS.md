# AGENTS.md — claw-forge-issue17 Agent Harness

[One sentence describing what this repo does.]
This file is a **table of contents** — not a reference manual. Follow the links.

> **Context depth guide (progressive disclosure):**
> - **L1 (here):** orientation, commands, invariants — read this first
> - **L2 (`docs/`):** architecture, quality standards, conventions — read before coding
> - **L3 (source):** implementation details — pull on demand via grep/read tools
>
> Do not dump L2/L3 into your context unless you need it. Pull, don't pre-load.

---

## Repo Map

```
  claw_forge/
  docs/
  scripts/
  skills/
  tests/
  ui/
  website/
```

---

## Packages (3 total)

```
  claw_forge
  scripts
  tests
```

---

## Docs (start here before touching code)

| File | What it covers |
|------|---------------|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Layer rules, dependency graph, key invariants |
| [`docs/QUALITY.md`](docs/QUALITY.md) | Coverage targets, security rules, testing standards |
| [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) | Naming conventions, code style |
| [`docs/RESILIENCE.md`](docs/RESILIENCE.md) | Agent recovery protocols, 7-point checklist, VBR standards |
| [`docs/EXECUTION_PLAN_TEMPLATE.md`](docs/EXECUTION_PLAN_TEMPLATE.md) | Template for planning complex tasks |

---

## How to Build & Test

```bash
# Run all tests
uv run pytest tests/ -v

# Run lints
uv run ruff check . && uv run pyright

# Run agent-specific lints (architectural invariants)
bash scripts/agent-lint.sh
```

---

## Agent Invariants (non-negotiable)

1. **Always run tests before opening a PR.** Never break existing tests.
2. **Check docs/ARCHITECTURE.md before adding cross-package dependencies.**
3. **All new public APIs must have documentation.**
4. **Run `bash scripts/agent-lint.sh` locally.** Failures include fix instructions.
5. **For complex tasks** (multiple packages, new APIs, migrations), create an execution
   plan using `docs/EXECUTION_PLAN_TEMPLATE.md` before writing code.
6. **Log every task outcome to RSI loop** (if installed). After completing any task:
   ```bash
   uv run python ~/.openclaw/workspace/skills/rsi-loop/scripts/rsi_cli.py log \
     --task <type> --success <true|false> --quality <1-5> --issue "<what went wrong>"
   ```
   This feeds the self-improvement loop. Omit `--issue` on success.

---

## CI Gates

Every PR runs agent-lint + tests + lints. All must pass.

---

*This file must stay under 150 lines. See `scripts/agent-lint.sh`.*