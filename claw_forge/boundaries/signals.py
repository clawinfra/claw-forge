"""Per-file signal computations for boundary auditing."""
from __future__ import annotations

import re
from pathlib import Path

# Match if/elif on a string-literal comparison: ``if x == 'foo':`` or ``elif name == "bar":``
_DISPATCH_BRANCH_RE = re.compile(
    r"^\s*(?:if|elif)\s+\w[\w\.]*\s*==\s*['\"]\w+['\"]\s*:",
    re.MULTILINE,
)
# Match ``case 'foo':`` and ``case "bar":`` inside match statements.
_MATCH_CASE_RE = re.compile(
    r"^\s*case\s+['\"]\w+['\"]\s*:",
    re.MULTILINE,
)


def dispatch_score(path: Path) -> int:
    """Count if/elif/match-case branches that look like a string-keyed dispatcher.

    A high dispatch score on a single file is a strong indicator that every
    new feature has to extend the same chain — a classic plugin-registry
    refactor candidate.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    return len(_DISPATCH_BRANCH_RE.findall(text)) + len(_MATCH_CASE_RE.findall(text))


def import_centrality(target: Path, all_files: list[Path]) -> int:
    """Count distinct files (other than *target*) that import *target*.

    Heuristic: matches ``from <stem>`` or ``import <stem>`` on whitespace-prefixed
    lines.  Doesn't resolve relative imports against package layout — treats the
    file's stem as the import name.  Misses some cases; over-counts none we care
    about.
    """
    stem = target.stem
    if not stem or stem in {"__init__", "__main__"}:
        return 0
    pattern = re.compile(
        rf"^\s*(?:from\s+\.?{re.escape(stem)}\b|import\s+\.?{re.escape(stem)}\b)",
        re.MULTILINE,
    )
    count = 0
    for f in all_files:
        if f == target:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if pattern.search(text):
            count += 1
    return count
