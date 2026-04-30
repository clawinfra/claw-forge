# `claw-forge boundaries` Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `claw-forge boundaries audit | apply | status` commands that identify and refactor extension hotspots in target codebases, converting "edit shared file" surfaces into "drop new plugin file" patterns. Built on claude-agent-sdk; uses the same sandbox + permission infrastructure as `claw-forge run`.

**Architecture:** Two phases. **Audit** (read-only) walks the project tree, computes per-file signals (dispatch density, import centrality, git churn, function centrality), composites them into a hotspot score, and emits `boundaries_report.md`. **Apply** (modifies repo) iterates over confirmed hotspots; for each, spawns a coding subagent on a feature branch with sandboxed permissions, runs the project's test command, and squash-merges on green / reverts on red. Refactors run **serially** because they share files.

**Tech Stack:** Python 3.12, Typer (existing CLI), claude-agent-sdk (`query()` + `can_use_tool`), `git` plumbing, pytest, ruff, mypy.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `claw_forge/boundaries/__init__.py` | Create | Public re-exports (`audit`, `apply_hotspot`, `Report`) |
| `claw_forge/boundaries/walker.py` | Create | Enumerate source files, respect `.gitignore` and `boundaries.ignore_paths` |
| `claw_forge/boundaries/signals.py` | Create | Per-file signal computation (dispatch, imports, churn, functions) |
| `claw_forge/boundaries/scorer.py` | Create | Composite score + ranking; threshold filter |
| `claw_forge/boundaries/classifier.py` | Create | Subagent that classifies hotspot pattern (registry / split / etc.) |
| `claw_forge/boundaries/report.py` | Create | Emit + parse `boundaries_report.md` |
| `claw_forge/boundaries/refactor.py` | Create | Per-hotspot subagent invocation + `can_use_tool` permissions |
| `claw_forge/boundaries/apply.py` | Create | Per-hotspot loop: branch / subagent / test / merge or revert |
| `claw_forge/boundaries/audit.py` | Create | Top-level audit orchestration |
| `claw_forge/boundaries/cli.py` | Create | Typer subapp: `audit`, `apply`, `status` commands |
| `claw_forge/cli.py` | Modify | `app.add_typer(boundaries_app, name="boundaries")` registration |
| `tests/boundaries/__init__.py` | Create | Empty marker |
| `tests/boundaries/test_walker.py` | Create | File enumeration tests |
| `tests/boundaries/test_signals.py` | Create | Per-signal scoring tests |
| `tests/boundaries/test_scorer.py` | Create | Composite + threshold tests |
| `tests/boundaries/test_report.py` | Create | Report emit / parse round-trip |
| `tests/boundaries/test_apply.py` | Create | Apply lifecycle on synthetic project |
| `tests/boundaries/fixtures/` | Create | Tiny mock projects with known hotspot patterns |

---

## Phase A — Audit (Tasks 1-11)

### Task 1: Module scaffolding

**Files:**
- Create: `claw_forge/boundaries/__init__.py`
- Create: `tests/boundaries/__init__.py`

- [ ] **Step 1: Create the empty package files**

```bash
mkdir -p claw_forge/boundaries tests/boundaries tests/boundaries/fixtures
echo '"""Plugin-boundary refactoring harness — audit + apply."""' > claw_forge/boundaries/__init__.py
echo '' > tests/boundaries/__init__.py
```

- [ ] **Step 2: Verify import**

```bash
uv run python -c "import claw_forge.boundaries"
```

Expected: no error.

- [ ] **Step 3: Commit**

```bash
git add claw_forge/boundaries/ tests/boundaries/
git commit -m "chore(boundaries): scaffold module package"
```

---

### Task 2: Walker enumerates source files respecting .gitignore

**Files:**
- Create: `claw_forge/boundaries/walker.py`
- Create: `tests/boundaries/test_walker.py`

- [ ] **Step 1: Write the failing test**

Create `tests/boundaries/test_walker.py`:

```python
"""Tests for the source-file walker."""
from __future__ import annotations

from pathlib import Path

import subprocess

from claw_forge.boundaries.walker import walk_source_files


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)


def test_walker_excludes_gitignored_paths(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("__pycache__/\n.venv/\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "main.cpython.pyc").write_bytes(b"\x00")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text("# venv\n")
    files = list(walk_source_files(tmp_path))
    rels = sorted(str(f.relative_to(tmp_path)) for f in files)
    assert "src/main.py" in rels
    assert ".gitignore" in rels  # tracked-but-config files included
    assert all(".venv" not in r for r in rels)
    assert all("__pycache__" not in r for r in rels)


def test_walker_respects_extra_ignore_paths(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "dist").mkdir()
    (tmp_path / "ui" / "dist" / "bundle.js").write_text("// generated\n")
    (tmp_path / "ui" / "src.ts").write_text("export {};\n")
    files = list(walk_source_files(tmp_path, ignore_paths=["ui/dist"]))
    rels = sorted(str(f.relative_to(tmp_path)) for f in files)
    assert "ui/src.ts" in rels
    assert all("ui/dist" not in r for r in rels)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/boundaries/test_walker.py -v
```

Expected: ImportError — `walk_source_files` not defined.

- [ ] **Step 3: Implement `walker.py`**

Create `claw_forge/boundaries/walker.py`:

```python
"""Walk source files in a project, respecting .gitignore and configured ignores."""
from __future__ import annotations

import subprocess
from collections.abc import Iterable, Iterator
from pathlib import Path

# Source-file extensions the audit cares about.
SOURCE_SUFFIXES: frozenset[str] = frozenset({
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt",
    ".rb", ".php", ".cs", ".c", ".cc", ".cpp", ".h", ".hpp",
})

# Always-skip paths regardless of .gitignore.
DEFAULT_SKIP: frozenset[str] = frozenset({
    ".git", ".claw-forge", "node_modules", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "venv", ".venv", "env", "dist", "build",
    "target", ".next", ".nuxt",
})


def walk_source_files(
    root: Path,
    *,
    ignore_paths: Iterable[str] = (),
) -> Iterator[Path]:
    """Yield every source file under *root* that git tracks (or would track).

    Uses ``git ls-files --cached --others --exclude-standard`` so .gitignore
    is honored without re-implementing parsing.  Returns absolute paths.
    """
    extra_ignores = {p.strip("/") for p in ignore_paths}
    proc = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root, check=True, capture_output=True, text=True,
    )
    for rel in proc.stdout.splitlines():
        rel = rel.strip()
        if not rel:
            continue
        # Hard skips
        first = rel.split("/", 1)[0]
        if first in DEFAULT_SKIP:
            continue
        if any(rel == p or rel.startswith(p + "/") for p in extra_ignores):
            continue
        path = root / rel
        if not path.is_file():
            continue
        # Source extension or explicit allow-list (.gitignore included as a known config)
        if path.suffix in SOURCE_SUFFIXES or rel in {".gitignore"}:
            yield path
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/boundaries/test_walker.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/boundaries/walker.py tests/boundaries/test_walker.py
git commit -m "feat(boundaries): walker enumerates source files via git ls-files"
```

---

### Task 3: Dispatch-score signal

**Files:**
- Create: `claw_forge/boundaries/signals.py`
- Create: `tests/boundaries/test_signals.py`

- [ ] **Step 1: Write the failing test**

Create `tests/boundaries/test_signals.py`:

```python
"""Tests for per-file signal computation."""
from __future__ import annotations

from pathlib import Path

from claw_forge.boundaries.signals import dispatch_score


def test_dispatch_score_counts_long_if_chain_at_module_scope(tmp_path: Path) -> None:
    src = """
def main(args):
    if args.cmd == 'foo':
        do_foo()
    elif args.cmd == 'bar':
        do_bar()
    elif args.cmd == 'baz':
        do_baz()
    elif args.cmd == 'qux':
        do_qux()
    else:
        raise ValueError(args.cmd)
"""
    p = tmp_path / "cli.py"
    p.write_text(src)
    score = dispatch_score(p)
    assert score >= 4, f"expected >=4 dispatch branches, got {score}"


def test_dispatch_score_zero_for_simple_file(tmp_path: Path) -> None:
    p = tmp_path / "model.py"
    p.write_text("class User:\n    name: str\n    email: str\n")
    assert dispatch_score(p) == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/boundaries/test_signals.py::test_dispatch_score_counts_long_if_chain_at_module_scope -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `dispatch_score`**

Create (or extend) `claw_forge/boundaries/signals.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/boundaries/test_signals.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/boundaries/signals.py tests/boundaries/test_signals.py
git commit -m "feat(boundaries): dispatch_score signal counts string-keyed if/match chains"
```

---

### Task 4: Import-centrality signal

**Files:**
- Modify: `claw_forge/boundaries/signals.py`
- Modify: `tests/boundaries/test_signals.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/boundaries/test_signals.py`:

```python
def test_import_centrality_counts_distinct_files_importing_target(tmp_path: Path) -> None:
    """A file imported by 3 others has centrality 3."""
    target = tmp_path / "core.py"
    target.write_text("VALUE = 1\n")
    (tmp_path / "a.py").write_text("from core import VALUE\n")
    (tmp_path / "b.py").write_text("import core\n")
    (tmp_path / "c.py").write_text("from .core import VALUE\n")
    (tmp_path / "d.py").write_text("# does not import\n")
    from claw_forge.boundaries.signals import import_centrality
    files = list(tmp_path.glob("*.py"))
    assert import_centrality(target, files) == 3
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/boundaries/test_signals.py::test_import_centrality_counts_distinct_files_importing_target -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `import_centrality`**

Append to `claw_forge/boundaries/signals.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/boundaries/test_signals.py -v
```

Expected: PASS (all signals tests).

- [ ] **Step 5: Commit**

```bash
git add claw_forge/boundaries/signals.py tests/boundaries/test_signals.py
git commit -m "feat(boundaries): import_centrality signal"
```

---

### Task 5: Recent-churn signal (git log)

**Files:**
- Modify: `claw_forge/boundaries/signals.py`
- Modify: `tests/boundaries/test_signals.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/boundaries/test_signals.py`:

```python
def test_recent_churn_counts_distinct_branches_touching_file(tmp_path: Path) -> None:
    """A file modified across N distinct branches in the last 90 days reports
    churn = N."""
    import subprocess as sp
    sp.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    sp.run(["git", "config", "user.email", "t@t.x"], cwd=tmp_path, check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    target = tmp_path / "shared.py"
    target.write_text("v = 0\n")
    sp.run(["git", "add", "."], cwd=tmp_path, check=True)
    sp.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    for i, branch in enumerate(["feat/a", "feat/b", "feat/c"]):
        sp.run(["git", "checkout", "-q", "-b", branch], cwd=tmp_path, check=True)
        target.write_text(f"v = {i + 1}\n")
        sp.run(["git", "add", "."], cwd=tmp_path, check=True)
        sp.run(["git", "commit", "-q", "-m", f"edit on {branch}"], cwd=tmp_path, check=True)
        sp.run(["git", "checkout", "-q", "main"], cwd=tmp_path, check=True)
    from claw_forge.boundaries.signals import recent_churn
    assert recent_churn(target, repo_root=tmp_path, since_days=90) == 3
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/boundaries/test_signals.py::test_recent_churn_counts_distinct_branches_touching_file -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `recent_churn`**

Append to `claw_forge/boundaries/signals.py`:

```python
import subprocess
from datetime import datetime, timedelta


def recent_churn(target: Path, *, repo_root: Path, since_days: int = 90) -> int:
    """Return the number of distinct branches that touched *target* in the
    last *since_days*.  Excludes the current HEAD branch from being counted
    multiple times by collapsing all commits into the set of refs that point
    at them.
    """
    since = (datetime.now() - timedelta(days=since_days)).strftime("%Y-%m-%d")
    try:
        # List commit SHAs that modified the file in the time window
        proc = subprocess.run(
            [
                "git", "log", "--all", f"--since={since}",
                "--pretty=format:%H", "--", str(target.relative_to(repo_root)),
            ],
            cwd=repo_root, check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError:
        return 0
    shas = [s for s in proc.stdout.splitlines() if s]
    if not shas:
        return 0
    # For each commit, find which branches contain it; count the union of branches
    branches: set[str] = set()
    for sha in shas:
        try:
            br = subprocess.run(
                ["git", "branch", "--contains", sha, "--format=%(refname:short)"],
                cwd=repo_root, check=True, capture_output=True, text=True,
            )
            for line in br.stdout.splitlines():
                line = line.strip().lstrip("*").strip()
                if line:
                    branches.add(line)
        except subprocess.CalledProcessError:
            continue
    return len(branches)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/boundaries/test_signals.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/boundaries/signals.py tests/boundaries/test_signals.py
git commit -m "feat(boundaries): recent_churn signal counts distinct touching branches"
```

---

### Task 6: Function-centrality signal

**Files:**
- Modify: `claw_forge/boundaries/signals.py`
- Modify: `tests/boundaries/test_signals.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/boundaries/test_signals.py`:

```python
def test_function_centrality_counts_call_sites(tmp_path: Path) -> None:
    """For each top-level function in target, count call sites in other files."""
    target = tmp_path / "util.py"
    target.write_text("def helper():\n    pass\n\ndef rare():\n    pass\n")
    (tmp_path / "a.py").write_text("from util import helper\nhelper()\nhelper()\n")
    (tmp_path / "b.py").write_text("from util import helper\nhelper()\n")
    (tmp_path / "c.py").write_text("# nothing\n")
    from claw_forge.boundaries.signals import function_centrality
    score = function_centrality(target, [tmp_path / "a.py", tmp_path / "b.py", tmp_path / "c.py"])
    # helper() appears in 2 distinct other files; rare() appears in 0.
    assert score == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/boundaries/test_signals.py::test_function_centrality_counts_call_sites -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `function_centrality`**

Append to `claw_forge/boundaries/signals.py`:

```python
_DEF_RE = re.compile(r"^def\s+([a-zA-Z_]\w*)\s*\(", re.MULTILINE)


def function_centrality(target: Path, all_files: list[Path]) -> int:
    """Sum, for each top-level function in *target*, the count of distinct
    other files that reference the function name.

    Cheap heuristic: regex on the bare name.  Will over-count if other files
    define their own ``helper`` and call it locally; acceptable for ranking.
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
            continue  # private — don't count
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/boundaries/test_signals.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/boundaries/signals.py tests/boundaries/test_signals.py
git commit -m "feat(boundaries): function_centrality signal"
```

---

### Task 7: Composite scorer + ranking

**Files:**
- Create: `claw_forge/boundaries/scorer.py`
- Create: `tests/boundaries/test_scorer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/boundaries/test_scorer.py`:

```python
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


def test_rank_hotspots_filters_below_threshold_and_sorts_desc() -> None:
    candidates = [
        Hotspot(path="a.py", score=8.5, signals={}),
        Hotspot(path="b.py", score=2.0, signals={}),
        Hotspot(path="c.py", score=6.0, signals={}),
    ]
    ranked = rank_hotspots(candidates, min_score=5.0)
    assert [h.path for h in ranked] == ["a.py", "c.py"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/boundaries/test_scorer.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `scorer.py`**

Create `claw_forge/boundaries/scorer.py`:

```python
"""Compose per-file signals into a hotspot score and rank."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_WEIGHTS: dict[str, float] = {
    "dispatch": 0.4,
    "import": 0.2,
    "churn": 0.3,
    "function": 0.1,
}


@dataclass
class Hotspot:
    path: str  # relative path within project_dir
    score: float
    signals: dict[str, int] = field(default_factory=dict)
    pattern: str = ""  # filled in later by classifier


def score_file(
    *,
    dispatch: int,
    import_cent: int,
    churn: int,
    function: int,
    weights: dict[str, float] = DEFAULT_WEIGHTS,
) -> float:
    """Composite weighted-sum score."""
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
    """Filter to those above *min_score*, sorted descending."""
    above = [h for h in candidates if h.score >= min_score]
    return sorted(above, key=lambda h: h.score, reverse=True)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/boundaries/test_scorer.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/boundaries/scorer.py tests/boundaries/test_scorer.py
git commit -m "feat(boundaries): composite scorer + threshold-based ranker"
```

---

### Task 8: Audit orchestration ties walker + signals + scorer together

**Files:**
- Create: `claw_forge/boundaries/audit.py`
- Modify: `tests/boundaries/test_audit.py` (new file)

- [ ] **Step 1: Write the failing integration test**

Create `tests/boundaries/test_audit.py`:

```python
"""End-to-end audit on a synthetic project."""
from __future__ import annotations

import subprocess
from pathlib import Path

from claw_forge.boundaries.audit import run_audit


def test_audit_flags_dispatcher_file_above_simple_files(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.x"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    # Hotspot: 8-branch dispatcher
    cli = tmp_path / "cli.py"
    cli.write_text(
        "def main(args):\n"
        + "\n".join(
            f"    {'if' if i == 0 else 'elif'} args.cmd == 'c{i}':\n        do_c{i}()"
            for i in range(8)
        )
        + "\n    else:\n        raise ValueError\n"
    )
    # Simple file
    (tmp_path / "model.py").write_text("class User:\n    name: str\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    hotspots = run_audit(tmp_path, min_score=2.0)
    paths = [h.path for h in hotspots]
    assert "cli.py" in paths
    assert "model.py" not in paths
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/boundaries/test_audit.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `audit.py`**

Create `claw_forge/boundaries/audit.py`:

```python
"""Top-level audit: walk → signal → score → rank."""
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
    """Compute per-file signals, composite score, and return ranked hotspots."""
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/boundaries/test_audit.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/boundaries/audit.py tests/boundaries/test_audit.py
git commit -m "feat(boundaries): top-level audit orchestration"
```

---

### Task 9: Hotspot pattern classifier (subagent)

**Files:**
- Create: `claw_forge/boundaries/classifier.py`
- Create: `tests/boundaries/test_classifier.py`

This task wraps a claude-agent-sdk `query()` call that reads the hotspot file's content and returns a structured pattern label (`registry`, `split`, `extract_collaborators`, `route_table`).

- [ ] **Step 1: Write the failing test**

Create `tests/boundaries/test_classifier.py`:

```python
"""Tests for the hotspot pattern classifier subagent.

The classifier is mocked because exercising claude-agent-sdk in unit tests is
slow and flaky.  The test verifies the classifier wires inputs/outputs
correctly given a stubbed agent response.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from claw_forge.boundaries.classifier import classify_hotspot
from claw_forge.boundaries.scorer import Hotspot


def test_classify_hotspot_returns_pattern_from_subagent(tmp_path: Path) -> None:
    cli = tmp_path / "cli.py"
    cli.write_text("# big dispatcher\n" + "if x == 'a':\n    pass\n" * 10)
    hotspot = Hotspot(
        path="cli.py",
        score=8.7,
        signals={"dispatch": 10, "churn": 5, "import": 3, "function": 2},
    )
    with patch(
        "claw_forge.boundaries.classifier._invoke_classifier_subagent",
        return_value={"pattern": "registry", "rationale": "10 if/elif on cmd"},
    ):
        result = classify_hotspot(hotspot, project_dir=tmp_path)
    assert result.pattern == "registry"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/boundaries/test_classifier.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `classifier.py`**

Create `claw_forge/boundaries/classifier.py`:

```python
"""Subagent that classifies a hotspot's refactor pattern."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claw_forge.agent.runner import collect_structured_result
from claw_forge.boundaries.scorer import Hotspot


_CLASSIFIER_PROMPT = """\
You are auditing a code file to determine the cleanest refactor pattern.

File: {path}
Lines: {lines}
Signals:
- dispatch chains: {dispatch}
- imports: {imports}
- churn: {churn}
- function refs: {functions}

File contents (first 200 lines):
{content}

Choose ONE of these patterns:
- "registry"  : long if/match dispatch on a string key → extract one file per case
- "split"     : multiple unrelated domains in one file → split by domain
- "extract_collaborators" : god-class with many responsibilities → extract helper classes
- "route_table" : hardcoded route/handler list → introduce route registry

Return JSON only, no prose:
{{
  "pattern": "<one of the four>",
  "rationale": "<one sentence>"
}}
"""


async def _invoke_classifier_subagent(prompt: str) -> dict[str, Any]:
    """Run the classifier subagent and return its parsed JSON output."""
    return await collect_structured_result(prompt, agent_type="auditor")


def classify_hotspot(hotspot: Hotspot, *, project_dir: Path) -> Hotspot:
    """Run the classifier subagent and stamp ``pattern`` onto the hotspot."""
    target = project_dir / hotspot.path
    try:
        content = target.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return hotspot
    head = "\n".join(content[:200])
    prompt = _CLASSIFIER_PROMPT.format(
        path=hotspot.path,
        lines=len(content),
        dispatch=hotspot.signals.get("dispatch", 0),
        imports=hotspot.signals.get("import", 0),
        churn=hotspot.signals.get("churn", 0),
        functions=hotspot.signals.get("function", 0),
        content=head,
    )
    import asyncio
    try:
        result = asyncio.run(_invoke_classifier_subagent(prompt))
    except Exception:  # noqa: BLE001 — best-effort; fall back to no pattern
        return hotspot
    pattern = str(result.get("pattern", "")).strip()
    if pattern in {"registry", "split", "extract_collaborators", "route_table"}:
        hotspot.pattern = pattern
    return hotspot
```

(`collect_structured_result` is the existing helper in `claw_forge/agent/runner.py` — confirm by `grep -n collect_structured_result claw_forge/agent/runner.py` before relying on its exact signature.)

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/boundaries/test_classifier.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/boundaries/classifier.py tests/boundaries/test_classifier.py
git commit -m "feat(boundaries): pattern classifier subagent"
```

---

### Task 10: Report emission + parsing

**Files:**
- Create: `claw_forge/boundaries/report.py`
- Create: `tests/boundaries/test_report.py`

- [ ] **Step 1: Write the failing test**

Create `tests/boundaries/test_report.py`:

```python
"""Tests for boundaries_report.md emission and parsing."""
from __future__ import annotations

from pathlib import Path

from claw_forge.boundaries.report import emit_report, parse_report
from claw_forge.boundaries.scorer import Hotspot


def test_round_trip_emit_then_parse(tmp_path: Path) -> None:
    hotspots = [
        Hotspot(
            path="cli/main.py", score=8.7,
            signals={"dispatch": 10, "import": 6, "churn": 14, "function": 3},
            pattern="registry",
        ),
        Hotspot(
            path="parser.py", score=6.2,
            signals={"dispatch": 4, "import": 8, "churn": 5, "function": 1},
            pattern="route_table",
        ),
    ]
    out = tmp_path / "boundaries_report.md"
    emit_report(hotspots, out_path=out, project_name="myapp")
    parsed = parse_report(out)
    assert len(parsed) == 2
    assert parsed[0].path == "cli/main.py"
    assert parsed[0].pattern == "registry"
    assert parsed[0].signals["dispatch"] == 10
    assert parsed[1].path == "parser.py"
    assert parsed[1].pattern == "route_table"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/boundaries/test_report.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `report.py`**

Create `claw_forge/boundaries/report.py`:

```python
"""Emit and parse boundaries_report.md."""
from __future__ import annotations

import re
from pathlib import Path

from claw_forge.boundaries.scorer import Hotspot


_HEADER_RE = re.compile(r"^## (?P<idx>\d+)\.\s+(?P<path>\S+)\s+\(score (?P<score>[\d.]+)\)\s*$")
_SIGNAL_RE = re.compile(
    r"^- signals:\s+dispatch=(?P<d>\d+),\s+import=(?P<i>\d+),\s+churn=(?P<c>\d+),\s+function=(?P<f>\d+)\s*$"
)
_PATTERN_RE = re.compile(r"^\*\*Proposed pattern:\*\*\s+(?P<pattern>\w+)\s*$")


def emit_report(
    hotspots: list[Hotspot],
    *,
    out_path: Path,
    project_name: str = "",
) -> None:
    lines: list[str] = []
    title = f"# Boundaries Audit — {project_name}" if project_name else "# Boundaries Audit"
    lines.append(title)
    lines.append("")
    lines.append(f"{len(hotspots)} hotspot(s) identified.")
    lines.append("")
    for idx, h in enumerate(hotspots, 1):
        lines.append(f"## {idx}. {h.path}  (score {h.score:.1f})")
        s = h.signals
        lines.append(
            f"- signals: dispatch={s.get('dispatch', 0)}, "
            f"import={s.get('import', 0)}, "
            f"churn={s.get('churn', 0)}, "
            f"function={s.get('function', 0)}"
        )
        if h.pattern:
            lines.append(f"**Proposed pattern:** {h.pattern}")
        lines.append("")
    out_path.write_text("\n".join(lines) + "\n")


def parse_report(path: Path) -> list[Hotspot]:
    """Parse a previously-emitted report back into Hotspots."""
    text = path.read_text(encoding="utf-8")
    hotspots: list[Hotspot] = []
    current: Hotspot | None = None
    for line in text.splitlines():
        m_h = _HEADER_RE.match(line)
        if m_h:
            if current is not None:
                hotspots.append(current)
            current = Hotspot(
                path=m_h.group("path"),
                score=float(m_h.group("score")),
            )
            continue
        m_s = _SIGNAL_RE.match(line)
        if m_s and current is not None:
            current.signals = {
                "dispatch": int(m_s.group("d")),
                "import": int(m_s.group("i")),
                "churn": int(m_s.group("c")),
                "function": int(m_s.group("f")),
            }
            continue
        m_p = _PATTERN_RE.match(line)
        if m_p and current is not None:
            current.pattern = m_p.group("pattern")
    if current is not None:
        hotspots.append(current)
    return hotspots
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/boundaries/test_report.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/boundaries/report.py tests/boundaries/test_report.py
git commit -m "feat(boundaries): boundaries_report.md emit/parse round-trip"
```

---

### Task 11: `claw-forge boundaries audit` CLI command

**Files:**
- Create: `claw_forge/boundaries/cli.py`
- Modify: `claw_forge/cli.py` (add Typer subapp registration)
- Test: `tests/boundaries/test_cli.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/boundaries/test_cli.py`:

```python
"""Tests for ``claw-forge boundaries audit`` CLI."""
from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from claw_forge.cli import app


def test_boundaries_audit_writes_report(tmp_path: Path, monkeypatch) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.x"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "main.py").write_text(
        "\n".join(
            f"{'if' if i == 0 else 'elif'} cmd == 'c{i}':\n    do_c{i}()" for i in range(6)
        ) + "\n"
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    runner = CliRunner()
    result = runner.invoke(
        app, ["boundaries", "audit", "--project", str(tmp_path), "--min-score", "1.0"]
    )
    assert result.exit_code == 0, result.output
    report = tmp_path / "boundaries_report.md"
    assert report.exists()
    text = report.read_text()
    assert "main.py" in text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/boundaries/test_cli.py -v
```

Expected: typer error — `boundaries` subcommand not registered.

- [ ] **Step 3: Create the boundaries Typer subapp**

Create `claw_forge/boundaries/cli.py`:

```python
"""Typer subapp for `claw-forge boundaries audit | apply | status`."""
from __future__ import annotations

from pathlib import Path

import typer

from claw_forge.boundaries.audit import run_audit
from claw_forge.boundaries.report import emit_report

boundaries_app = typer.Typer(help="Plugin-boundary audit + refactor commands.")


@boundaries_app.command()
def audit(
    project: Path = typer.Option(
        Path.cwd(), "--project", help="Project root to audit (default: CWD)"
    ),
    min_score: float = typer.Option(
        5.0, "--min-score", help="Minimum hotspot score to include in the report"
    ),
    out: Path = typer.Option(
        None, "--out", help="Output path (default: <project>/boundaries_report.md)"
    ),
) -> None:
    """Read-only: scan the project, score hotspots, write boundaries_report.md."""
    project = project.resolve()
    out_path = out or (project / "boundaries_report.md")
    hotspots = run_audit(project, min_score=min_score)
    emit_report(hotspots, out_path=out_path, project_name=project.name)
    typer.echo(
        f"Wrote {out_path} with {len(hotspots)} hotspot(s) (min score {min_score})."
    )
```

- [ ] **Step 4: Register the subapp in `cli.py`**

In `claw_forge/cli.py`, near the other Typer setup (top of file, near the `app = typer.Typer(...)` line — confirm location with `grep -n 'app = typer\.Typer' claw_forge/cli.py`), add:

```python
from claw_forge.boundaries.cli import boundaries_app
app.add_typer(boundaries_app, name="boundaries")
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/boundaries/test_cli.py::test_boundaries_audit_writes_report -v
```

Expected: PASS.

- [ ] **Step 6: Sanity-check the CLI manually**

```bash
uv run claw-forge boundaries audit --help
```

Expected: Typer help output.

- [ ] **Step 7: Commit**

```bash
git add claw_forge/boundaries/cli.py claw_forge/cli.py tests/boundaries/test_cli.py
git commit -m "feat(cli): claw-forge boundaries audit command"
```

---

## Phase B — Apply (Tasks 12-18)

### Task 12: Refactor subagent prompt + sandboxed permissions

**Files:**
- Create: `claw_forge/boundaries/refactor.py`
- Create: `tests/boundaries/test_refactor.py`

- [ ] **Step 1: Write the failing test (mocked subagent)**

Create `tests/boundaries/test_refactor.py`:

```python
"""Tests for the refactor subagent invocation."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from claw_forge.boundaries.refactor import run_refactor_subagent
from claw_forge.boundaries.scorer import Hotspot


def test_run_refactor_subagent_passes_hotspot_to_agent(tmp_path: Path) -> None:
    hotspot = Hotspot(
        path="cli.py", score=8.7,
        signals={"dispatch": 10, "import": 5, "churn": 7, "function": 2},
        pattern="registry",
    )
    (tmp_path / "cli.py").write_text("if cmd == 'a':\n    pass\n")
    captured: dict[str, str] = {}
    async def fake_query(prompt: str, **kwargs):
        captured["prompt"] = prompt
        captured["project_dir"] = str(kwargs.get("project_dir", ""))
        return {"changes_made": True}
    with patch("claw_forge.boundaries.refactor._dispatch_agent", side_effect=fake_query):
        import asyncio
        asyncio.run(run_refactor_subagent(hotspot, project_dir=tmp_path))
    assert "cli.py" in captured["prompt"]
    assert "registry" in captured["prompt"]
    assert captured["project_dir"] == str(tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/boundaries/test_refactor.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `refactor.py`**

Create `claw_forge/boundaries/refactor.py`:

```python
"""Refactor subagent: takes one hotspot + pattern, applies the refactor."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from claw_forge.agent.runner import run_agent
from claw_forge.boundaries.scorer import Hotspot


_REFACTOR_PROMPTS: dict[str, str] = {
    "registry": (
        "Refactor {path} so its long if/elif chain on a string key becomes "
        "a plugin registry: extract each branch into its own file under a "
        "``commands/`` (or analogous) subdirectory; introduce a registry "
        "loader; the main file becomes only argument parsing + registry "
        "dispatch.  Preserve all behavior and all tests must pass."
    ),
    "split": (
        "Refactor {path} by splitting it into multiple files, one per "
        "logical domain.  Preserve all public APIs and behavior."
    ),
    "extract_collaborators": (
        "Refactor {path} by extracting collaborator classes/objects.  "
        "Preserve behavior."
    ),
    "route_table": (
        "Refactor {path} by replacing the hardcoded route/handler list "
        "with a route registry where new handlers are added by importing a "
        "decorated function.  Preserve all routes."
    ),
}


async def _dispatch_agent(prompt: str, *, project_dir: Path) -> dict[str, Any]:
    """Run the SDK coding agent with sandbox + can_use_tool restrictions."""
    # The existing run_agent helper handles sandbox + permissions.  We pass
    # agent_type='coding' so it picks up the editing tool set.
    final = {}
    async for msg in run_agent(
        prompt=prompt,
        project_dir=project_dir,
        agent_type="coding",
    ):
        # The agent emits status messages; the final one carries the summary.
        final = msg if isinstance(msg, dict) else final
    return final


async def run_refactor_subagent(
    hotspot: Hotspot, *, project_dir: Path,
) -> dict[str, Any]:
    """Build the prompt for the hotspot's pattern and dispatch the agent."""
    template = _REFACTOR_PROMPTS.get(hotspot.pattern, _REFACTOR_PROMPTS["registry"])
    prompt = template.format(path=hotspot.path)
    return await _dispatch_agent(prompt, project_dir=project_dir)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/boundaries/test_refactor.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/boundaries/refactor.py tests/boundaries/test_refactor.py
git commit -m "feat(boundaries): refactor subagent for hotspot-specific patterns"
```

---

### Task 13: Test gating helper

**Files:**
- Create: `claw_forge/boundaries/apply.py` (start)
- Create: `tests/boundaries/test_apply.py` (start)

- [ ] **Step 1: Write the failing test**

Create `tests/boundaries/test_apply.py`:

```python
"""Tests for the apply lifecycle on synthetic projects."""
from __future__ import annotations

import subprocess
from pathlib import Path

from claw_forge.boundaries.apply import run_test_command


def _init_repo_with_passing_test(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.x"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "passing.sh").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "passing.sh").chmod(0o755)
    (tmp_path / "failing.sh").write_text("#!/bin/sh\nexit 1\n")
    (tmp_path / "failing.sh").chmod(0o755)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)


def test_run_test_command_returns_true_on_zero_exit(tmp_path: Path) -> None:
    _init_repo_with_passing_test(tmp_path)
    assert run_test_command("./passing.sh", cwd=tmp_path) is True


def test_run_test_command_returns_false_on_nonzero(tmp_path: Path) -> None:
    _init_repo_with_passing_test(tmp_path)
    assert run_test_command("./failing.sh", cwd=tmp_path) is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/boundaries/test_apply.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `run_test_command`**

Create `claw_forge/boundaries/apply.py`:

```python
"""Per-hotspot apply loop: branch → subagent → test → merge or revert."""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path


def run_test_command(
    cmd: str, *, cwd: Path, timeout_seconds: float = 1800.0,
) -> bool:
    """Run *cmd* in *cwd*; return True if exit 0 within *timeout_seconds*."""
    try:
        result = subprocess.run(
            shlex.split(cmd),
            cwd=cwd,
            timeout=timeout_seconds,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/boundaries/test_apply.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/boundaries/apply.py tests/boundaries/test_apply.py
git commit -m "feat(boundaries): test-command runner for apply gating"
```

---

### Task 14: Per-hotspot apply lifecycle (branch + subagent + gate + merge/revert)

**Files:**
- Modify: `claw_forge/boundaries/apply.py`
- Modify: `tests/boundaries/test_apply.py`

This task is the core of phase B. It uses claw-forge's existing git helpers (`create_worktree`, `squash_merge`, `remove_worktree`) to mirror the production refactor flow.

- [ ] **Step 1: Write the failing test**

Append to `tests/boundaries/test_apply.py`:

```python
def test_apply_hotspot_squash_merges_when_tests_pass(tmp_path: Path, monkeypatch) -> None:
    """If subagent makes a real edit and tests stay green, the change is squash-
    merged to main and the worktree is cleaned up."""
    import subprocess
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.x"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "cli.py").write_text("# original\n")
    (tmp_path / "test.sh").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "test.sh").chmod(0o755)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    from claw_forge.boundaries.apply import apply_hotspot
    from claw_forge.boundaries.scorer import Hotspot
    hotspot = Hotspot(path="cli.py", score=8.7, pattern="registry")
    # Stub the subagent to write to the file (simulates a successful refactor).
    async def fake_run_refactor(h, *, project_dir):
        (project_dir / "cli.py").write_text("# refactored\n")
        return {"changes_made": True}
    monkeypatch.setattr(
        "claw_forge.boundaries.apply.run_refactor_subagent", fake_run_refactor,
    )
    result = apply_hotspot(
        hotspot, project_dir=tmp_path, test_command="./test.sh",
    )
    assert result["status"] == "merged"
    # main should now contain the refactored content
    assert (tmp_path / "cli.py").read_text() == "# refactored\n"


def test_apply_hotspot_reverts_when_tests_fail(tmp_path: Path, monkeypatch) -> None:
    import subprocess
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.x"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "cli.py").write_text("# original\n")
    (tmp_path / "test.sh").write_text("#!/bin/sh\nexit 1\n")
    (tmp_path / "test.sh").chmod(0o755)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    from claw_forge.boundaries.apply import apply_hotspot
    from claw_forge.boundaries.scorer import Hotspot
    hotspot = Hotspot(path="cli.py", score=8.7, pattern="registry")
    async def fake_run_refactor(h, *, project_dir):
        (project_dir / "cli.py").write_text("# broken\n")
        return {"changes_made": True}
    monkeypatch.setattr(
        "claw_forge.boundaries.apply.run_refactor_subagent", fake_run_refactor,
    )
    result = apply_hotspot(
        hotspot, project_dir=tmp_path, test_command="./test.sh",
    )
    assert result["status"] == "reverted"
    # main is unchanged
    assert (tmp_path / "cli.py").read_text() == "# original\n"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/boundaries/test_apply.py::test_apply_hotspot_squash_merges_when_tests_pass tests/boundaries/test_apply.py::test_apply_hotspot_reverts_when_tests_fail -v
```

Expected: AttributeError — `apply_hotspot` not defined.

- [ ] **Step 3: Implement `apply_hotspot` in `apply.py`**

Append to `claw_forge/boundaries/apply.py`:

```python
import asyncio
import logging
from typing import Any

from claw_forge.boundaries.refactor import run_refactor_subagent
from claw_forge.boundaries.scorer import Hotspot
from claw_forge.git.branching import create_worktree, remove_worktree
from claw_forge.git.merge import squash_merge
from claw_forge.git.slug import make_slug

_log = logging.getLogger("claw_forge.boundaries.apply")


def apply_hotspot(
    hotspot: Hotspot,
    *,
    project_dir: Path,
    test_command: str,
) -> dict[str, Any]:
    """Run a single hotspot's refactor in a worktree, gate on tests, merge or revert.

    Returns a dict with ``status`` ∈ {"merged", "reverted", "skipped"} and
    diagnostic detail.
    """
    slug = make_slug("boundaries-" + hotspot.path.replace("/", "-").replace(".", "-"))
    branch_name, worktree_path = create_worktree(
        project_dir, task_id=slug, slug=slug, prefix="boundaries"
    )
    try:
        # Run the subagent inside the worktree; it edits files there.
        try:
            asyncio.run(
                run_refactor_subagent(hotspot, project_dir=worktree_path)
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning("subagent error on %s: %s", hotspot.path, exc)
            remove_worktree(project_dir, worktree_path)
            return {"status": "skipped", "reason": f"subagent error: {exc}"}
        # Stage everything the subagent did and commit on the boundaries branch.
        subprocess.run(["git", "add", "-A"], cwd=worktree_path, check=True)
        commit_proc = subprocess.run(
            ["git", "commit", "--no-verify", "-m",
             f"boundaries({hotspot.path}): extract {hotspot.pattern}"],
            cwd=worktree_path, capture_output=True, text=True,
        )
        if commit_proc.returncode != 0:
            # Nothing changed — subagent produced no edits.
            remove_worktree(project_dir, worktree_path)
            return {"status": "skipped", "reason": "no changes"}
        # Run tests INSIDE the worktree so we test the refactored code.
        passed = run_test_command(test_command, cwd=worktree_path)
        if not passed:
            remove_worktree(project_dir, worktree_path)
            # Branch still exists — clean it up too
            subprocess.run(
                ["git", "branch", "-D", branch_name],
                cwd=project_dir, check=False,
            )
            return {"status": "reverted", "reason": "tests failed"}
        # Tests green → squash-merge into project_dir's main branch.
        merge = squash_merge(
            project_dir, branch_name,
            title=f"boundaries: refactor {hotspot.path} ({hotspot.pattern})",
            worktree_path=worktree_path,
        )
        if not merge.get("merged"):
            return {"status": "skipped", "reason": f"merge failed: {merge.get('error', '')}"}
        return {"status": "merged", "commit_hash": merge.get("commit_hash", "")}
    except Exception as exc:  # noqa: BLE001
        try:
            remove_worktree(project_dir, worktree_path)
        except Exception:  # noqa: BLE001
            pass
        return {"status": "skipped", "reason": f"unexpected error: {exc}"}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/boundaries/test_apply.py -v
```

Expected: PASS for both new tests + the earlier `run_test_command` tests.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/boundaries/apply.py tests/boundaries/test_apply.py
git commit -m "feat(boundaries): apply_hotspot lifecycle with test gating + merge/revert"
```

---

### Task 15: Apply CLI command

**Files:**
- Modify: `claw_forge/boundaries/cli.py`
- Modify: `tests/boundaries/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/boundaries/test_cli.py`:

```python
def test_boundaries_apply_runs_hotspots_from_existing_report(
    tmp_path: Path, monkeypatch,
) -> None:
    """``boundaries apply`` reads boundaries_report.md and runs apply_hotspot
    on each, in --auto mode (no prompts)."""
    import subprocess as sp
    sp.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    sp.run(["git", "config", "user.email", "t@t.x"], cwd=tmp_path, check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "cli.py").write_text("# original\n")
    (tmp_path / "test.sh").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "test.sh").chmod(0o755)
    sp.run(["git", "add", "."], cwd=tmp_path, check=True)
    sp.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    # Pre-write a report
    (tmp_path / "boundaries_report.md").write_text(
        "# Boundaries Audit — test\n\n1 hotspot\n\n"
        "## 1. cli.py  (score 8.7)\n"
        "- signals: dispatch=10, import=5, churn=7, function=2\n"
        "**Proposed pattern:** registry\n\n"
    )
    calls: list[str] = []
    async def fake_run_refactor(h, *, project_dir):
        (project_dir / "cli.py").write_text("# refactored\n")
        calls.append(h.path)
        return {"changes_made": True}
    monkeypatch.setattr(
        "claw_forge.boundaries.apply.run_refactor_subagent", fake_run_refactor,
    )
    runner = CliRunner()
    result = runner.invoke(
        app, [
            "boundaries", "apply",
            "--project", str(tmp_path),
            "--auto",
            "--test-command", "./test.sh",
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls == ["cli.py"]
    assert (tmp_path / "cli.py").read_text() == "# refactored\n"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/boundaries/test_cli.py::test_boundaries_apply_runs_hotspots_from_existing_report -v
```

Expected: typer error or test failure — `apply` subcommand not yet defined.

- [ ] **Step 3: Add `apply` command to `boundaries/cli.py`**

Append to `claw_forge/boundaries/cli.py`:

```python
@boundaries_app.command()
def apply(
    project: Path = typer.Option(
        Path.cwd(), "--project", help="Project root to apply (default: CWD)"
    ),
    test_command: str = typer.Option(
        "uv run pytest tests/ -q",
        "--test-command",
        help="Test command (run inside each refactor's worktree)",
    ),
    hotspot: str | None = typer.Option(
        None, "--hotspot", help="Apply only this one hotspot (path)"
    ),
    auto: bool = typer.Option(
        False, "--auto", help="No prompts; apply all hotspots above threshold"
    ),
) -> None:
    """Apply hotspot refactors from boundaries_report.md, gated by tests."""
    from claw_forge.boundaries.apply import apply_hotspot
    from claw_forge.boundaries.report import parse_report

    project = project.resolve()
    report_path = project / "boundaries_report.md"
    if not report_path.exists():
        # Auto-run audit if report missing.
        from claw_forge.boundaries.audit import run_audit
        from claw_forge.boundaries.report import emit_report
        spots = run_audit(project)
        emit_report(spots, out_path=report_path, project_name=project.name)
    hotspots = parse_report(report_path)
    if hotspot:
        hotspots = [h for h in hotspots if h.path == hotspot]
        if not hotspots:
            typer.echo(f"No hotspot named {hotspot!r} in report.")
            raise typer.Exit(code=1)
    n_merged = n_reverted = n_skipped = 0
    for h in hotspots:
        if not auto:
            typer.echo(f"\nNext: {h.path} (score {h.score:.1f}, pattern={h.pattern})")
            if not typer.confirm("Apply?", default=False):
                n_skipped += 1
                continue
        result = apply_hotspot(h, project_dir=project, test_command=test_command)
        status = result["status"]
        if status == "merged":
            n_merged += 1
        elif status == "reverted":
            n_reverted += 1
        else:
            n_skipped += 1
        typer.echo(f"  {h.path}: {status} ({result.get('reason', '')})")
    typer.echo(
        f"\nDone. {n_merged} merged, {n_reverted} reverted, {n_skipped} skipped."
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/boundaries/test_cli.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/boundaries/cli.py tests/boundaries/test_cli.py
git commit -m "feat(cli): claw-forge boundaries apply --auto / --hotspot / interactive"
```

---

### Task 16: Status command

**Files:**
- Modify: `claw_forge/boundaries/cli.py`
- Modify: `tests/boundaries/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/boundaries/test_cli.py`:

```python
def test_boundaries_status_shows_report_summary(tmp_path: Path) -> None:
    (tmp_path / "boundaries_report.md").write_text(
        "# Boundaries Audit — myapp\n\n2 hotspots\n\n"
        "## 1. cli.py  (score 8.7)\n"
        "- signals: dispatch=10, import=5, churn=7, function=2\n"
        "**Proposed pattern:** registry\n\n"
        "## 2. parser.py  (score 6.0)\n"
        "- signals: dispatch=4, import=3, churn=2, function=1\n"
        "**Proposed pattern:** route_table\n\n"
    )
    runner = CliRunner()
    result = runner.invoke(app, ["boundaries", "status", "--project", str(tmp_path)])
    assert result.exit_code == 0
    assert "cli.py" in result.output
    assert "parser.py" in result.output
    assert "8.7" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/boundaries/test_cli.py::test_boundaries_status_shows_report_summary -v
```

Expected: typer error.

- [ ] **Step 3: Add `status` command**

Append to `claw_forge/boundaries/cli.py`:

```python
@boundaries_app.command()
def status(
    project: Path = typer.Option(
        Path.cwd(), "--project", help="Project root (default: CWD)"
    ),
) -> None:
    """Show the most recent audit's hotspot list."""
    from claw_forge.boundaries.report import parse_report

    report_path = project.resolve() / "boundaries_report.md"
    if not report_path.exists():
        typer.echo("No boundaries_report.md — run `claw-forge boundaries audit` first.")
        raise typer.Exit(code=1)
    hotspots = parse_report(report_path)
    typer.echo(f"{len(hotspots)} hotspot(s) in {report_path}:")
    for h in hotspots:
        typer.echo(
            f"  {h.path:40s}  score={h.score:5.1f}  pattern={h.pattern or '?'}"
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/boundaries/test_cli.py::test_boundaries_status_shows_report_summary -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add claw_forge/boundaries/cli.py tests/boundaries/test_cli.py
git commit -m "feat(cli): claw-forge boundaries status"
```

---

## Phase C — Polish (Tasks 17-18)

### Task 17: End-to-end integration test on a synthetic project

**Files:**
- Modify: `tests/boundaries/test_apply.py`

- [ ] **Step 1: Write the integration test**

Append to `tests/boundaries/test_apply.py`:

```python
def test_end_to_end_audit_then_apply_on_synthetic_dispatcher(
    tmp_path: Path, monkeypatch,
) -> None:
    """Audit identifies a dispatcher hotspot; apply (with stubbed subagent)
    refactors it; tests stay green; squash-merged on main."""
    import subprocess as sp
    sp.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    sp.run(["git", "config", "user.email", "t@t.x"], cwd=tmp_path, check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    cli = tmp_path / "main.py"
    cli.write_text(
        "\n".join(
            f"{'if' if i == 0 else 'elif'} cmd == 'c{i}':\n    do_c{i}()" for i in range(8)
        ) + "\n"
    )
    (tmp_path / "test.sh").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "test.sh").chmod(0o755)
    sp.run(["git", "add", "."], cwd=tmp_path, check=True)
    sp.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    # Audit
    from claw_forge.boundaries.audit import run_audit
    from claw_forge.boundaries.report import emit_report
    spots = run_audit(tmp_path, min_score=2.0)
    emit_report(
        spots, out_path=tmp_path / "boundaries_report.md", project_name="syn",
    )
    assert any(h.path == "main.py" for h in spots)
    # Apply (stubbed subagent writes a "refactored" version)
    async def fake_run_refactor(h, *, project_dir):
        (project_dir / "main.py").write_text("# refactored — registry pattern\n")
        return {"changes_made": True}
    monkeypatch.setattr(
        "claw_forge.boundaries.apply.run_refactor_subagent", fake_run_refactor,
    )
    from claw_forge.boundaries.apply import apply_hotspot
    main_hotspot = next(h for h in spots if h.path == "main.py")
    main_hotspot.pattern = "registry"  # classifier is mocked
    result = apply_hotspot(
        main_hotspot, project_dir=tmp_path, test_command="./test.sh",
    )
    assert result["status"] == "merged"
    # Verify the refactored content landed on main
    assert (tmp_path / "main.py").read_text().startswith("# refactored")
```

- [ ] **Step 2: Run test to verify it passes**

```bash
uv run pytest tests/boundaries/test_apply.py::test_end_to_end_audit_then_apply_on_synthetic_dispatcher -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/boundaries/test_apply.py
git commit -m "test(boundaries): end-to-end audit → apply on synthetic dispatcher"
```

---

### Task 18: Lint, type-check, full suite, coverage gate

- [ ] **Step 1: Lint**

```bash
uv run ruff check claw_forge/ tests/
```

Expected: All checks passed!

- [ ] **Step 2: Type check**

```bash
uv run mypy claw_forge/ --ignore-missing-imports
```

Expected: Success: no issues found.

- [ ] **Step 3: Full test suite + coverage**

```bash
uv run pytest tests/ -q --cov=claw_forge --cov-report=term
```

Expected: all green; coverage ≥ 90%.

- [ ] **Step 4: Sanity-run the new commands locally**

```bash
uv run claw-forge boundaries --help
uv run claw-forge boundaries audit --help
uv run claw-forge boundaries apply --help
uv run claw-forge boundaries status --help
```

Expected: help output for each subcommand.

- [ ] **Step 5: No commit needed if all clean**

---

## Self-Review

**Spec coverage:**
- ✅ Audit: walker + 4 signals + scorer + classifier + report (Tasks 2-10)
- ✅ Apply: refactor subagent + test gating + apply lifecycle (Tasks 12-14)
- ✅ CLI: audit / apply / status (Tasks 11, 15, 16)
- ✅ End-to-end test (Task 17)
- ✅ Lint / types / coverage (Task 18)
- ⚠ **Out of scope items deliberately not implemented:** cross-language refactor heuristics, multi-hotspot fusion, `boundaries undo`, auto-suggestion in `/create-spec`, reverting refactors automatically. All listed in the spec's "Out of scope" section.

**Placeholder scan:** none.

**Type consistency:**
- `Hotspot.path: str` (relative path); `score: float`; `signals: dict[str, int]`; `pattern: str` — consistent across walker → scorer → report → apply.
- `apply_hotspot` returns `{"status": str, ...}` with `status ∈ {"merged", "reverted", "skipped"}` — used identically in CLI command.
- `run_refactor_subagent` is async; `apply_hotspot` is sync and uses `asyncio.run` to bridge — consistent with how other claw-forge code bridges async/sync.

**Notes for the implementer:**
- **Task 9** (classifier) and **Task 12** (refactor) both call into `claw_forge/agent/runner.py`. Confirm the existing `run_agent` and `collect_structured_result` signatures with `grep -n` before relying on them; the helper signatures shown in the plan match the snapshots from earlier code reading but the runner may have evolved.
- **Task 14**'s `apply_hotspot` uses claw-forge's existing `create_worktree`, `squash_merge`, and `remove_worktree` — these are battle-tested. Re-using them means refactor commits land via the same pipeline that fixed v0.5.24/v0.5.27, so their fixes apply automatically.
- **All subagent invocations are mocked in tests**. Real-world validation happens during dogfooding (run `claw-forge boundaries audit` against the claw-forge repo itself, then `apply` against a non-critical hotspot like `cli.py` if one is identified).

**Critical safety note for the implementer:**
- Do **not** run `claw-forge boundaries apply --auto` against `claw-forge` itself or `agent-trading-arena` until you've reviewed the audit report by hand and the test suite is fast (<5 min). The first apply on a real codebase should be `--hotspot=<one_known_safe_file>` to validate end-to-end before unleashing autonomous mode.
