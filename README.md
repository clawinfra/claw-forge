# 🔨 claw-forge

**Multi-provider autonomous coding agent harness.**

A Python-first coding agent framework with automatic API provider rotation, circuit breakers, and cost tracking across Anthropic, AWS Bedrock, Azure, Vertex AI, and any OpenAI-compatible endpoint.

[![CI](https://github.com/clawinfra/claw-forge/actions/workflows/ci.yml/badge.svg)](https://github.com/clawinfra/claw-forge/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/claw-forge)](https://pypi.org/project/claw-forge/)
[![Python](https://img.shields.io/pypi/pyversions/claw-forge)](https://pypi.org/project/claw-forge/)

## Why claw-forge?

Existing coding agent harnesses have critical limitations:
- **Single provider** — one API key goes down, everything stops
- **Node.js dependency** — complex toolchains for Python-centric AI work
- **No cost tracking** — no visibility into spend across providers
- **Cold starts** — every session starts from scratch

claw-forge solves all of these:

| Feature | claw-forge | Others |
|---------|-----------|--------|
| Multi-provider pool | ✅ 6+ provider types | ❌ Single provider |
| Circuit breaker | ✅ Per-provider | ❌ No failover |
| Cost tracking | ✅ Per-request | ❌ None |
| Pure Python | ✅ `uv tool install` | ❌ Node.js required |
| Plugin system | ✅ Entry points | ❌ Monolithic |
| Session manifest | ✅ Cold-start elimination | ❌ Full re-analysis |

## Quick Start

```bash
# Install
uv tool install claw-forge

# Or with all provider support
uv tool install "claw-forge[all-providers]"

# Initialize a project
claw-forge init --project ./my-app

# Run a coding task
claw-forge run --project ./my-app --task coding

# Check provider pool status
claw-forge pool-status

# Start state service
claw-forge state --port 8420
```

## Provider Pool (The Killer Feature)

Configure multiple providers with automatic failover:

```yaml
providers:
  anthropic-1:
    type: anthropic
    api_key: ${ANTHROPIC_KEY_1}
    priority: 1

  anthropic-2:
    type: anthropic
    api_key: ${ANTHROPIC_KEY_2}
    priority: 1

  bedrock:
    type: bedrock
    region: us-east-1
    priority: 2

  azure:
    type: azure
    endpoint: https://my-resource.openai.azure.com
    api_key: ${AZURE_KEY}
    priority: 3
```

The pool automatically:
- Routes by priority with weighted random and round-robin options
- Detects rate limits and backs off per-provider
- Opens circuit breakers on persistent failures
- Tracks cost per provider per request
- Falls through the entire chain before giving up

## Supported Providers

| Provider | Type | Auth |
|----------|------|------|
| Anthropic Direct | `anthropic` | API key or OAuth token |
| Claude CLI OAuth | `anthropic_oauth` | Auto-read from `claude login` |
| Anthropic-format proxy | `anthropic_compat` | `x-api-key` (or none for internal) |
| AWS Bedrock | `bedrock` | IAM/boto3 |
| Azure AI Foundry | `azure` | API key |
| Google Vertex AI | `vertex` | Service account |
| Groq | `openai_compat` | API key |
| Any OpenAI-compatible | `openai_compat` | API key (optional) |

### Zero-config Claude OAuth

If you've already run `claude login`, add this to `claw-forge.yaml` — no API key needed:

```yaml
providers:
  claude-oauth:
    type: anthropic_oauth
    priority: 1
    # Token auto-read from ~/.claude/.credentials.json
```

### Anthropic-Compatible Proxies

For proxies that expose the Anthropic wire format at a custom URL:

```yaml
providers:
  my-proxy:
    type: anthropic_compat
    api_key: ${PROXY_KEY}
    base_url: https://proxy.example.com/v1
    priority: 2
    model_map:
      claude-sonnet-4-20250514: proxy-internal-sonnet  # optional rename

  # No-auth internal proxy (k8s sidecar, etc.)
  internal-gw:
    type: anthropic_compat
    api_key: null
    base_url: http://internal-gateway:8080/v1
    priority: 3
```

## Kanban UI

Monitor feature progress in real time with the built-in React/Vite board:

```bash
cd ui
npm install
npm run dev   # opens http://localhost:5173/?session=<uuid>
```

The board connects to `ws://localhost:8888/ws` for live updates pushed by the
state service (`ConnectionManager`).  Columns: **Pending | In Progress | Passing
| Failed | Blocked**.  Header shows provider pool health dots, overall progress
bar, active agent count, and total cost.

## Agent Runtime

claw-forge uses [`claude-agent-sdk`](https://pypi.org/project/claude-agent-sdk/) as its core execution engine. Every plugin runs agents through the SDK's `query()` loop, which handles tool use, permission prompts, MCP server connections, and streaming output — without spawning a subprocess or managing raw HTTP connections yourself.

### Using `run_agent()` directly

```python
from pathlib import Path
from claw_forge.agent import run_agent, collect_result
import claude_agent_sdk

# Stream messages as they arrive
async for message in run_agent(
    "Refactor the auth module to use OAuth2",
    model="claude-sonnet-4-5",
    cwd=Path("./my-project"),
    allowed_tools=["Read", "Write", "Edit", "Bash"],
    max_turns=30,
):
    if isinstance(message, claude_agent_sdk.AssistantMessage):
        for block in message.content:
            if isinstance(block, claude_agent_sdk.TextBlock):
                print(block.text)
    elif isinstance(message, claude_agent_sdk.ResultMessage):
        print(f"Done. Cost: ${message.total_cost_usd:.4f}")

# Or just get the final result text
result = await collect_result(
    "Write unit tests for src/auth.py",
    cwd=Path("./my-project"),
    allowed_tools=["Read", "Write", "Bash"],
)
print(result)
```

### Combining with the provider pool

The provider pool handles API key rotation and circuit breaking. Pass a `ProviderConfig` to route through any configured provider:

```python
from claw_forge.pool import ProviderPoolManager
from claw_forge.agent import collect_result

pool = ProviderPoolManager.from_config("claw-forge.yaml")
provider = await pool.acquire("claude-sonnet-4-5")

result = await collect_result(
    "Fix the failing tests",
    cwd=Path("./project"),
    provider_config=provider,
)
```

### MCP server integration

Skills that declare an `mcp` section in their `skill.yaml` can be loaded as MCP servers:

```python
from claw_forge.agent.mcp_builder import load_skills_as_mcp
from claw_forge.agent import run_agent

mcp_servers = load_skills_as_mcp(Path("~/.openclaw/skills").expanduser())

async for msg in run_agent(
    "Search the web for recent Python security advisories",
    mcp_servers=mcp_servers,
    allowed_tools=["mcp__web-search__search"],
):
    ...
```

## Plugin System

Agent types are plugins discovered via `pyproject.toml` entry points:

```toml
[project.entry-points."claw_forge.plugins"]
my_plugin = "my_package.plugin:MyPlugin"
```

Built-in plugins: `initializer`, `coding`, `testing`, `reviewer`

## Pre-installed Skills (18)

**LSP:** rust-analyzer, gopls, pyright, typescript-lsp, clangd, solidity-lsp

**Process:** systematic-debug, verification-gate, parallel-dispatch, test-driven, code-review

**Integration:** web-research, git-workflow, api-client, docker, security-audit, performance, database

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for full details including ASCII diagrams.

## Development

```bash
git clone https://github.com/clawinfra/claw-forge.git
cd claw-forge
uv sync --extra dev
uv run pytest tests/ -v --cov
uv run ruff check claw_forge/
uv run mypy claw_forge/
```

## License

Apache-2.0
