# Multi-Core / GPU Leverage within an asyncio Event Loop

## Context

claw-forge uses a pure `asyncio` event loop for all concurrency. This document describes how to leverage multiple CPU cores or GPU acceleration when the main orchestration loop is async.

## Current Workload Analysis

| Workload | Bound | Already Offloaded? |
|----------|-------|-------------------|
| Claude API calls (30s+ each) | Network I/O | Yes — async |
| Git operations (commits, merges) | Disk I/O | Yes — `asyncio.to_thread()` |
| SQLite queries | Disk I/O | Yes — `aiosqlite` |
| Test execution (pytest, npm) | Subprocess | Yes — `create_subprocess_exec()` |
| Agent dispatch (5-10 parallel) | Network I/O | Yes — `asyncio.TaskGroup` |
| SHA256 hashing (hashline.py) | CPU | No — but negligible (~ms) |
| XML spec parsing | CPU | No — but runs once (~ms) |

**Conclusion: No meaningful CPU/GPU bottleneck exists today.** The system spends 99%+ of wall-clock time waiting on LLM API responses.

## Three Patterns for Multi-Core/GPU from asyncio

### Pattern 1: `ProcessPoolExecutor` — CPU-Bound Python Work

**When to use:** Python code doing heavy computation (embedding generation, AST analysis, large diffing, local model inference with Python bindings).

```python
import asyncio
import os
from concurrent.futures import ProcessPoolExecutor

# Create once at module level (pool persists across calls)
_cpu_pool = ProcessPoolExecutor(max_workers=os.cpu_count())

async def heavy_computation(data):
    loop = asyncio.get_running_loop()
    # Runs in a separate PROCESS — bypasses the GIL
    result = await loop.run_in_executor(_cpu_pool, cpu_bound_function, data)
    return result
```

**Key properties:**
- Each worker is a separate OS process with its own Python interpreter — **escapes the GIL**
- Arguments and return values must be picklable (serialized across process boundary)
- ~10ms startup overhead per task (process fork + pickle)
- Best for work taking >50ms — below that, the serialization overhead dominates

**Where it would apply in claw-forge:**
- If `hashline.py` ever processes thousands of files: `await loop.run_in_executor(pool, annotate_batch, files)`
- If spec parser handled massive XML specs: `await loop.run_in_executor(pool, parse_spec, content)`
- If local embedding generation were added for semantic search

### Pattern 2: Subprocess — External Tools That Already Use Multiple Cores

**When to use:** Calling tools like `ruff`, `mypy`, `pytest`, `cargo build`, `gcc` — these are already compiled programs that internally use threads/SIMD.

```python
proc = await asyncio.create_subprocess_exec(
    "ruff", "check", "--fix", ".",
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
stdout, stderr = await proc.communicate()
```

**Key properties:**
- The subprocess runs outside Python entirely — no GIL, no overhead
- Already uses however many cores the tool itself supports
- asyncio just awaits the result without blocking
- claw-forge already does this correctly in `reviewer.py` and via agent bash tools

**This is actually how claw-forge already leverages multi-core** — when agents run `pytest`, `ruff`, `mypy`, or `git` commands, those tools use all available cores. The asyncio loop just orchestrates them.

### Pattern 3: GPU via Subprocess or C Extension

**When to use:** Local model inference (llama.cpp, vLLM, TensorRT), image processing, or any CUDA workload.

**Option A: GPU server as a subprocess (recommended)**
```python
# Start a local inference server (runs on GPU, exposes HTTP API)
gpu_server = await asyncio.create_subprocess_exec(
    "python", "-m", "vllm.entrypoints.openai.api_server",
    "--model", "codellama/CodeLlama-7b",
    "--port", "8001",
)

# Call it like any other async HTTP endpoint
async with httpx.AsyncClient() as client:
    resp = await client.post("http://localhost:8001/v1/completions", json={...})
```

This is the cleanest pattern because:
- GPU work happens in a completely separate process
- Communication is via HTTP (same as cloud LLM APIs)
- The asyncio loop treats it identically to Anthropic/OpenAI calls
- claw-forge's pool manager already supports OpenAI-compatible endpoints (`openai_compat` provider)

**Option B: C extension in thread (for quick GPU calls)**
```python
# Libraries like torch, cupy expose C-level functions that release the GIL
result = await asyncio.to_thread(torch_model.generate, input_tensor)
```

This works because `torch.generate()` releases the GIL internally when executing CUDA kernels. The Python thread just waits for the GPU to finish.

## Recommendations

### Short term: No changes needed
The system is I/O-bound. Adding `ProcessPoolExecutor` would add complexity with zero performance gain.

### If local inference is added (e.g., Ollama provider for code review):
- Use **Pattern 2/3A**: Run the inference server as a subprocess
- claw-forge already has an `ollama` provider in `pool/providers/ollama.py` that communicates via HTTP
- This means GPU leverage is "free" — Ollama handles GPU scheduling internally, claw-forge just makes async HTTP calls

### If heavy local analysis is added (e.g., semantic code search, large AST transforms):
- Use **Pattern 1**: `ProcessPoolExecutor` with `loop.run_in_executor()`
- Create the pool once in `cli.py` and pass it down
- Wrap only the CPU-heavy function, not the entire workflow

### Anti-patterns to avoid

1. **Don't use `multiprocessing.Pool` directly** — it has its own event loop issues and doesn't compose well with asyncio
2. **Don't spawn threads for CPU work** — the GIL means Python threads don't actually parallelize computation; only use threads for blocking I/O
3. **Don't try to run GPU code in the main process** — CUDA contexts are heavy and can interfere with the event loop
4. **Don't over-parallelize** — if the work takes <50ms, the overhead of pickling data across process boundaries costs more than the parallelism saves

## Summary

| Pattern | Escapes GIL? | Best For | Overhead |
|---------|-------------|----------|----------|
| `asyncio.to_thread()` | No | Blocking I/O (git, file reads) | ~0.1ms |
| `ProcessPoolExecutor` | Yes | CPU-bound Python (hashing, parsing, embeddings) | ~10ms |
| `create_subprocess_exec()` | Yes | External tools (ruff, pytest, compilers) | ~50ms |
| GPU subprocess server | Yes | Local inference (Ollama, vLLM) | HTTP round-trip |

**The right mental model:** asyncio is the orchestrator. It doesn't do the heavy lifting — it dispatches work to the right executor (thread pool for I/O, process pool for CPU, subprocess for tools, HTTP for GPU). The event loop stays responsive because it's only doing lightweight coordination.
