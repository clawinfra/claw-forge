"""Unit tests for ResultsParser.

All logic tested on synthetic TaskResult lists — no I/O.
"""
from __future__ import annotations

import math

import pytest

from scripts.eval.harbor_adapter import TaskResult
from scripts.eval.results_parser import AblationTable, ConfigStats, ResultsParser


def _make_result(
    config_id: str = "A",
    task_id: str = "task-001",
    rep: int = 1,
    score: float = 80.0,
    passed: bool = True,
    error: str | None = None,
) -> TaskResult:
    """Factory for test TaskResult objects."""
    return TaskResult(
        config_id=config_id,
        task_id=task_id,
        rep=rep,
        score=score,
        passed=passed,
        duration_s=1.0,
        error=error,
    )


class TestResultsParserParse:
    def test_parse_empty_results_returns_empty_table(self) -> None:
        parser = ResultsParser()
        table = parser.parse([], model="sonnet", run_date="2026-01-01")
        assert len(table.configs) == 0
        assert table.baseline_score == 0.0

    def test_parse_single_config_single_run(self) -> None:
        parser = ResultsParser()
        results = [_make_result(score=85.0)]
        table = parser.parse(results, model="sonnet", run_date="2026-01-01")
        assert len(table.configs) == 1
        assert table.configs[0].mean_score == 85.0
        assert table.configs[0].std_score == 0.0
        assert table.configs[0].n_runs == 1

    def test_parse_computes_correct_mean(self) -> None:
        parser = ResultsParser()
        results = [
            _make_result(score=60.0, task_id="t1"),
            _make_result(score=80.0, task_id="t2"),
            _make_result(score=100.0, task_id="t3"),
        ]
        table = parser.parse(results, model="sonnet", run_date="2026-01-01")
        assert table.configs[0].mean_score == pytest.approx(80.0)

    def test_parse_computes_correct_std(self) -> None:
        parser = ResultsParser()
        results = [
            _make_result(score=60.0, task_id="t1"),
            _make_result(score=80.0, task_id="t2"),
            _make_result(score=100.0, task_id="t3"),
        ]
        table = parser.parse(results, model="sonnet", run_date="2026-01-01")
        # std of [60, 80, 100] = sqrt(((60-80)^2 + 0 + (100-80)^2) / 3) = sqrt(800/3)
        expected_std = math.sqrt(800.0 / 3.0)
        assert table.configs[0].std_score == pytest.approx(expected_std, rel=1e-6)

    def test_parse_excludes_error_runs_from_mean(self) -> None:
        parser = ResultsParser()
        results = [
            _make_result(score=80.0, task_id="t1"),
            _make_result(score=0.0, task_id="t2", error="failed"),
            _make_result(score=100.0, task_id="t3"),
        ]
        table = parser.parse(results, model="sonnet", run_date="2026-01-01")
        assert table.configs[0].mean_score == pytest.approx(90.0)
        assert table.configs[0].n_errors == 1
        assert table.configs[0].n_runs == 2

    def test_parse_computes_pass_rate(self) -> None:
        parser = ResultsParser()
        results = [
            _make_result(score=80.0, task_id="t1", passed=True),
            _make_result(score=40.0, task_id="t2", passed=False),
            _make_result(score=90.0, task_id="t3", passed=True),
        ]
        table = parser.parse(results, model="sonnet", run_date="2026-01-01")
        assert table.configs[0].pass_rate == pytest.approx(2.0 / 3.0)

    def test_parse_sets_delta_none_for_config_a(self) -> None:
        parser = ResultsParser()
        results = [_make_result(config_id="A", score=70.0)]
        table = parser.parse(results, model="sonnet", run_date="2026-01-01")
        assert table.configs[0].delta_vs_baseline is None

    def test_parse_sets_delta_vs_baseline_for_others(self) -> None:
        parser = ResultsParser()
        results = [
            _make_result(config_id="A", score=70.0, task_id="t1"),
            _make_result(config_id="B", score=85.0, task_id="t1"),
        ]
        table = parser.parse(results, model="sonnet", run_date="2026-01-01")
        b_stats = next(c for c in table.configs if c.config_id == "B")
        assert b_stats.delta_vs_baseline == pytest.approx(15.0)

    def test_parse_orders_configs_a_to_e(self) -> None:
        parser = ResultsParser()
        results = [
            _make_result(config_id="E", score=90.0, task_id="t1"),
            _make_result(config_id="A", score=70.0, task_id="t1"),
            _make_result(config_id="C", score=80.0, task_id="t1"),
        ]
        table = parser.parse(results, model="sonnet", run_date="2026-01-01")
        ids = [c.config_id for c in table.configs]
        assert ids == ["A", "C", "E"]

    def test_parse_all_errors_gives_zero_mean(self) -> None:
        parser = ResultsParser()
        results = [
            _make_result(config_id="A", score=0.0, error="err1", task_id="t1"),
            _make_result(config_id="A", score=0.0, error="err2", task_id="t2"),
        ]
        table = parser.parse(results, model="sonnet", run_date="2026-01-01")
        assert table.configs[0].mean_score == 0.0
        assert table.configs[0].std_score == 0.0
        assert table.configs[0].n_errors == 2
        assert table.configs[0].n_runs == 0

    def test_parse_sets_model_and_date(self) -> None:
        parser = ResultsParser()
        results = [_make_result()]
        table = parser.parse(results, model="claude-sonnet-4-6", run_date="2026-03-12")
        assert table.model == "claude-sonnet-4-6"
        assert table.run_date == "2026-03-12"

    def test_parse_default_date_is_today(self) -> None:
        parser = ResultsParser()
        results = [_make_result()]
        table = parser.parse(results, model="sonnet")
        # Just verify it's a valid ISO date
        assert len(table.run_date) == 10
        assert table.run_date.count("-") == 2


class TestResultsParserRenderMarkdown:
    def _make_table(self, **kwargs: object) -> AblationTable:
        defaults = {
            "model": "claude-sonnet-4-6",
            "run_date": "2026-03-12",
            "configs": [
                ConfigStats("A", "baseline", 70.0, 5.0, 0.8, 10, 0, None),
                ConfigStats("B", "hashline", 80.0, 4.0, 0.9, 10, 0, 10.0),
                ConfigStats("E", "full", 90.0, 3.0, 0.95, 10, 1, 20.0),
            ],
            "baseline_score": 70.0,
        }
        defaults.update(kwargs)
        return AblationTable(**defaults)  # type: ignore[arg-type]

    def test_render_contains_all_config_ids(self) -> None:
        parser = ResultsParser()
        table = self._make_table()
        md = parser.render_markdown(table)
        assert "A — baseline" in md
        assert "B — hashline" in md
        assert "E — full" in md

    def test_render_includes_model_name(self) -> None:
        parser = ResultsParser()
        table = self._make_table()
        md = parser.render_markdown(table)
        assert "claude-sonnet-4-6" in md

    def test_render_includes_run_date(self) -> None:
        parser = ResultsParser()
        table = self._make_table()
        md = parser.render_markdown(table)
        assert "2026-03-12" in md

    def test_render_shows_delta_with_sign(self) -> None:
        parser = ResultsParser()
        table = self._make_table()
        md = parser.render_markdown(table)
        assert "+10.0" in md
        assert "+20.0" in md

    def test_render_shows_n_errors_when_nonzero(self) -> None:
        parser = ResultsParser()
        table = self._make_table()
        md = parser.render_markdown(table)
        # Config E has 1 error
        assert "1" in md

    def test_render_no_header_when_include_header_false(self) -> None:
        parser = ResultsParser()
        table = self._make_table()
        md = parser.render_markdown(table, include_header=False)
        assert "## Terminal Bench" not in md

    def test_render_is_valid_markdown_table(self) -> None:
        parser = ResultsParser()
        table = self._make_table()
        md = parser.render_markdown(table)
        lines = [ln for ln in md.split("\n") if "|" in ln]
        # All table rows should have the same number of columns
        col_counts = [ln.count("|") for ln in lines]
        assert len(set(col_counts)) == 1


class TestStd:
    def test_std_empty_list_returns_zero(self) -> None:
        assert ResultsParser._std([]) == 0.0

    def test_std_single_element_returns_zero(self) -> None:
        assert ResultsParser._std([42.0]) == 0.0

    def test_std_known_values(self) -> None:
        # [2, 4, 4, 4, 5, 5, 7, 9] → mean=5, variance=4, std=2.0
        values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        assert ResultsParser._std(values) == pytest.approx(2.0)
