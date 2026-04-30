"""Top-level audit pipeline: walk → signal → score → rank.

Composes the four signal computations from ``signals.py`` against every
source file under the project root, emits a ``Hotspot`` per file with
its raw signals attached, then filters/sorts via the scorer.

The audit is **read-only** — no file modifications, no subprocess calls
beyond ``git ls-files`` and ``git log`` (signals.recent_churn).
"""
from __future__ import annotations

from pathlib import Path

from claw_forge.boundaries.scorer import (
    DEFAULT_WEIGHTS,
    Hotspot,
    rank_hotspots,
    score_file,
)
from claw_forge.boundaries.signals import (
    dispatch_score,
    function_centrality,
    import_centrality,
    recent_churn,
)
from claw_forge.boundaries.walker import walk_source_files


def run_audit(
    project_dir: Path,
    *,
    ignore_paths: list[str] | None = None,
    weights: dict[str, float] = DEFAULT_WEIGHTS,
    min_score: float = 5.0,
    since_days: int = 90,
) -> list[Hotspot]:
    """Compute per-file signals, composite score, and return ranked hotspots.

    Parameters
    ----------
    project_dir
        Root of the project to audit.  Must be a git repository.
    ignore_paths
        Additional path prefixes to skip beyond ``.gitignore`` and the
        walker's hard-skip list.  Pass per-project config (``ui/dist``,
        ``coverage``, etc.) here.
    weights
        Per-signal weights for the composite score.  See
        ``scorer.DEFAULT_WEIGHTS`` for the defaults.
    min_score
        Files below this composite score are excluded from the result.
    since_days
        Window for ``recent_churn``; commits older than this are ignored.
    """
    files = list(walk_source_files(project_dir, ignore_paths=ignore_paths or []))
    candidates: list[Hotspot] = []
    for path in files:
        d = dispatch_score(path)
        i = import_centrality(path, files)
        c = recent_churn(path, repo_root=project_dir, since_days=since_days)
        f = function_centrality(path, files)
        score = score_file(
            dispatch=d, import_cent=i, churn=c, function=f, weights=weights,
        )
        candidates.append(Hotspot(
            path=str(path.relative_to(project_dir)),
            score=score,
            signals={"dispatch": d, "import": i, "churn": c, "function": f},
        ))
    return rank_hotspots(candidates, min_score=min_score)
