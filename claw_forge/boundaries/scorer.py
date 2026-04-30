"""Compose per-file signals into a hotspot score and rank.

The composite score is a weighted sum of four signals (dispatch, import,
churn, function).  Default weights bias toward dispatch density (the
clearest plugin-registry refactor candidate) but every weight is
configurable via the ``weights`` argument.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_WEIGHTS: dict[str, float] = {
    "dispatch": 0.4,
    "import": 0.2,
    "churn": 0.3,
    "function": 0.1,
}


@dataclass
class Hotspot:
    """A file the audit has flagged as a refactor candidate.

    ``signals`` carries the raw per-signal counts so the report can show
    the user *why* the file scored high.  ``pattern`` is filled later by
    the classifier subagent (see ``claw_forge/boundaries/classifier.py``).
    """

    path: str  # relative path within project_dir
    score: float
    signals: dict[str, int] = field(default_factory=dict)
    pattern: str = ""


def score_file(
    *,
    dispatch: int,
    import_cent: int,
    churn: int,
    function: int,
    weights: dict[str, float] = DEFAULT_WEIGHTS,
) -> float:
    """Composite weighted-sum score.  Missing weight keys default to 0."""
    return (
        dispatch * weights.get("dispatch", 0.0)
        + import_cent * weights.get("import", 0.0)
        + churn * weights.get("churn", 0.0)
        + function * weights.get("function", 0.0)
    )


def rank_hotspots(
    candidates: list[Hotspot],
    *,
    min_score: float = 5.0,
) -> list[Hotspot]:
    """Filter to those at or above *min_score*, sorted descending by score."""
    above = [h for h in candidates if h.score >= min_score]
    return sorted(above, key=lambda h: h.score, reverse=True)
