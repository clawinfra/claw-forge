# Frequently Asked Questions

Common questions about how claw-forge works, what it protects against, and how to operate it in production.

---

## How It Works

**What happens if an agent fails mid-run? Does it stop everything?**

No. Failed tasks are isolated from their wave siblings — other tasks in the same wave keep running. claw-forge retries the failed task up to 3 times (5 in YOLO mode) with exponential back-off (1 s, 2 s, 4 s…). After retries are exhausted the task is marked `failed` and any tasks that depend on it become `blocked`, but the rest of the project continues. You can inspect failures in the Kanban UI and drag-and-drop cards to retry manually.

---

**Can I add new features while a run is already in progress?**

You can add features, but the running dispatcher won't pick them up mid-wave — the execution plan is computed at start. The easiest path is `claw-forge plan` (or `/expand-project` in Claude Code), which reconciles new spec features against the existing session and inserts them as pending tasks. If you run this while the dispatcher is active, new tasks will be picked up on the next session restart. The reviewer plugin does dynamically create bugfix tasks mid-run; those are processed in a clean-up sweep after all main waves complete.

---

**Will claw-forge hit SQLite limits if I run many agents at once?**

For typical use (5–20 concurrent agents), SQLite in WAL mode handles write concurrency well. If you need more scale — dozens of long-running agents with high write throughput — switch to PostgreSQL by setting `CLAW_FORGE_DB_URL=postgresql+asyncpg://...` in your environment. The state service uses SQLAlchemy 2.0, so the swap is transparent.

---

**Does the schema change between versions? Will my SQLite file break on upgrade?**

The state service creates tables on startup with `CREATE TABLE IF NOT EXISTS` — there are no Alembic migrations. This means upgrading claw-forge with an existing SQLite file can silently miss new columns added in newer versions. The safe path for upgrades is to start a fresh session (`claw-forge plan ... --fresh`). If you need cross-version persistence, use PostgreSQL and manage schema changes manually.

---

## Security

**Does claw-forge prevent agents from running dangerous shell commands?**

Yes, via two layers that work together. First, a `bash_security_hook` runs before every shell command: it checks against a hardcoded blocklist (`sudo`, `dd`, `shutdown`, `netcat`, and others) and an allowlist of permitted tools (`git`, `python`, `pytest`, `curl`, etc.) — anything not on the allowlist is blocked before execution. Second, a `smart_can_use_tool` callback inspects every tool call, validates that all path arguments resolve inside your project directory, and blocks redirects to paths outside the sandbox. File operations (Read, Write, Edit, Glob, Grep) are also sandboxed to the project root.

---

**Can agents make network requests to internal addresses?**

This is a known limitation. The `WebFetch` and `WebSearch` tools are available to agents with no URL filtering — they do not block private IP ranges (RFC 1918) or cloud metadata endpoints such as `169.254.169.254`. For production deployments where agents run untrusted or user-supplied tasks, we recommend running claw-forge inside a network-restricted environment (e.g. a container with egress rules) rather than relying on application-level URL filtering.

---

**Are my API keys safe? Could they end up in logs?**

API keys are read from environment variables or `~/.claude/.credentials.json` and are never embedded in the source. The logging layer records command names, task outcomes, and truncated command strings — not credential values. Keys passed to subprocess environments use `os.environ` injection without logging the values. That said, any prompt or code sent to a cloud AI provider is transmitted to that provider — claw-forge's security boundary ends at the outbound API call.

---

## Getting Started

**How detailed does my spec need to be?**

Each feature needs at minimum a description and acceptance criteria written as verifiable conditions. Concrete is better: "15 unit tests, all passing" gives the agent a clear done condition; "add tests" does not. If you use `/create-spec` or `claw-forge validate-spec`, it will flag thin acceptance criteria before the run starts. Start with 5–10 well-defined features rather than 30 vague ones — you can always expand with `/expand-project` once the first wave is running.

---

**What do I see in the CLI if something goes wrong?**

Failed tasks are logged with their error message at `WARNING` level and stored in the database. The Kanban UI shows the failure reason on the task card. When a task is retried, the agent receives its prior error message as a resume preamble so it focuses on what went wrong rather than starting over. For detailed tracing, check `.claw-forge/state.log`, which captures the full agent interaction log for the session.

---

**Do I need to start the Kanban UI separately from `claw-forge run`?**

Yes. `claw-forge run` starts the state service (port 8420 by default) and the agent pool, but does not open the UI. Run `claw-forge ui` in a separate terminal to open the Kanban board. If you want both at once during development, `claw-forge dev` starts the API, UI, and (optionally with `--run`) the agent orchestrator in a single command.

---

## Reliability & Performance

**How well-tested is the async concurrency code?**

The dispatcher and scheduler are covered by unit tests that verify wave isolation (a failing task does not cancel sibling tasks), dependency ordering, and the pause/resume mechanism. The `_FreezableSemaphore` — which handles stopping a task without releasing its concurrency slot — has its own test suite. There are no dedicated stress tests for deadlock detection under high concurrency; the practical test for large YOLO runs is your own workload.

---

**Are provider failover and circuit breaking tested?**

Yes. The `CircuitBreaker` state machine (CLOSED → OPEN → HALF_OPEN) is tested in `tests/test_health.py`. The pool manager's routing strategies and per-provider fallback behaviour are covered in `tests/test_manager.py` and `tests/test_router.py`. End-to-end pool behaviour with simulated providers is tested in `tests/e2e/test_pool_e2e.py`.

---

**Is the in-process MCP server actually faster than a subprocess?**

Yes, meaningfully so. The SDK MCP server (`claw_forge/mcp/sdk_server.py`) runs in the same Python process and event loop as the orchestrator — feature tool calls (`feature_claim_and_get`, `feature_mark_passing`, etc.) are direct async function calls to SQLAlchemy with no IPC, socket setup, or subprocess spawn. The ~400 ms cold-start penalty mentioned in the architecture docs reflects the cost of starting a separate Python subprocess MCP server, which the in-process design avoids entirely.

---

**Will memory grow unboundedly with many concurrent agents?**

Each agent session buffers its conversation context in memory via the Claude Agent SDK. For large runs with many features, memory grows proportionally to the number of active sessions times their context size. There are no explicit memory caps in the runner. Practical mitigation: keep `--concurrency` at a level appropriate for your available RAM, and use `--reset-threshold` (context reset) for long-running sessions to keep individual context sizes bounded.

---

## Providers & Dependencies

**Are all dependencies actively maintained?**

The core dependencies — FastAPI, SQLAlchemy 2.0, httpx, Typer, and the Claude Agent SDK — are all actively maintained projects with no known end-of-life concerns. All versions are pinned in `uv.lock`. Automated vulnerability scanning (e.g. Dependabot) is not currently configured; if you need it for compliance, adding `.github/dependabot.yml` to the repo is straightforward.

---

**Is the `uv` lockfile reproducible across machines?**

Yes. `uv.lock` pins all transitive dependencies to exact versions and hashes. `uv sync --extra dev` on any supported platform (macOS, Linux, Python 3.11–3.13) will produce an identical environment. The CI matrix verifies this across all three Python versions on every push.

---

## Licensing & Community

**What license is claw-forge released under?**

Apache 2.0. You are free to use, modify, and distribute claw-forge — including in commercial products — as long as you retain the license and attribution notice. All core dependencies are Apache 2.0, MIT, or PSF licensed, so there are no license conflicts.

---

**How active is the project? How do I contribute?**

The project has approximately 85 releases over roughly two years and is in active development by ClawInfra. There is no formal `CONTRIBUTING.md` yet — the best starting point is to open a GitHub issue. Bug reports with reproduction steps, failing test cases, and documentation improvements are the most welcome contributions.

---

**How does claw-forge compare to AutoGPT or similar agent frameworks?**

claw-forge is narrower in scope and more opinionated. It is built specifically for implementing Python software projects from a structured spec, not for open-ended task automation. The key differentiators are the **feature DAG** (structured dependency ordering, not free-form execution), the **multi-provider pool** (rotation across Anthropic, Bedrock, Azure, Vertex, and Ollama with circuit breaking and cost tracking), and **brownfield support** (it can extend existing codebases, not just start from scratch). If you want an agent that answers questions or automates general workflows, frameworks like LangChain or CrewAI are a better fit. If you want an agent that implements a defined spec and tracks measurable progress toward it, claw-forge is built for that.
