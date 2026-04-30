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
