"""Hashline edit mode — content-addressed line tagging for robust file editing.

Each line is tagged with a 3-character hex hash derived from sha256(line.strip()).
Agents reference lines by hash instead of reproducing exact text, eliminating
whitespace/indentation errors on weaker models.

Benchmark: 6.7% → 68.3% success rate on Grok Code Fast (can1357).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class EditOpKind(str, Enum):
    """Types of hashline edit operations."""

    REPLACE = "replace"
    INSERT_AFTER = "insert_after"
    DELETE = "delete"


@dataclass
class EditOp:
    """A single hashline edit operation.

    Attributes:
        kind: The operation type (replace, insert_after, delete).
        hash_ref: The 3-char hash (with optional collision suffix) of the target line.
        new_content: The new line content for replace/insert_after. Ignored for delete.
    """

    kind: EditOpKind
    hash_ref: str
    new_content: str = ""


class HashlineError(Exception):
    """Raised when hashline operations fail (invalid hash, collision, etc.)."""

    pass


def compute_hash(line: str) -> str:
    """Compute the 3-character hex hash of a stripped line.

    Args:
        line: The line content (will be stripped before hashing).

    Returns:
        First 3 hex characters of sha256(line.strip()).
    """
    stripped = line.strip()
    return hashlib.sha256(stripped.encode("utf-8")).hexdigest()[:3]


def annotate(content: str) -> str:
    """Annotate each line of content with its hashline tag.

    Handles hash collisions by appending _2, _3, etc. to duplicate hashes
    within the same file.

    Args:
        content: The raw file content (multi-line string).

    Returns:
        Annotated content where each line is prefixed with its hash and a pipe:
        "a3f|original line content\\n"

    Examples:
        >>> annotate("def hello():\\n  return 'world'\\n")
        'xxx|def hello():\\nyyy|  return \\'world\\'\\n'
    """
    if not content:
        return ""

    # Determine whether the original content ends with a newline
    ends_with_newline = content.endswith("\n")

    # Split into lines (without trailing newline effect on the last item)
    lines = content[:-1].split("\n") if ends_with_newline else content.split("\n")

    # Build hash tags with collision handling
    hash_counts: dict[str, int] = {}
    annotated_lines: list[str] = []

    for line in lines:
        h = compute_hash(line)
        count = hash_counts.get(h, 0)
        hash_counts[h] = count + 1
        tag = h if count == 0 else f"{h}_{count + 1}"
        annotated_lines.append(f"{tag}|{line}")

    result = "\n".join(annotated_lines)
    if ends_with_newline:
        result += "\n"
    return result


def _build_hash_index(original: str) -> dict[str, int]:
    """Build a mapping from hash_ref → line index (0-based).

    Args:
        original: Raw file content.

    Returns:
        Dict mapping hash_ref tags to line indices.
    """
    ends_with_newline = original.endswith("\n")
    lines = original[:-1].split("\n") if ends_with_newline else original.split("\n")

    hash_counts: dict[str, int] = {}
    index: dict[str, int] = {}

    for i, line in enumerate(lines):
        h = compute_hash(line)
        count = hash_counts.get(h, 0)
        hash_counts[h] = count + 1
        tag = h if count == 0 else f"{h}_{count + 1}"
        index[tag] = i

    return index


def apply_edits(original: str, edits: list[EditOp]) -> str:
    """Apply a list of edit operations to annotated content.

    Edits are applied sequentially. After each edit, hashes are NOT
    recomputed — the caller must use the hash values from the annotated
    content they received from annotate() or read_file_annotated().

    Args:
        original: The raw (unannotated) file content.
        edits: Ordered list of edit operations to apply.

    Returns:
        The modified file content (unannotated).

    Raises:
        HashlineError: If a hash_ref does not match any line in the original.
        HashlineError: If a hash_ref is ambiguous (collision without suffix).
    """
    if not edits:
        return original

    ends_with_newline = original.endswith("\n")
    lines = original[:-1].split("\n") if ends_with_newline else original.split("\n")

    # Build initial hash index
    hash_index = _build_hash_index(original)

    # Apply edits sequentially, adjusting indices as needed
    # We work on a list and track offset caused by insertions/deletions
    result_lines = list(lines)
    offset = 0  # cumulative shift: insertions add, deletions subtract

    for op in edits:
        # Check if this is an ambiguous bare hash (collision exists but no suffix provided)
        # If hash_ref has no suffix (e.g., "abc") but "abc_2" exists, it's ambiguous
        if (
            "_" not in op.hash_ref  # bare hash, no suffix
            and f"{op.hash_ref}_2" in hash_index  # collision exists
        ):
            available = sorted(
                k for k in hash_index
                if k == op.hash_ref or k.startswith(f"{op.hash_ref}_")
            )
            raise HashlineError(
                f"Hash '{op.hash_ref}' matches multiple lines. "
                f"Use collision suffix: {', '.join(available)}"
            )

        # Resolve the hash_ref to original line index
        if op.hash_ref not in hash_index:
            available = list(hash_index.keys())[:10]
            raise HashlineError(
                f"Hash '{op.hash_ref}' not found in file. "
                f"Available hashes: {', '.join(available)}"
                + ("..." if len(hash_index) > 10 else "")
            )

        orig_idx = hash_index[op.hash_ref]
        current_idx = orig_idx + offset

        if op.kind == EditOpKind.REPLACE:
            new_lines_to_insert = op.new_content.splitlines() if op.new_content else [""]
            result_lines[current_idx : current_idx + 1] = new_lines_to_insert
            offset += len(new_lines_to_insert) - 1

        elif op.kind == EditOpKind.INSERT_AFTER:
            new_lines_to_insert = op.new_content.splitlines() if op.new_content else [""]
            insert_pos = current_idx + 1
            result_lines[insert_pos:insert_pos] = new_lines_to_insert
            offset += len(new_lines_to_insert)

        elif op.kind == EditOpKind.DELETE:
            result_lines.pop(current_idx)
            offset -= 1

    if not result_lines:
        return ""

    result = "\n".join(result_lines)
    if ends_with_newline:
        result += "\n"
    return result


def read_file_annotated(path: Path | str) -> str:
    """Read a file from disk and return its hashline-annotated content.

    Args:
        path: Path to the file to read.

    Returns:
        The file content with each line prefixed by its hash tag.

    Raises:
        FileNotFoundError: If path does not exist.
        IsADirectoryError: If path is a directory.
        HashlineError: If the file appears to be binary.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No such file or directory: '{p}'")
    if p.is_dir():
        raise IsADirectoryError(f"Is a directory: '{p}'")

    # Detect binary files by checking for null bytes in the first 8192 bytes
    raw = p.read_bytes()
    if b"\x00" in raw[:8192]:
        raise HashlineError(f"Cannot annotate binary file: {p}")

    content = p.read_text(encoding="utf-8")
    return annotate(content)


def write_file_with_edits(path: Path | str, edits: list[EditOp]) -> str:
    """Read a file, apply edits, write it back, and return the new annotated content.

    This is a convenience function combining read + apply_edits + write + annotate.

    Args:
        path: Path to the file to edit.
        edits: Ordered list of edit operations to apply.

    Returns:
        The new annotated content (post-edit) for the agent's context.

    Raises:
        FileNotFoundError: If path does not exist.
        HashlineError: If any edit operation fails validation.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No such file or directory: '{p}'")
    if p.is_dir():
        raise IsADirectoryError(f"Is a directory: '{p}'")

    # Read original content first
    raw = p.read_bytes()
    if b"\x00" in raw[:8192]:
        raise HashlineError(f"Cannot annotate binary file: {p}")

    original = p.read_text(encoding="utf-8")

    # Apply edits — may raise HashlineError; file is NOT written on failure
    new_content = apply_edits(original, edits)

    # Write only after successful edit application
    p.write_text(new_content, encoding="utf-8")

    return annotate(new_content)


def build_system_prompt_fragment() -> str:
    """Return the system prompt fragment that teaches an agent how to use hashline mode.

    This text is prepended to the agent's system prompt when edit_mode="hashline".
    It explains the hash format, how to read annotated output, and how to
    construct edit operations.

    Returns:
        A multi-line string with hashline usage instructions.
    """
    return """\
## Hashline Edit Mode

When you read files, each line is prefixed with a content hash:

```
a3f|def hello():
7b2|    return "world"
0e1|}
```

The hash (before the `|`) is a short identifier for that line's content.
Use these hashes to reference lines when editing.

### Reading Files
Use the `Read` tool normally. The output will be hashline-annotated automatically.

### Editing Files
Instead of reproducing exact text, reference lines by hash. Use this format:

```
HASHLINE_EDIT path/to/file.py
REPLACE a3f
def hello(name: str):
END
INSERT_AFTER 7b2
    print(f"Hello {name}")
END
DELETE 0e1
END
HASHLINE_EDIT_END
```

**Operations:**
- `REPLACE <hash>` — replace the line matching <hash> with content before END (multi-line ok)
- `INSERT_AFTER <hash>` — insert content after the line matching <hash>
- `DELETE <hash>` — remove the line matching <hash>

**Collision handling:** If two lines have the same hash, they'll be shown as `a3f`, `a3f_2`,
etc. Use the suffixed version to target a specific occurrence.

**Important:** Always use the hashes from the most recent file read. If you edit a file,
the hashes may change — re-read the file to get updated hashes.
"""


def parse_edit_ops(text: str) -> list[EditOp]:
    """Parse edit operations from agent output text.

    Expects a structured format emitted by the agent:

        HASHLINE_EDIT file_path
        REPLACE hash_ref
        new line content here
        END
        INSERT_AFTER hash_ref
        new line content here
        END
        DELETE hash_ref
        END
        HASHLINE_EDIT_END

    Args:
        text: Raw agent output text containing edit blocks.

    Returns:
        List of parsed EditOp instances.

    Raises:
        HashlineError: If the edit block format is malformed.
    """
    ops: list[EditOp] = []

    # Find all HASHLINE_EDIT ... HASHLINE_EDIT_END blocks
    block_pattern = re.compile(
        r"HASHLINE_EDIT\s+\S+\n(.*?)HASHLINE_EDIT_END",
        re.DOTALL,
    )

    blocks = block_pattern.findall(text)
    if not blocks:
        # Check if there's a HASHLINE_EDIT without HASHLINE_EDIT_END (malformed)
        if "HASHLINE_EDIT" in text and "HASHLINE_EDIT_END" not in text:
            raise HashlineError("Malformed edit block: missing HASHLINE_EDIT_END marker")
        return ops

    valid_ops = {"REPLACE", "INSERT_AFTER", "DELETE"}

    for block in blocks:
        # Parse individual operations within the block
        lines = block.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            # Expect REPLACE/INSERT_AFTER/DELETE <hash_ref>
            parts = line.split(None, 1)
            if len(parts) < 2:
                i += 1
                continue

            op_name = parts[0].upper()
            if op_name not in valid_ops:
                if op_name == "END" or op_name == "HASHLINE_EDIT_END":
                    i += 1
                    continue
                raise HashlineError(
                    f"Malformed edit block: expected REPLACE/INSERT_AFTER/DELETE, got '{line}'"
                )

            hash_ref = parts[1].strip()
            i += 1

            # Collect content lines until END
            content_lines: list[str] = []
            found_end = False
            while i < len(lines):
                content_line = lines[i]
                stripped = content_line.strip()
                if stripped == "END":
                    found_end = True
                    i += 1
                    break
                content_lines.append(content_line)
                i += 1

            if not found_end:
                raise HashlineError(
                    f"Malformed edit block: missing END marker after {op_name} {hash_ref}"
                )

            # Remove trailing empty lines from content
            while content_lines and not content_lines[-1].strip():
                content_lines.pop()

            new_content = "\n".join(content_lines)

            if op_name == "REPLACE":
                ops.append(
                    EditOp(kind=EditOpKind.REPLACE, hash_ref=hash_ref, new_content=new_content)
                )
            elif op_name == "INSERT_AFTER":
                ops.append(
                    EditOp(kind=EditOpKind.INSERT_AFTER, hash_ref=hash_ref, new_content=new_content)
                )
            elif op_name == "DELETE":
                ops.append(EditOp(kind=EditOpKind.DELETE, hash_ref=hash_ref, new_content=""))

    return ops
