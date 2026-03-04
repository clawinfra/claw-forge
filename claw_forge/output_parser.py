"""Parse code blocks from LLM output and write them to disk.

Used in API-only mode (BUG-11 fix) where the LLM generates code but there is
no claude CLI agent to write files.  Extracts fenced code blocks annotated
with a filename and writes each to the project directory.

Supported formats::

    ```path/to/file.py
    <code>
    ```

    ```python:path/to/file.py
    <code>
    ```

    ```python path/to/file.py
    <code>
    ```

When a code block's info string is just a language tag (e.g. ``python``,
``javascript``) with no filename, the block is skipped — we cannot determine
where to write it.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Match fenced code blocks: ```<info>\n<content>\n```
_CODE_BLOCK_RE = re.compile(
    r"```([^\n]*)\n(.*?)```",
    re.DOTALL,
)

# Language-only info strings that should NOT be treated as filenames
_LANG_ONLY = frozenset({
    "python", "py", "javascript", "js", "typescript", "ts", "tsx", "jsx",
    "rust", "rs", "go", "java", "c", "cpp", "h", "hpp", "css", "html",
    "xml", "json", "yaml", "yml", "toml", "ini", "cfg", "sql", "sh",
    "bash", "zsh", "fish", "powershell", "ps1", "ruby", "rb", "perl",
    "pl", "lua", "r", "swift", "kotlin", "kt", "scala", "clojure",
    "haskell", "hs", "elixir", "ex", "erlang", "erl", "dart", "vue",
    "svelte", "markdown", "md", "text", "txt", "diff", "patch",
    "dockerfile", "makefile", "cmake", "protobuf", "proto", "graphql",
    "gql", "csv", "plaintext", "console", "output", "log", "env",
})


def _parse_filename(info_string: str) -> str | None:
    """Extract a filename from a code block info string.

    Returns None if the info string is just a language tag.

    Examples:
        >>> _parse_filename("path/to/file.py")
        'path/to/file.py'
        >>> _parse_filename("python:path/to/file.py")
        'path/to/file.py'
        >>> _parse_filename("python path/to/file.py")
        'path/to/file.py'
        >>> _parse_filename("python")
        >>> _parse_filename("")
    """
    info = info_string.strip()
    if not info:
        return None

    # Format: lang:path/to/file
    if ":" in info:
        parts = info.split(":", 1)
        candidate = parts[1].strip()
        if candidate and ("/" in candidate or "." in candidate):
            return candidate

    # Format: lang path/to/file
    if " " in info:
        parts = info.split(None, 1)
        candidate = parts[1].strip()
        if candidate and ("/" in candidate or "." in candidate):
            return candidate

    # Format: path/to/file (no language prefix)
    # Check if it looks like a path (contains / or .)
    if info.lower() in _LANG_ONLY:
        return None

    if "/" in info or "." in info:
        # Must have a file extension (e.g. .py, .ts) or explicit path separator
        # Reject bare shell commands like "path/to/check" or "path/to/file"
        stem = info.rsplit("/", 1)[-1]  # last component
        if "/" in info and "." not in stem:
            # Looks like a shell command path, not a source file — skip
            return None
        return info

    return None


def extract_code_blocks(text: str) -> list[tuple[str, str]]:
    """Extract (filename, content) pairs from fenced code blocks.

    Only returns blocks where a filename could be determined.
    """
    results: list[tuple[str, str]] = []
    for match in _CODE_BLOCK_RE.finditer(text):
        info_string = match.group(1)
        content = match.group(2)
        filename = _parse_filename(info_string)
        if filename is not None:
            results.append((filename, content))
    return results


def write_code_blocks(
    text: str,
    project_dir: str | Path,
) -> list[str]:
    """Parse code blocks from LLM output and write files to disk.

    Args:
        text: Raw LLM output containing fenced code blocks.
        project_dir: Root directory to write files relative to.

    Returns:
        List of file paths (relative) that were written.
    """
    project_path = Path(project_dir)
    blocks = extract_code_blocks(text)
    written: list[str] = []

    for filename, content in blocks:
        # Security: prevent path traversal
        clean_path = Path(filename)
        if clean_path.is_absolute():
            logger.warning("Skipping absolute path: %s", filename)
            continue
        try:
            resolved = (project_path / clean_path).resolve()
            if not str(resolved).startswith(str(project_path.resolve())):
                logger.warning("Path traversal detected, skipping: %s", filename)
                continue
        except (ValueError, OSError):
            logger.warning("Invalid path, skipping: %s", filename)
            continue

        target = project_path / clean_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(str(clean_path))
        logger.info("Wrote %s (%d bytes)", clean_path, len(content))

    return written
