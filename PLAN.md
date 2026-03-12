# PLAN: Hashline Edit Mode

**Issue:** clawinfra/claw-forge#2
**PR title:** `feat: hashline edit mode — 10x improvement for weak models`
**Closes:** #2
**Benchmark reference:** 6.7% → 68.3% (Grok Code Fast, can1357 benchmark)

---

## 1. Architecture Overview + Data Flow

### Core Concept

Hashline wraps file read/write operations with content-addressed line tagging. Each line gets a short hash derived from its stripped content. Agents reference lines by hash instead of reproducing exact text, eliminating whitespace/indentation errors that plague `str_replace` on weaker models.

### Data Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                         CLI layer                                 │
│  `claw-forge run --edit-mode hashline`                            │
│   stores edit_mode in config context                              │
└─────────────────────────┬────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Agent Runner (runner.py)                        │
│  Receives edit_mode from caller                                   │
│  If edit_mode == "hashline":                                      │
│    1. Prepends hashline tool instructions to system_prompt        │
│    2. Agent reads files → hashline.annotate() → tagged output     │
│    3. Agent emits edit ops referencing hashes                     │
│    4. hashline.apply_edits() validates + applies                 │
└─────────────────────────┬────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                    hashline.py (NEW)                               │
│                                                                    │
│  annotate(content: str) → str                                     │
│    • Split lines, compute sha256 hash (3 hex chars) per line      │
│    • Handle collisions: a3f, a3f_2, a3f_3                         │
│    • Return: "a3f|def hello():\n7b2|  return 'world'\n"           │
│                                                                    │
│  apply_edits(original: str, edits: list[EditOp]) → str            │
│    • Validate all hashes exist in the current file                │
│    • Apply replace/insert_after/delete operations                 │
│    • Re-hash after each edit for cascading operations             │
│    • Raise HashlineError on invalid hash / collision conflict     │
│                                                                    │
│  read_file_annotated(path: Path) → str                            │
│    • Read file from disk, return annotate(content)                │
│                                                                    │
│  write_file_with_edits(path: Path, edits: list[EditOp]) → str    │
│    • Read current file, apply_edits(), write result back          │
│    • Return the new annotated content for agent's context         │
└──────────────────────────────────────────────────────────────────┘
```

### Integration Points

The hashline module is a **pure library** with no dependencies on the rest of claw-forge beyond being called by the agent layer. It does NOT become an MCP tool or SDK plugin — it's injected via system prompt instructions that tell the agent how to use the existing `Read`, `Write`, and `Edit` tools with hashline-aware wrappers.

**How it integrates with the existing agent flow:**

1. **CLI** (`cli.py`): The `run` command gains `--edit-mode` option. The value is passed through to the orchestrator → task handler → agent runner.

2. **Agent runner** (`agent/runner.py`): When `edit_mode="hashline"`, the runner prepends hashline instructions to the system prompt. These instructions tell the agent:
   - When using `Read`, the output will be hashline-annotated
   - When using `Edit`, provide hash references instead of exact text
   - The format for replace/insert_after/delete operations

3. **Hooks** (`agent/hooks.py`): A new `PostToolUse` hook intercepts `Read` tool results and passes them through `hashline.annotate()` before the agent sees them. A `PreToolUse` hook for `Edit` intercepts edit requests, parses hashline references, and translates them to exact line operations via `hashline.apply_edits()`.

4. **Config** (`claw-forge.yaml`): An `edit_mode` field under the `agent` section allows persistent configuration.

---

## 2. File Structure with Exact Function Signatures

### New Files

#### `claw_forge/hashline.py`

```python
"""Hashline edit mode — content-addressed line tagging for robust file editing.

Each line is tagged with a 3-character hex hash derived from sha256(line.strip()).
Agents reference lines by hash instead of reproducing exact text, eliminating
whitespace/indentation errors on weaker models.

Benchmark: 6.7% → 68.3% success rate on Grok Code Fast (can1357).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


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
    ...


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
    ...


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
    ...


def read_file_annotated(path: Path | str) -> str:
    """Read a file from disk and return its hashline-annotated content.
    
    Args:
        path: Path to the file to read.
        
    Returns:
        The file content with each line prefixed by its hash tag.
        
    Raises:
        FileNotFoundError: If path does not exist.
        IsADirectoryError: If path is a directory.
    """
    ...


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
    ...


def build_system_prompt_fragment() -> str:
    """Return the system prompt fragment that teaches an agent how to use hashline mode.
    
    This text is prepended to the agent's system prompt when edit_mode="hashline".
    It explains the hash format, how to read annotated output, and how to
    construct edit operations.
    
    Returns:
        A multi-line string with hashline usage instructions.
    """
    ...


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
    ...
```

#### `tests/test_hashline.py`

```python
"""Tests for claw_forge.hashline — hashline edit mode."""
from __future__ import annotations
# Full test cases listed in section 6 below.
```

### Modified Files

#### `claw_forge/cli.py`

- Add `--edit-mode` option to the `run` command (type: `str`, choices: `["str_replace", "hashline"]`, default: `"str_replace"`)
- Pass `edit_mode` through to the task handler and ultimately to `run_agent()`

#### `claw_forge/agent/runner.py`

- Add `edit_mode: str = "str_replace"` parameter to `run_agent()` and `collect_result()`
- When `edit_mode == "hashline"`:
  - Import `build_system_prompt_fragment()` from `claw_forge.hashline`
  - Prepend the hashline system prompt fragment to any existing `system_prompt`

#### `claw_forge/agent/hooks.py`

- Add a new hook factory `hashline_read_hook()` that returns a `PostToolUse` hook for `Read`:
  - Intercepts the `Read` tool result
  - Passes the content through `hashline.annotate()`
  - Returns the annotated version to the agent
- Add a new hook factory `hashline_edit_hook()` that returns a `PreToolUse` hook for `Edit`:
  - Intercepts `Edit` tool requests
  - If the edit contains hashline references (`HASHLINE_EDIT` markers), parse them via `parse_edit_ops()`
  - Translate hash-referenced edits into exact text replacements using `apply_edits()`
  - Pass the translated edit to the SDK
- Add `get_hashline_hooks()` function that returns the combined list of hashline hooks
- Modify `get_default_hooks()` to accept an optional `edit_mode` parameter; when `"hashline"`, include hashline hooks

#### `claw_forge/plugins/coding.py`

- Modify `get_system_prompt()` to accept `edit_mode` from context metadata
- When `edit_mode == "hashline"`, append hashline instructions to the system prompt

---

## 3. Interface Definitions (API, CLI, Config)

### CLI Interface

```
claw-forge run [OPTIONS]
  --edit-mode TEXT    Edit tool mode for agent file operations.
                      str_replace: current default (exact text matching)
                      hashline: content-addressed line tagging (better for weak models)
                      [default: str_replace]
```

The `--edit-mode` flag is added to the `run` command only. It does not apply to `init`, `plan`, `status`, `fix`, or `add` (those commands don't execute coding agents, or in the case of `fix`, we can add it later).

### Config Interface (claw-forge.yaml)

```yaml
agent:
  default_model: claude-sonnet-4-6
  max_tokens: 8192
  max_concurrent_agents: 5
  edit_mode: str_replace    # NEW: str_replace | hashline
```

**Priority order:** CLI flag > config file > default ("str_replace").

### Python API

```python
# Direct usage of hashline module
from claw_forge.hashline import (
    annotate,
    apply_edits,
    read_file_annotated,
    write_file_with_edits,
    parse_edit_ops,
    build_system_prompt_fragment,
    EditOp,
    EditOpKind,
    HashlineError,
    compute_hash,
)

# Via agent runner
from claw_forge.agent.runner import run_agent
async for msg in run_agent(prompt, edit_mode="hashline", ...):
    ...
```

---

## 4. Data Models and Schemas

### EditOpKind (Enum)

| Value | Description |
|---|---|
| `replace` | Replace the target line with new content |
| `insert_after` | Insert new content after the target line |
| `delete` | Delete the target line |

### EditOp (Dataclass)

| Field | Type | Description |
|---|---|---|
| `kind` | `EditOpKind` | Operation type |
| `hash_ref` | `str` | 3-char hash with optional collision suffix (e.g., `"a3f"`, `"a3f_2"`) |
| `new_content` | `str` | New line content (empty for delete) |

### Hash Format

- **Hash computation:** `sha256(line.strip().encode("utf-8")).hexdigest()[:3]`
- **Hash tag format:** `<hash>|<original line content>` (no spaces around pipe)
- **Collision suffix:** `_2`, `_3`, ..., `_N` appended for duplicate hashes within same file
- **Empty lines:** Hash is computed on the empty string: `sha256(b"").hexdigest()[:3]` → `"e3b"`. If multiple empty lines exist, they get `"e3b"`, `"e3b_2"`, etc.

### Agent Edit Block Format

The agent will be instructed (via system prompt) to emit edits in this format:

```
HASHLINE_EDIT <file_path>
REPLACE <hash_ref>
<new_content_line_1>
<new_content_line_2>
...
END
INSERT_AFTER <hash_ref>
<new_content_line_1>
<new_content_line_2>
...
END
DELETE <hash_ref>
END
HASHLINE_EDIT_END
```

**Notes:**
- `<new_content>` between `REPLACE`/`INSERT_AFTER` and `END` can be multi-line.
- `DELETE` has no content between the hash line and `END`.
- Multiple operations in a single `HASHLINE_EDIT` block are applied top-to-bottom.
- File path is relative to the project root.

---

## 5. Error Handling Strategy

### Error Types

All errors raised from hashline.py use `HashlineError` (subclass of `Exception`).

| Error Condition | Message Format | Recovery |
|---|---|---|
| Hash not found | `"Hash '{hash_ref}' not found in file. Available hashes: ..."` | Agent sees error, re-reads file to get current hashes |
| Ambiguous hash | `"Hash '{hash_ref}' matches multiple lines. Use collision suffix: {hash_ref}_2, {hash_ref}_3"` | Agent uses suffixed version |
| Malformed edit block | `"Malformed edit block: expected REPLACE/INSERT_AFTER/DELETE, got '{line}'"` | Agent re-formats edit |
| Empty file | Return empty string from `annotate()` — NOT an error | N/A |
| File not found | Re-raise `FileNotFoundError` from `read_file_annotated()` | Agent checks path |
| Binary file | `"Cannot annotate binary file: {path}"` | Agent uses binary-aware tool |

### Hook Error Handling

- **PostToolUse (Read hook):** If `annotate()` raises (e.g., binary file), let the original unmodified content pass through. Log a warning but don't crash the agent.
- **PreToolUse (Edit hook):** If `parse_edit_ops()` or `apply_edits()` raises, return the error message to the agent as a tool error. The agent can then retry.

### Graceful Degradation

- If `edit_mode="hashline"` is set but the agent produces a normal `str_replace` style edit (no `HASHLINE_EDIT` markers), the edit passes through unchanged. The hashline hook is a **filter**, not a gate.
- Binary files are never annotated — the Read hook checks for null bytes in the first 8192 bytes and skips annotation.

---

## 6. Test Plan

### Test File: `tests/test_hashline.py`

Target: **≥90% line coverage** on `claw_forge/hashline.py`.

#### `compute_hash` tests

| Test | Description |
|---|---|
| `test_compute_hash_basic` | Simple string → 3-char hex output |
| `test_compute_hash_strips_whitespace` | `"  hello  "` and `"hello"` produce same hash |
| `test_compute_hash_empty_string` | Empty string produces a valid 3-char hash |
| `test_compute_hash_returns_3_chars` | Output is always exactly 3 hex characters |
| `test_compute_hash_deterministic` | Same input always produces same output |
| `test_compute_hash_different_inputs` | Different inputs produce different hashes (spot check, not guaranteed) |

#### `annotate` tests

| Test | Description |
|---|---|
| `test_annotate_single_line` | One line → `"<hash>\|<content>\n"` |
| `test_annotate_multiline` | Multiple lines each get their own hash |
| `test_annotate_empty_string` | Empty string → empty string |
| `test_annotate_empty_lines` | Blank lines get hashes (e3b hash of empty) |
| `test_annotate_preserves_content` | Content after the `\|` is unchanged (including indentation) |
| `test_annotate_collision_handling` | Two lines with same stripped content → `hash`, `hash_2` |
| `test_annotate_triple_collision` | Three identical lines → `hash`, `hash_2`, `hash_3` |
| `test_annotate_trailing_newline_preserved` | If input ends with `\n`, output does too |
| `test_annotate_no_trailing_newline` | If input doesn't end with `\n`, output doesn't either |
| `test_annotate_unicode` | Unicode content (CJK, emoji) is handled correctly |
| `test_annotate_tabs_and_spaces` | Lines with different whitespace but same stripped content collide |

#### `apply_edits` tests

| Test | Description |
|---|---|
| `test_apply_replace_single_line` | Replace one line by hash |
| `test_apply_replace_with_multiline` | Replace one line with multiple lines |
| `test_apply_insert_after` | Insert new content after a target line |
| `test_apply_insert_after_last_line` | Insert after the final line of file |
| `test_apply_delete` | Delete a line by hash |
| `test_apply_multiple_edits` | Apply replace + insert_after + delete in one batch |
| `test_apply_edits_preserves_untouched_lines` | Lines not referenced remain unchanged |
| `test_apply_edits_invalid_hash_raises` | Non-existent hash → `HashlineError` |
| `test_apply_edits_empty_edits_list` | Empty edit list → content unchanged |
| `test_apply_edits_collision_suffix` | Edit targeting `hash_2` hits the second occurrence |
| `test_apply_edits_delete_all_lines` | Delete every line → empty string |
| `test_apply_replace_empty_content` | Replace with empty string → effectively delete but leave empty line |
| `test_apply_edits_order_matters` | Sequential edits applied top-to-bottom |

#### `read_file_annotated` tests

| Test | Description |
|---|---|
| `test_read_file_annotated_basic` | Read a real file, verify annotated output |
| `test_read_file_annotated_nonexistent` | Missing file → `FileNotFoundError` |
| `test_read_file_annotated_directory` | Directory path → `IsADirectoryError` |
| `test_read_file_annotated_empty_file` | Empty file → empty string |
| `test_read_file_annotated_binary_detection` | File with null bytes → `HashlineError("Cannot annotate binary file")` |

#### `write_file_with_edits` tests

| Test | Description |
|---|---|
| `test_write_file_with_edits_basic` | Read + edit + write + verify file on disk |
| `test_write_file_with_edits_returns_annotated` | Return value is the new annotated content |
| `test_write_file_with_edits_nonexistent` | Missing file → `FileNotFoundError` |
| `test_write_file_with_edits_invalid_hash` | Bad hash → `HashlineError`, file unchanged |
| `test_write_file_with_edits_atomicity` | On error, original file is NOT modified |

#### `parse_edit_ops` tests

| Test | Description |
|---|---|
| `test_parse_single_replace` | Parse one REPLACE block |
| `test_parse_single_insert_after` | Parse one INSERT_AFTER block |
| `test_parse_single_delete` | Parse one DELETE block |
| `test_parse_multiple_ops` | Parse a block with all three op types |
| `test_parse_multiline_content` | REPLACE with multi-line new content |
| `test_parse_empty_text` | No HASHLINE_EDIT markers → empty list |
| `test_parse_malformed_raises` | Missing END marker → `HashlineError` |
| `test_parse_unknown_op_raises` | Unknown operation type → `HashlineError` |
| `test_parse_multiple_edit_blocks` | Multiple HASHLINE_EDIT blocks for different files (returns all ops) |

#### `build_system_prompt_fragment` tests

| Test | Description |
|---|---|
| `test_prompt_fragment_not_empty` | Returns non-empty string |
| `test_prompt_fragment_contains_hash_format` | Mentions the `\|` separator |
| `test_prompt_fragment_contains_edit_ops` | Mentions REPLACE, INSERT_AFTER, DELETE |
| `test_prompt_fragment_contains_example` | Contains at least one usage example |

#### Integration tests

| Test | Description |
|---|---|
| `test_roundtrip_annotate_edit_verify` | annotate → parse_edit_ops → apply_edits → verify content correct |
| `test_roundtrip_file_read_write` | read_file_annotated → construct edits → write_file_with_edits → read again → verify |
| `test_hashline_with_real_python_file` | Use a multi-function Python file as input, apply realistic edits |

#### CLI integration tests (in `tests/test_cli_commands.py` or new test file)

| Test | Description |
|---|---|
| `test_run_accepts_edit_mode_flag` | `claw-forge run --edit-mode hashline` doesn't error on parsing |
| `test_run_default_edit_mode` | Default is `str_replace` |
| `test_run_invalid_edit_mode` | Invalid value → error message |

---

## 7. Constraints and Assumptions

### Constraints

1. **No new dependencies.** hashline.py uses only `hashlib`, `dataclasses`, `enum`, `pathlib`, and `re` from the stdlib. No pip installs needed.

2. **Backward compatibility.** `--edit-mode str_replace` (the default) must produce identical behaviour to the current codebase. No existing test should break.

3. **The `claw_forge/hashline.py` file goes in the package root** — NOT in `claw_forge/agent/` or `claw_forge/tools/`. It's a utility module usable by any layer.

4. **Hook-based integration.** Hashline mode is implemented via SDK hooks (PostToolUse for Read, PreToolUse for Edit), NOT by modifying the SDK or adding new tools. This keeps the integration clean and reversible.

5. **System prompt injection.** The hashline instructions are prepended to the system prompt, not added as a separate tool description. The agent still uses the standard `Read` and `Edit` tools — the hooks transparently translate.

6. **Coverage ≥ 90%.** `tests/test_hashline.py` must achieve ≥90% line coverage on `claw_forge/hashline.py`. Run with `uv run pytest tests/test_hashline.py --cov=claw_forge.hashline --cov-report=term-missing`.

7. **All existing tests must pass.** Run `uv run pytest tests/ -x -q` before and after changes. Zero regressions.

8. **Python 3.11+ only.** Use modern typing syntax (`str | None`, `list[str]`).

9. **Package structure.** The module lives at `claw_forge/hashline.py` (flat, same level as `cli.py`, `lsp.py`, `output_parser.py`, `scaffold.py`). This follows the existing pattern of utility modules in the package root.

### Assumptions

1. **SHA256 is sufficient.** With 3 hex characters (4096 possible values) and typical file sizes (<1000 lines), collisions are manageable via the `_N` suffix scheme. For files with >500 lines, collision rate is ~6% which is handled automatically.

2. **Agents can follow structured output formats.** The `HASHLINE_EDIT` block format is simple enough for all models that support claw-forge (Claude, Grok, GLM, MiniMax, etc.).

3. **The hook system supports our use case.** We assume `PostToolUse` can modify tool results and `PreToolUse` can modify tool inputs. Based on the SDK hook architecture in `hooks.py`, this is confirmed.

4. **No concurrent file edits.** Hashline assumes single-agent-per-file at any point. The existing claw-forge dispatcher already ensures this via task dependency ordering.

5. **Text files only.** Hashline mode is designed for text files. Binary files (detected by null bytes in first 8KB) are passed through without annotation.

6. **The agent runner passes `edit_mode` to hooks.** This requires threading `edit_mode` through `ClaudeAgentOptions` metadata or passing it as a closure variable to hook factories. The plan uses hook factories that capture `edit_mode`.

### Out of Scope

- Benchmarking infrastructure (can1357's methodology replication) — separate PR
- Brownfield mode integration (`claw-forge add`, `claw-forge fix`) — separate PR  
- MCP tool integration (exposing hashline as an MCP tool) — not needed; hooks are cleaner
- UI changes (showing edit mode in Kanban board) — separate PR
- `claw-forge.yaml` schema validation for the new `edit_mode` field — use existing pattern

---

## Appendix: System Prompt Fragment (draft)

The `build_system_prompt_fragment()` function returns text similar to:

```
## Hashline Edit Mode

When you read files, each line is prefixed with a content hash:

```
a3f|def hello():
7b2|    return "world"
0e1|}
```

The hash (before the `|`) is a short identifier for that line's content. Use these hashes to reference lines when editing.

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
- `REPLACE <hash>` — replace the line matching <hash> with the content before END (can be multi-line)
- `INSERT_AFTER <hash>` — insert content after the line matching <hash>
- `DELETE <hash>` — remove the line matching <hash>

**Collision handling:** If two lines have the same hash, they'll be shown as `a3f`, `a3f_2`, etc. Use the suffixed version to target a specific occurrence.

**Important:** Always use the hashes from the most recent file read. If you edit a file, the hashes may change — re-read the file to get updated hashes.
```
