# 🔥 claw-forge

**Autonomous coding agent harness for serious Python projects.**

Multi-provider API rotation · Claude Agent SDK core · 18 pre-installed skills · Pure asyncio · Zero Node.js

[![CI](https://github.com/clawinfra/claw-forge/actions/workflows/ci.yml/badge.svg)](https://github.com/clawinfra/claw-forge/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/claw-forge)](https://pypi.org/project/claw-forge/)
[![Python](https://img.shields.io/pypi/pyversions/claw-forge)](https://pypi.org/project/claw-forge/)
[![Tests](https://img.shields.io/badge/tests-427%20passing-brightgreen)](https://github.com/clawinfra/claw-forge/actions)
[![Coverage](https://img.shields.io/badge/coverage-%E2%89%A590%25-brightgreen)](https://github.com/clawinfra/claw-forge/actions)

---

## What it does

claw-forge runs autonomous coding agents that implement features, fix bugs, write tests, and review code — in parallel, across multiple AI providers, with live progress tracked in a Kanban UI.

It is built on the [Claude Agent SDK](https://pypi.org/project/claude-agent-sdk/) as its execution engine, with a provider pool layer on top for API key rotation, circuit breaking, and cost tracking.

---

## Quick Start

```bash
# Install
pip install uv
uv tool install claw-forge

# Create a project
claw-forge init my-app

# Run agents (uses ~/.claude/.credentials.json if you've run `claude login`)
claw-forge run my-app

# YOLO mode — max speed, no verification pauses
claw-forge run my-app --yolo

# Monitor in browser
claw-forge state &  # start state service on port 8888
cd ui && npm install && npm run dev  # open http://localhost:5173
```

---

## Provider Pool

Never hit a rate limit again. Configure multiple providers with automatic failover:

```yaml
# claw-forge.yaml
providers:
  # Use your `claude login` token — no API key needed
  claude-oauth:
    type: anthropic_oauth
    priority: 1

  # Direct API key as primary fallback
  anthropic-primary:
    type: anthropic
    api_key: ${ANTHROPIC_KEY_1}
    priority: 2

  # Second API key for burst capacity
  anthropic-secondary:
    type: anthropic
    api_key: ${ANTHROPIC_KEY_2}
    priority: 2

  # Cloud providers for enterprise scale
  aws-bedrock:
    type: bedrock
    region: us-east-1
    priority: 3

  azure-ai:
    type: azure
    endpoint: https://my-resource.openai.azure.com
    api_key: ${AZURE_KEY}
    priority: 4

  # Free-tier providers for lightweight tasks
  groq-free:
    type: openai_compat
    base_url: https://api.groq.com/openai/v1
    api_key: ${GROQ_KEY}
    priority: 5

  # Local model via Ollama
  local-ollama:
    type: ollama
    base_url: http://localhost:11434
    model: qwen2.5-coder
    priority: 6
```

The pool automatically:
- Routes requests through providers in priority order
- Backs off per-provider when rate limited (parses `Retry-After` headers)
- Opens per-provider circuit breakers on persistent failures
- Tracks cost, latency, and RPM per provider
- Falls through the entire chain before giving up

**5 routing strategies:** `priority` (default) · `round_robin` · `weighted_random` · `least_cost` · `least_latency`

---

## Supported Providers

| Provider | Type | Auth |
|---|---|---|
| Anthropic direct | `anthropic` | API key |
| Claude OAuth | `anthropic_oauth` | Auto-reads `~/.claude/.credentials.json` |
| Anthropic-format proxy | `anthropic_compat` | `x-api-key` or none (internal proxies) |
| AWS Bedrock | `bedrock` | IAM / instance role |
| Azure AI Foundry | `azure` | API key |
| Google Vertex AI | `vertex` | Application Default Credentials |
| Groq / Cerebras | `openai_compat` | API key |
| Any OpenAI-compat endpoint | `openai_compat` | Optional API key |
| Ollama (local) | `ollama` | Optional (usually none) |

---

## Agent Runtime

claw-forge uses the Claude Agent SDK for all agent execution. The SDK handles the tool-use loop, MCP server connections, permission hooks, streaming — claw-forge adds the orchestration, state management, and provider rotation layer on top.

### Bidirectional sessions

```python
from pathlib import Path
from claw_forge.agent import AgentSession
from claw_forge.agent.thinking import thinking_for_task
from claw_forge.agent.output import CODE_REVIEW_SCHEMA
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage

options = ClaudeAgentOptions(
    model="claude-sonnet-4-6",
    cwd=Path("./my-project"),
    thinking=thinking_for_task("coding"),      # adaptive by default
    max_budget_usd=1.00,                        # hard cost cap
    betas=["context-1m-2025-08-07"],            # 1M token context
)

async with AgentSession(options) as session:
    # Primary task
    async for msg in session.run("Implement the OAuth2 login flow"):
        handle_message(msg)

    # Tests failed — guide without restarting the session
    async for msg in session.follow_up("Focus on fixing test_auth.py first"):
        handle_message(msg)

    # Refactor went wrong — rewind files to before the last step
    await session.rewind(steps_back=1)

    # Escalate to Opus for the hard security review
    await session.switch_model("claude-opus-4-6")
```

### One-shot queries

```python
from claw_forge.agent import collect_result, collect_structured_result

# Simple text result
result = await collect_result(
    "Write unit tests for src/auth.py",
    cwd=Path("./my-project"),
    agent_type="testing",   # gets correct tool list + max_turns
)

# Structured JSON output (schema enforced)
review = await collect_structured_result(
    "Review the PR diff for security issues",
    cwd=Path("./my-project"),
    agent_type="reviewer",
    output_format=CODE_REVIEW_SCHEMA,
)
# review = {"verdict": "request_changes", "blockers": [...], "security_issues": [...]}
```

### Provider pool + agent

```python
from claw_forge.pool import ProviderPoolManager
from claw_forge.agent import collect_result

pool = ProviderPoolManager.from_config("claw-forge.yaml")
provider = await pool.acquire("claude-sonnet-4-6")

result = await collect_result(
    "Fix the failing integration tests",
    cwd=Path("./project"),
    provider_config=provider,  # routes through pool with failover
)
```

---

## Advanced SDK Features

claw-forge exposes all 20 Claude Agent SDK APIs. See [`docs/sdk-api-guide.md`](docs/sdk-api-guide.md) for detailed examples. Highlights:

| Feature | API | Use case |
|---|---|---|
| File undo | `enable_file_checkpointing` + `rewind_files()` | Roll back bad refactors |
| Cost cap | `max_budget_usd` | Hard limit per session |
| Structured output | `output_format` schema | Typed review verdicts |
| Thinking depth | `ThinkingConfig` | Deep for planning, off for monitoring |
| Named sub-agents | `AgentDefinition` | Planner / Coder / Reviewer roles |
| OS sandbox | `SandboxSettings` | Filesystem + network isolation |
| Model fallback | `fallback_model` | Auto-retry on model error |

---

## Security

Three-layer defence:

1. **`CanUseTool` callback** — Python function runs before every tool; blocks dangerous commands, restricts writes to project directory, can mutate tool inputs
2. **Bash security hook** — hardcoded blocklist (`sudo`, `dd`, `shutdown`, ...) + per-project `allowed_commands.yaml`
3. **`SandboxSettings`** — OS-level bash isolation on macOS/Linux (optional)

Agent lock file (`.claw-forge.lock`) prevents two agents running on the same project simultaneously.

---

## Workflow Features

| Feature | Command / Flag |
|---|---|
| YOLO mode | `claw-forge run my-app --yolo` |
| Pause (drain) | `claw-forge pause my-app` |
| Resume | `claw-forge resume my-app` |
| Human input | `claw-forge input my-app "Here's the API key"` |
| Batch features | `--batch-size 3` |
| Specific features | `--batch-features 1,2,3` |
| Pool health | `claw-forge pool-status` |

---

## Kanban UI

Real-time board tracking feature progress across all agents.

```bash
claw-forge state &          # start REST + WebSocket server on :8888
cd ui && npm install
npm run dev                  # http://localhost:5173/?session=<uuid>
```

**Columns:** Pending · In Progress · Passing · Failed · Blocked

**Header:** provider health dots · progress bar (X/Y passing) · live agent count · cost tracker

Live updates pushed over WebSocket: feature status changes, agent events, provider health, cost.

---

## Claude Commands

Six slash commands in `.claude/commands/` for use inside Claude Code:

| Command | Purpose |
|---|---|
| `/create-spec` | Interactive project spec creation |
| `/expand-project` | Add features to an existing project |
| `/check-code` | Run ruff + mypy + pytest and report |
| `/checkpoint` | Commit + DB snapshot + session summary |
| `/review-pr` | Structured PR review with verdict |
| `/pool-status` | Provider health and cost analysis |

Four agent definitions in `.claude/agents/`:

| Agent | Model | Purpose |
|---|---|---|
| `coding` | sonnet | Implement features, TDD-first |
| `testing` | sonnet | Run regression tests, report failures |
| `reviewing` | opus | Code review with blocking/suggestion/approve verdict |
| `initializer` | sonnet | Parse spec, create feature DAG |

---

## Pre-installed Skills (18)

**LSP servers (6):** pyright · gopls · rust-analyzer · typescript-lsp · clangd · solidity-lsp

**Process skills:** systematic-debug · verification-gate · parallel-dispatch · frontend-design · playwright-cli

**Integration skills:** web-research · git-workflow · api-client · docker · security-audit · performance · database

---

## Plugin System

Extend claw-forge with custom agent types via Python entry points — no fork required:

```toml
# your-package/pyproject.toml
[project.entry-points."claw_forge.plugins"]
my_agent = "my_package.plugin:MyAgentPlugin"
```

```python
from claw_forge.plugins.base import AgentPlugin, PluginContext, PluginResult

class MyAgentPlugin(AgentPlugin):
    name = "my_agent"
    description = "Does something custom"
    version = "1.0.0"

    def get_system_prompt(self, context: PluginContext) -> str:
        return "You are a specialist in ..."

    async def execute(self, context: PluginContext) -> PluginResult:
        from claw_forge.agent import collect_result
        result = await collect_result(
            self.get_system_prompt(context),
            cwd=context.project_dir,
            agent_type="coding",
        )
        return PluginResult(success=True, output=result)
```

---

## Development

```bash
git clone https://github.com/clawinfra/claw-forge.git
cd claw-forge
uv sync --extra dev
uv run pytest tests/ -v --cov --cov-report=term-missing
uv run ruff check claw_forge/
uv run mypy claw_forge/
```

---

## Documentation

| Document | Contents |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | System design, data flow, component details |
| [`docs/sdk-api-guide.md`](docs/sdk-api-guide.md) | 20 Claude Agent SDK APIs with claw-forge examples |
| [`claw-forge.yaml`](claw-forge.yaml) | Annotated configuration reference |
| [`website/tutorial.html`](website/tutorial.html) | End-to-end getting started guide |
| [`website/features.html`](website/features.html) | Full feature list |

---

## License

Apache-2.0 · Built by [ClawInfra](https://github.com/clawinfra)
