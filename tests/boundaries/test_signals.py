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


def test_recent_churn_counts_distinct_branches_touching_file(tmp_path: Path) -> None:
    """A file modified across N distinct branches in the last 90 days, plus
    main (which contains the initial commit), reports churn = N + 1.

    Including main is harmless for ranking — it adds a constant +1 to every
    file that's been committed at all, so relative scores are unchanged.
    """
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
        sp.run(
            ["git", "commit", "-q", "-m", f"edit on {branch}"],
            cwd=tmp_path, check=True,
        )
        sp.run(["git", "checkout", "-q", "main"], cwd=tmp_path, check=True)
    from claw_forge.boundaries.signals import recent_churn
    # 3 feature branches + main (which contains the initial commit) = 4.
    assert recent_churn(target, repo_root=tmp_path, since_days=90) == 4


def test_recent_churn_zero_for_unmodified_file(tmp_path: Path) -> None:
    """A file modified only on the initial commit (no branches diverging)
    reports churn = 1 (just the main branch).
    """
    import subprocess as sp
    sp.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    sp.run(["git", "config", "user.email", "t@t.x"], cwd=tmp_path, check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    target = tmp_path / "stable.py"
    target.write_text("CONST = 1\n")
    sp.run(["git", "add", "."], cwd=tmp_path, check=True)
    sp.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    from claw_forge.boundaries.signals import recent_churn
    # The init commit is on main, so churn = 1 (one branch contains it).
    assert recent_churn(target, repo_root=tmp_path, since_days=90) == 1


def test_function_centrality_counts_call_sites(tmp_path: Path) -> None:
    """For each top-level public function in target, count call sites in
    other files."""
    target = tmp_path / "util.py"
    target.write_text("def helper():\n    pass\n\ndef rare():\n    pass\n")
    (tmp_path / "a.py").write_text(
        "from util import helper\nhelper()\nhelper()\n"
    )
    (tmp_path / "b.py").write_text("from util import helper\nhelper()\n")
    (tmp_path / "c.py").write_text("# nothing\n")
    from claw_forge.boundaries.signals import function_centrality
    score = function_centrality(
        target,
        [tmp_path / "a.py", tmp_path / "b.py", tmp_path / "c.py"],
    )
    # ``helper()`` appears in 2 distinct other files; ``rare()`` in 0.
    assert score == 2


def test_function_centrality_skips_private_functions(tmp_path: Path) -> None:
    """Functions whose names start with ``_`` don't contribute to centrality."""
    target = tmp_path / "util.py"
    target.write_text("def _internal():\n    pass\n")
    (tmp_path / "a.py").write_text("from util import _internal\n_internal()\n")
    from claw_forge.boundaries.signals import function_centrality
    assert function_centrality(target, [tmp_path / "a.py"]) == 0
