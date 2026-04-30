"""Tests for composite hotspot scoring."""
from __future__ import annotations

from claw_forge.boundaries.scorer import (
    DEFAULT_WEIGHTS,
    Hotspot,
    rank_hotspots,
    score_file,
)


def test_score_file_weighted_sum_matches_default_weights() -> None:
    score = score_file(
        dispatch=10,
        import_cent=5,
        churn=4,
        function=2,
        weights=DEFAULT_WEIGHTS,
    )
    # 10*0.4 + 5*0.2 + 4*0.3 + 2*0.1 = 4 + 1 + 1.2 + 0.2 = 6.4
    assert abs(score - 6.4) < 1e-6


def test_score_file_with_custom_weights() -> None:
    score = score_file(
        dispatch=10, import_cent=0, churn=0, function=0,
        weights={"dispatch": 1.0, "import": 0.0, "churn": 0.0, "function": 0.0},
    )
    assert score == 10.0


def test_score_file_missing_weight_keys_default_to_zero() -> None:
    """A weights dict missing some keys treats them as 0 (no contribution)."""
    score = score_file(
        dispatch=10, import_cent=5, churn=4, function=2,
        weights={"dispatch": 1.0},  # only dispatch counted
    )
    assert score == 10.0


def test_rank_hotspots_filters_below_threshold_and_sorts_desc() -> None:
    candidates = [
        Hotspot(path="a.py", score=8.5, signals={}),
        Hotspot(path="b.py", score=2.0, signals={}),
        Hotspot(path="c.py", score=6.0, signals={}),
    ]
    ranked = rank_hotspots(candidates, min_score=5.0)
    assert [h.path for h in ranked] == ["a.py", "c.py"]


def test_rank_hotspots_empty_input_returns_empty() -> None:
    assert rank_hotspots([], min_score=5.0) == []


def test_rank_hotspots_all_below_threshold_returns_empty() -> None:
    candidates = [
        Hotspot(path="a.py", score=1.0, signals={}),
        Hotspot(path="b.py", score=2.0, signals={}),
    ]
    assert rank_hotspots(candidates, min_score=5.0) == []
