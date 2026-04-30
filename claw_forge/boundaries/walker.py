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
