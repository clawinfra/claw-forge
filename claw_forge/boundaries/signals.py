"""Per-file signal computations for boundary auditing."""
from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta
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


def recent_churn(target: Path, *, repo_root: Path, since_days: int = 90) -> int:
    """Return the number of distinct branches that touched *target* in the
    last *since_days*.

    For each commit that modified *target* in the time window, look up which
    branches contain that commit and union the results.  A file modified on
    many distinct branches is a hotspot — every concurrent feature ends up
    rewriting the same lines.
    """
    since = (datetime.now() - timedelta(days=since_days)).strftime("%Y-%m-%d")
    try:
        rel = target.relative_to(repo_root)
    except ValueError:
        return 0
    try:
        proc = subprocess.run(  # noqa: S603, S607
            [
                "git", "log", "--all", f"--since={since}",
                "--pretty=format:%H", "--", str(rel),
            ],
            cwd=repo_root, check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError:
        return 0
    shas = [s for s in proc.stdout.splitlines() if s]
    if not shas:
        return 0
    branches: set[str] = set()
    for sha in shas:
        try:
            br = subprocess.run(  # noqa: S603, S607
                ["git", "branch", "--contains", sha, "--format=%(refname:short)"],
                cwd=repo_root, check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError:
            continue
        for line in br.stdout.splitlines():
            line = line.strip().lstrip("*").strip()
            if line:
                branches.add(line)
    return len(branches)


_DEF_RE = re.compile(r"^def\s+([a-zA-Z_]\w*)\s*\(", re.MULTILINE)


def function_centrality(target: Path, all_files: list[Path]) -> int:
    """Sum, for each public top-level function in *target*, the count of
    distinct other files that reference the function name.

    Cheap heuristic: regex on the bare name.  Over-counts when other files
    happen to define their own ``helper`` and call it locally; acceptable
    for ranking purposes.
    """
    try:
        target_text = target.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    fn_names = _DEF_RE.findall(target_text)
    if not fn_names:
        return 0
    total = 0
    for name in fn_names:
        if name.startswith("_"):
            continue  # private functions don't count
        pattern = re.compile(rf"\b{re.escape(name)}\s*\(")
        sites = 0
        for f in all_files:
            if f == target:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if pattern.search(text):
                sites += 1
        total += sites
    return total
