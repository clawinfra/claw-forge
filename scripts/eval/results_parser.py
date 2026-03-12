"""Results parser for Terminal Bench 2.0 ablation study.

Pure data-transform module. Takes a flat list of TaskResult objects and produces
a structured ablation table + Markdown report. No I/O; all I/O is in the caller.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.eval.harbor_adapter import TaskResult

from scripts.eval.harbor_adapter import ABLATION_CONFIGS


@dataclass(frozen=True)
class ConfigStats:
    """Aggregate statistics for one ablation config."""

    config_id: str
    description: str
    mean_score: float
    std_score: float
    pass_rate: float
    n_runs: int
    n_errors: int
    delta_vs_baseline: float | None


@dataclass(frozen=True)
class AblationTable:
    """Full ablation study results."""

    model: str
    run_date: str
    configs: list[ConfigStats]
    baseline_score: float


class ResultsParser:
    """Parse a flat list of TaskResult objects into structured ablation statistics.

    This class is stateless — all methods are pure functions.
    """

    def parse(
        self,
        results: list[TaskResult],
        *,
        model: str,
        run_date: str | None = None,
    ) -> AblationTable:
        """Parse raw results into an AblationTable."""
        if run_date is None:
            run_date = date.today().isoformat()

        # Group by config_id
        groups: dict[str, list[TaskResult]] = {}
        for r in results:
            groups.setdefault(r.config_id, []).append(r)

        # Compute stats per config, sorted A → E
        sorted_ids = sorted(groups.keys())
        config_stats: list[ConfigStats] = []
        for cid in sorted_ids:
            stats = self._compute_stats(cid, groups[cid])
            config_stats.append(stats)

        # Get baseline score
        baseline_score = 0.0
        for cs in config_stats:
            if cs.config_id == "A":
                baseline_score = cs.mean_score
                break

        # Set delta_vs_baseline
        final_stats: list[ConfigStats] = []
        for cs in config_stats:
            if cs.config_id == "A":
                final_stats.append(cs)
            else:
                final_stats.append(
                    ConfigStats(
                        config_id=cs.config_id,
                        description=cs.description,
                        mean_score=cs.mean_score,
                        std_score=cs.std_score,
                        pass_rate=cs.pass_rate,
                        n_runs=cs.n_runs,
                        n_errors=cs.n_errors,
                        delta_vs_baseline=cs.mean_score - baseline_score,
                    )
                )

        return AblationTable(
            model=model,
            run_date=run_date,
            configs=final_stats,
            baseline_score=baseline_score,
        )

    def render_markdown(
        self,
        table: AblationTable,
        *,
        include_header: bool = True,
    ) -> str:
        """Render AblationTable to a Markdown section string."""
        lines: list[str] = []

        if include_header:
            lines.append(f"## Terminal Bench 2.0 Results — {table.run_date}")
            lines.append("")
            lines.append(f"Model: `{table.model}`")
            lines.append("")

        # Table header
        lines.append("| Config | Score | ± | Pass Rate | Δ vs A | Runs | Errors |")
        lines.append("|--------|------:|--:|----------:|-------:|-----:|-------:|")

        for cs in table.configs:
            delta_str = "—" if cs.delta_vs_baseline is None else f"{cs.delta_vs_baseline:+.1f}"
            pass_pct = f"{cs.pass_rate * 100:.0f}%"
            desc = ABLATION_CONFIGS.get(cs.config_id, None)
            label = f"{cs.config_id} — {cs.description}" if desc else cs.config_id
            lines.append(
                f"| {label} | {cs.mean_score:.1f} | ±{cs.std_score:.1f} "
                f"| {pass_pct} | {delta_str} | {cs.n_runs} | {cs.n_errors} |"
            )

        lines.append("")

        # Key findings
        b_delta = None
        e_delta = None
        best_config = None
        best_delta = float("-inf")
        for cs in table.configs:
            if cs.config_id == "B" and cs.delta_vs_baseline is not None:
                b_delta = cs.delta_vs_baseline
            if cs.config_id == "E" and cs.delta_vs_baseline is not None:
                e_delta = cs.delta_vs_baseline
            if cs.delta_vs_baseline is not None and cs.delta_vs_baseline > best_delta:
                best_delta = cs.delta_vs_baseline
                best_config = cs.config_id

        if b_delta is not None:
            lines.append(f"**Hashline impact (B vs A):** {b_delta:+.1f} pts  ")
        if e_delta is not None:
            lines.append(f"**Full-stack impact (E vs A):** {e_delta:+.1f} pts  ")
        if best_config is not None:
            lines.append(f"**Best single change:** Config {best_config} ({best_delta:+.1f} pts)  ")

        lines.append("")
        return "\n".join(lines)

    def _compute_stats(
        self,
        config_id: str,
        runs: list[TaskResult],
    ) -> ConfigStats:
        """Compute ConfigStats for one config from its raw runs."""
        non_error_runs = [r for r in runs if r.error is None]
        n_errors = len(runs) - len(non_error_runs)

        if not non_error_runs:
            desc = ABLATION_CONFIGS.get(config_id)
            return ConfigStats(
                config_id=config_id,
                description=desc.description if desc else config_id,
                mean_score=0.0,
                std_score=0.0,
                pass_rate=0.0,
                n_runs=0,
                n_errors=n_errors,
                delta_vs_baseline=None,
            )

        scores = [r.score for r in non_error_runs]
        mean = sum(scores) / len(scores)
        std = self._std(scores)
        pass_count = sum(1 for r in non_error_runs if r.passed)
        pass_rate = pass_count / len(non_error_runs)
        desc = ABLATION_CONFIGS.get(config_id)

        return ConfigStats(
            config_id=config_id,
            description=desc.description if desc else config_id,
            mean_score=mean,
            std_score=std,
            pass_rate=pass_rate,
            n_runs=len(non_error_runs),
            n_errors=n_errors,
            delta_vs_baseline=None,  # Set by parse() after all configs computed
        )

    @staticmethod
    def _std(values: list[float]) -> float:
        """Population standard deviation (ddof=0) of a list of floats.

        Returns 0.0 for lists with fewer than 2 elements.
        """
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return math.sqrt(variance)
