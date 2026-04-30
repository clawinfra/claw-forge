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
