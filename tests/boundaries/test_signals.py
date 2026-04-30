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
