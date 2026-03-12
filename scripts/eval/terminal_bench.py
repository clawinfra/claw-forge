"""Terminal Bench 2.0 evaluation harness — CLI and AblationRunner.

Runs N ablation configs × M reps × K tasks against Harbor and collects results.
Supports partial run recovery via JSON Lines state file.

Usage:
    python -m scripts.eval.terminal_bench --config A --reps 3 --model sonnet
    python -m scripts.eval.terminal_bench --config all --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from dataclasses import asdict
from pathlib import Path

from scripts.eval.harbor_adapter import (
    ABLATION_CONFIGS,
    AblationConfig,
    HarborAdapter,
    TaskResult,
)
from scripts.eval.results_parser import ResultsParser

logger = logging.getLogger(__name__)

# Model aliases
MODEL_ALIASES: dict[str, str] = {
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
    "haiku": "claude-haiku-4-6",
}

VALID_CONFIGS = set(ABLATION_CONFIGS.keys()) | {"all"}


class RunState:
    """Persisted state for partial run recovery.

    Stored as JSON Lines in {output_dir}/run_state.jsonl.
    """

    def __init__(self) -> None:
        self.completed_keys: set[str] = set()
        self.completed_results: list[TaskResult] = []


class AblationRunner:
    """Runs N ablation configs × M reps × K tasks and collects TaskResult objects.

    Supports partial run recovery: if the process is interrupted, completed
    results are preserved in a state file.
    """

    def __init__(
        self,
        adapter: HarborAdapter,
        *,
        output_dir: Path,
        model: str = "claude-sonnet-4-6",
        concurrency: int = 1,
    ) -> None:
        self.adapter = adapter
        self.output_dir = output_dir
        self.model = model
        self.concurrency = concurrency
        self._state_file = output_dir / "run_state.jsonl"

    async def run(
        self,
        config_ids: list[str],
        *,
        reps: int = 3,
        task_ids: list[str] | None = None,
        dry_run: bool = False,
    ) -> list[TaskResult]:
        """Run ablation over specified configs × reps × tasks."""
        state = self._load_state()

        if task_ids is None:
            task_ids = self.adapter.list_tasks()

        results = list(state.completed_results)
        semaphore = asyncio.Semaphore(self.concurrency)

        for config_id in config_ids:
            config = ABLATION_CONFIGS[config_id]
            for rep in range(1, reps + 1):
                tasks_to_run: list[tuple[str, AblationConfig, int]] = []
                for task_id in task_ids:
                    key = self._make_key(config_id, task_id, rep)
                    if key in state.completed_keys:
                        logger.info("Skipping completed: %s", key)
                        continue
                    tasks_to_run.append((task_id, config, rep))

                for task_id, cfg, r in tasks_to_run:
                    async with semaphore:
                        result = await self._run_one(cfg, task_id, r, dry_run)
                        results.append(result)
                        self._append_result(result)
                        state.completed_keys.add(
                            self._make_key(cfg.config_id, task_id, r)
                        )

        return results

    def _load_state(self) -> RunState:
        """Load partial run state from run_state.jsonl."""
        state = RunState()
        if not self._state_file.exists():
            return state
        with open(self._state_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                key = self._make_key(data["config_id"], data["task_id"], data["rep"])
                state.completed_keys.add(key)
                state.completed_results.append(
                    TaskResult(
                        config_id=data["config_id"],
                        task_id=data["task_id"],
                        rep=data["rep"],
                        score=data["score"],
                        passed=data["passed"],
                        duration_s=data["duration_s"],
                        error=data.get("error"),
                        raw_scoring=data.get("raw_scoring", {}),
                    )
                )
        return state

    def _append_result(self, result: TaskResult) -> None:
        """Append a single TaskResult to run_state.jsonl."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        with open(self._state_file, "a") as f:
            f.write(json.dumps(asdict(result)) + "\n")

    def _make_key(self, config_id: str, task_id: str, rep: int) -> str:
        """Return the unique key string for a (config, task, rep) triple."""
        return f"{config_id}:{task_id}:{rep}"

    async def _run_one(
        self,
        config: AblationConfig,
        task_id: str,
        rep: int,
        dry_run: bool,
    ) -> TaskResult:
        """Run a single (config, task, rep) triple via the adapter."""
        logger.info(
            "Running %s / %s / rep %d (dry_run=%s)",
            config.config_id,
            task_id,
            rep,
            dry_run,
        )
        start = time.monotonic()
        result = await self.adapter.run_task(
            task_id,
            config=config,
            rep=rep,
            model=self.model,
            dry_run=dry_run,
        )
        elapsed = time.monotonic() - start
        logger.info(
            "Completed %s / %s / rep %d: score=%.1f passed=%s (%.1fs)",
            config.config_id,
            task_id,
            rep,
            result.score,
            result.passed,
            elapsed,
        )
        return result


def _resolve_model(model: str) -> str:
    """Resolve model alias to full name."""
    return MODEL_ALIASES.get(model, model)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="terminal-bench",
        description="Terminal Bench 2.0 ablation evaluation harness",
    )
    parser.add_argument(
        "--config",
        required=True,
        choices=sorted(VALID_CONFIGS),
        help="Ablation config ID (A-E) or 'all'",
    )
    parser.add_argument(
        "--reps",
        type=int,
        default=3,
        help="Number of repetitions per (config, task) pair (default: 3)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("TERMINAL_BENCH_MODEL", "claude-sonnet-4-6"),
        help="Model name or alias (default: claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate setup without running real tasks",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(os.environ.get("TERMINAL_BENCH_OUTPUT_DIR", "docs/benchmarks/")),
        help="Output directory for results (default: docs/benchmarks/)",
    )
    parser.add_argument(
        "--harbor-url",
        default=os.environ.get("HARBOR_BASE_URL", "https://api.harborframework.com"),
        help="Harbor API base URL",
    )
    parser.add_argument(
        "--harbor-key",
        default=os.environ.get("HARBOR_API_KEY"),
        help="Harbor API key (or set HARBOR_API_KEY env var)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("TERMINAL_BENCH_CONCURRENCY", "1")),
        help="Number of parallel tasks (default: 1)",
    )
    parser.add_argument(
        "--tasks",
        nargs="*",
        default=None,
        help="Explicit task IDs to run (default: all from Harbor)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    ns = parser.parse_args(argv)

    # Validate reps > 0
    if ns.reps < 1:
        parser.error("--reps must be >= 1")

    return ns


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Returns:
        Exit code: 0 = success, 1 = partial failure, 2 = total failure.
    """
    ns = parse_args(argv)

    # Configure logging
    log_level = logging.DEBUG if ns.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")

    # Validate harbor key
    if not ns.harbor_key:
        logger.error("Harbor API key required. Set HARBOR_API_KEY or use --harbor-key.")
        return 2

    # Resolve model alias
    model = _resolve_model(ns.model)

    # Expand "all" to config list
    config_ids = ["A", "B", "C", "D", "E"] if ns.config == "all" else [ns.config]

    # Build adapter and runner
    adapter = HarborAdapter(ns.harbor_url, ns.harbor_key)
    output_dir: Path = ns.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    runner = AblationRunner(
        adapter,
        output_dir=output_dir,
        model=model,
        concurrency=ns.concurrency,
    )

    # Run
    try:
        results = asyncio.run(
            runner.run(
                config_ids,
                reps=ns.reps,
                task_ids=ns.tasks,
                dry_run=ns.dry_run,
            )
        )
    except Exception:
        logger.exception("Fatal error during run")
        return 2

    if not results:
        logger.warning("No results collected")
        return 2

    # Parse and render
    parser = ResultsParser()
    table = parser.parse(results, model=model)
    md = parser.render_markdown(table)

    # Write results
    results_file = output_dir / "results.md"
    if results_file.exists():
        content = results_file.read_text()
        marker = "<!-- RESULTS_MARKER: new sections inserted above this line -->"
        if marker in content:
            content = content.replace(marker, md + "\n" + marker)
        else:
            content = md + "\n" + content
        results_file.write_text(content)
    else:
        results_file.write_text(md)

    # Print summary
    print(md)

    # Determine exit code
    error_count = sum(1 for r in results if r.error is not None and r.error != "dry-run")
    if error_count == len(results):
        return 2
    if error_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
