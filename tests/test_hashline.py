"""Tests for claw_forge.hashline — hashline edit mode."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from claw_forge.hashline import (
    EditOp,
    EditOpKind,
    HashlineError,
    annotate,
    apply_edits,
    build_system_prompt_fragment,
    compute_hash,
    parse_edit_ops,
    read_file_annotated,
    write_file_with_edits,
)

# ── compute_hash tests ────────────────────────────────────────────────────────


class TestComputeHash:
    def test_compute_hash_basic(self) -> None:
        """Simple string → 3-char hex output."""
        result = compute_hash("hello")
        assert len(result) == 3
        assert all(c in "0123456789abcdef" for c in result)

    def test_compute_hash_strips_whitespace(self) -> None:
        """'  hello  ' and 'hello' produce same hash."""
        assert compute_hash("  hello  ") == compute_hash("hello")

    def test_compute_hash_empty_string(self) -> None:
        """Empty string produces a valid 3-char hash."""
        result = compute_hash("")
        assert len(result) == 3
        assert all(c in "0123456789abcdef" for c in result)
        # sha256("") starts with e3b
        expected = hashlib.sha256(b"").hexdigest()[:3]
        assert result == expected

    def test_compute_hash_returns_3_chars(self) -> None:
        """Output is always exactly 3 hex characters."""
        for s in ["a", "hello world", "def foo():", "    pass", ""]:
            assert len(compute_hash(s)) == 3

    def test_compute_hash_deterministic(self) -> None:
        """Same input always produces same output."""
        assert compute_hash("foo") == compute_hash("foo")
        assert compute_hash("bar") == compute_hash("bar")

    def test_compute_hash_different_inputs(self) -> None:
        """Different inputs (spot check) produce different hashes."""
        # These specific values are known to produce different hashes
        hashes = {compute_hash(s) for s in ["def foo():", "def bar():", "import os", "class X:"]}
        assert len(hashes) > 1  # at least some are different

    def test_compute_hash_strips_tabs(self) -> None:
        """Tabs are stripped along with spaces."""
        assert compute_hash("\thello") == compute_hash("hello")
        assert compute_hash("hello\t") == compute_hash("hello")

    def test_compute_hash_unicode(self) -> None:
        """Unicode content produces a valid hash."""
        result = compute_hash("你好世界")
        assert len(result) == 3
        assert all(c in "0123456789abcdef" for c in result)


# ── annotate tests ────────────────────────────────────────────────────────────


class TestAnnotate:
    def test_annotate_single_line(self) -> None:
        """One line → '<hash>|<content>\\n'."""
        result = annotate("def hello():\n")
        assert result.endswith("\n")
        parts = result.rstrip("\n").split("|", 1)
        assert len(parts) == 2
        assert len(parts[0]) == 3  # 3-char hash
        assert parts[1] == "def hello():"

    def test_annotate_multiline(self) -> None:
        """Multiple lines each get their own hash."""
        content = "def hello():\n    return 'world'\n"
        result = annotate(content)
        lines = result.rstrip("\n").split("\n")
        assert len(lines) == 2
        for line in lines:
            parts = line.split("|", 1)
            assert len(parts) == 2
            assert len(parts[0]) in (3, 5, 6)  # 3 or 3+_N suffix

    def test_annotate_empty_string(self) -> None:
        """Empty string → empty string."""
        assert annotate("") == ""

    def test_annotate_empty_lines(self) -> None:
        """Blank lines get hashes (e3b hash of empty)."""
        result = annotate("\n\n")
        lines = result.split("\n")
        # Two empty lines + trailing newline
        assert len(lines) >= 2
        # Both empty lines should have e3b as base hash
        for line in lines[:2]:
            if line:  # skip truly empty trailing lines
                assert line.split("|")[0].startswith("e3b")

    def test_annotate_preserves_content(self) -> None:
        """Content after the | is unchanged (including indentation)."""
        content = "    if True:\n        pass\n"
        result = annotate(content)
        lines = result.rstrip("\n").split("\n")
        assert lines[0].split("|", 1)[1] == "    if True:"
        assert lines[1].split("|", 1)[1] == "        pass"

    def test_annotate_collision_handling(self) -> None:
        """Two lines with same stripped content → hash, hash_2."""
        # Two identical lines
        content = "    pass\n    pass\n"
        result = annotate(content)
        lines = result.rstrip("\n").split("\n")
        assert len(lines) == 2
        h0 = lines[0].split("|")[0]
        h1 = lines[1].split("|")[0]
        assert not h0.endswith("_2")
        assert h1 == f"{h0}_2"

    def test_annotate_triple_collision(self) -> None:
        """Three identical lines → hash, hash_2, hash_3."""
        content = "    pass\n    pass\n    pass\n"
        result = annotate(content)
        lines = result.rstrip("\n").split("\n")
        assert len(lines) == 3
        h0 = lines[0].split("|")[0]
        h1 = lines[1].split("|")[0]
        h2 = lines[2].split("|")[0]
        assert not h0.endswith("_2")
        assert h1 == f"{h0}_2"
        assert h2 == f"{h0}_3"

    def test_annotate_trailing_newline_preserved(self) -> None:
        """If input ends with \\n, output does too."""
        result = annotate("hello\n")
        assert result.endswith("\n")

    def test_annotate_no_trailing_newline(self) -> None:
        """If input doesn't end with \\n, output doesn't either."""
        result = annotate("hello")
        assert not result.endswith("\n")
        assert "|" in result

    def test_annotate_unicode(self) -> None:
        """Unicode content (CJK, emoji) is handled correctly."""
        content = "你好世界\n🎉 hello\n"
        result = annotate(content)
        lines = result.rstrip("\n").split("\n")
        assert len(lines) == 2
        assert lines[0].split("|", 1)[1] == "你好世界"
        assert lines[1].split("|", 1)[1] == "🎉 hello"

    def test_annotate_tabs_and_spaces_collision(self) -> None:
        """Lines with different whitespace but same stripped content collide."""
        content = "hello\n    hello\n"
        result = annotate(content)
        lines = result.rstrip("\n").split("\n")
        h0 = lines[0].split("|")[0]
        h1 = lines[1].split("|")[0]
        # Both have "hello" when stripped → collision
        assert h1 == f"{h0}_2"

    def test_annotate_single_line_no_newline(self) -> None:
        """Single line without trailing newline."""
        result = annotate("hello world")
        assert "|" in result
        assert result.split("|", 1)[1] == "hello world"
        assert not result.endswith("\n")


# ── apply_edits tests ─────────────────────────────────────────────────────────


class TestApplyEdits:
    def _get_hash(self, content: str, line_idx: int = 0) -> str:
        """Helper to get the hash tag for a specific line."""
        annotated = annotate(content)
        if content.endswith("\n"):
            lines = annotated.rstrip("\n").split("\n")
        else:
            lines = annotated.split("\n")
        return lines[line_idx].split("|")[0]

    def test_apply_replace_single_line(self) -> None:
        """Replace one line by hash."""
        content = "def hello():\n    return 'world'\n"
        h = self._get_hash(content, 0)
        op = EditOp(kind=EditOpKind.REPLACE, hash_ref=h, new_content="def goodbye():")
        result = apply_edits(content, [op])
        assert "def goodbye():" in result
        assert "def hello():" not in result
        assert "    return 'world'" in result

    def test_apply_replace_with_multiline(self) -> None:
        """Replace one line with multiple lines."""
        content = "def hello():\n    pass\n"
        h = self._get_hash(content, 0)
        new_content = "def hello(name: str):\n    \"\"\"Greet someone.\"\"\""
        op = EditOp(kind=EditOpKind.REPLACE, hash_ref=h, new_content=new_content)
        result = apply_edits(content, [op])
        assert "def hello(name: str):" in result
        assert '"""Greet someone."""' in result
        assert "    pass" in result

    def test_apply_insert_after(self) -> None:
        """Insert new content after a target line."""
        content = "def hello():\n    pass\n"
        h = self._get_hash(content, 0)
        op = EditOp(
            kind=EditOpKind.INSERT_AFTER,
            hash_ref=h,
            new_content="    \"\"\"Say hello.\"\"\"",
        )
        result = apply_edits(content, [op])
        lines = result.rstrip("\n").split("\n")
        assert lines[0] == "def hello():"
        assert lines[1] == '    """Say hello."""'
        assert lines[2] == "    pass"

    def test_apply_insert_after_last_line(self) -> None:
        """Insert after the final line of file."""
        content = "x = 1\n"
        h = self._get_hash(content, 0)
        op = EditOp(kind=EditOpKind.INSERT_AFTER, hash_ref=h, new_content="y = 2")
        result = apply_edits(content, [op])
        assert "x = 1" in result
        assert "y = 2" in result

    def test_apply_delete(self) -> None:
        """Delete a line by hash."""
        content = "x = 1\ny = 2\nz = 3\n"
        h = self._get_hash(content, 1)  # y = 2
        op = EditOp(kind=EditOpKind.DELETE, hash_ref=h)
        result = apply_edits(content, [op])
        assert "x = 1" in result
        assert "y = 2" not in result
        assert "z = 3" in result

    def test_apply_multiple_edits(self) -> None:
        """Apply replace + insert_after + delete in one batch."""
        content = "line1\nline2\nline3\n"
        annotated = annotate(content)
        ann_lines = annotated.rstrip("\n").split("\n")
        h0 = ann_lines[0].split("|")[0]
        h1 = ann_lines[1].split("|")[0]
        h2 = ann_lines[2].split("|")[0]

        ops = [
            EditOp(kind=EditOpKind.REPLACE, hash_ref=h0, new_content="LINE_ONE"),
            EditOp(kind=EditOpKind.INSERT_AFTER, hash_ref=h1, new_content="between2and3"),
            EditOp(kind=EditOpKind.DELETE, hash_ref=h2),
        ]
        result = apply_edits(content, ops)
        assert "LINE_ONE" in result
        assert "line1" not in result
        assert "between2and3" in result
        assert "line3" not in result

    def test_apply_edits_preserves_untouched_lines(self) -> None:
        """Lines not referenced remain unchanged."""
        content = "a\nb\nc\nd\n"
        h = self._get_hash(content, 1)  # b
        op = EditOp(kind=EditOpKind.DELETE, hash_ref=h)
        result = apply_edits(content, [op])
        assert "a" in result
        assert "b" not in result
        assert "c" in result
        assert "d" in result

    def test_apply_edits_invalid_hash_raises(self) -> None:
        """Non-existent hash → HashlineError."""
        content = "hello\n"
        op = EditOp(kind=EditOpKind.REPLACE, hash_ref="zzz", new_content="world")
        with pytest.raises(HashlineError, match="not found"):
            apply_edits(content, [op])

    def test_apply_edits_empty_edits_list(self) -> None:
        """Empty edit list → content unchanged."""
        content = "hello\nworld\n"
        result = apply_edits(content, [])
        assert result == content

    def test_apply_edits_collision_suffix(self) -> None:
        """Edit targeting hash_2 hits the second occurrence."""
        content = "    pass\n    pass\nother\n"
        annotated = annotate(content)
        ann_lines = annotated.rstrip("\n").split("\n")
        h0 = ann_lines[0].split("|")[0]   # e.g. "abc"
        h1 = ann_lines[1].split("|")[0]   # e.g. "abc_2"
        assert h1 == f"{h0}_2"

        op = EditOp(kind=EditOpKind.REPLACE, hash_ref=h1, new_content="    continue")
        result = apply_edits(content, [op])
        lines = result.rstrip("\n").split("\n")
        assert lines[0] == "    pass"
        assert lines[1] == "    continue"
        assert lines[2] == "other"

    def test_apply_edits_delete_all_lines(self) -> None:
        """Delete every line → empty string."""
        content = "a\nb\n"
        annotated = annotate(content)
        ann_lines = annotated.rstrip("\n").split("\n")
        h0 = ann_lines[0].split("|")[0]
        h1 = ann_lines[1].split("|")[0]
        ops = [
            EditOp(kind=EditOpKind.DELETE, hash_ref=h0),
            EditOp(kind=EditOpKind.DELETE, hash_ref=h1),
        ]
        result = apply_edits(content, ops)
        assert result == "" or result == "\n"  # might keep trailing newline

    def test_apply_replace_empty_content(self) -> None:
        """Replace with empty string → effectively empty line."""
        content = "hello\n"
        h = self._get_hash(content, 0)
        op = EditOp(kind=EditOpKind.REPLACE, hash_ref=h, new_content="")
        result = apply_edits(content, [op])
        assert "hello" not in result

    def test_apply_edits_order_matters(self) -> None:
        """Sequential edits applied top-to-bottom."""
        content = "first\nsecond\nthird\n"
        annotated = annotate(content)
        ann_lines = annotated.rstrip("\n").split("\n")
        h0 = ann_lines[0].split("|")[0]
        h1 = ann_lines[1].split("|")[0]

        # Replace first, then insert after second (original index)
        ops = [
            EditOp(kind=EditOpKind.REPLACE, hash_ref=h0, new_content="FIRST"),
            EditOp(kind=EditOpKind.INSERT_AFTER, hash_ref=h1, new_content="INSERTED"),
        ]
        result = apply_edits(content, ops)
        assert "FIRST" in result
        assert "INSERTED" in result
        assert "second" in result
        assert "first" not in result

    def test_apply_replace_multiline_content_with_newline(self) -> None:
        """Replace with multi-line content that has embedded newlines."""
        content = "old_func()\n"
        h = self._get_hash(content, 0)
        op = EditOp(kind=EditOpKind.REPLACE, hash_ref=h, new_content="line1\nline2\nline3")
        result = apply_edits(content, [op])
        assert "line1" in result
        assert "line2" in result
        assert "line3" in result
        assert "old_func" not in result


# ── read_file_annotated tests ─────────────────────────────────────────────────


class TestReadFileAnnotated:
    def test_read_file_annotated_basic(self, tmp_path: Path) -> None:
        """Read a real file, verify annotated output."""
        f = tmp_path / "test.py"
        f.write_text("def hello():\n    pass\n")
        result = read_file_annotated(f)
        lines = result.rstrip("\n").split("\n")
        assert len(lines) == 2
        assert "|def hello():" in lines[0]
        assert "|    pass" in lines[1]

    def test_read_file_annotated_nonexistent(self, tmp_path: Path) -> None:
        """Missing file → FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            read_file_annotated(tmp_path / "nonexistent.txt")

    def test_read_file_annotated_directory(self, tmp_path: Path) -> None:
        """Directory path → IsADirectoryError."""
        with pytest.raises(IsADirectoryError):
            read_file_annotated(tmp_path)

    def test_read_file_annotated_empty_file(self, tmp_path: Path) -> None:
        """Empty file → empty string."""
        f = tmp_path / "empty.txt"
        f.write_text("")
        result = read_file_annotated(f)
        assert result == ""

    def test_read_file_annotated_binary_detection(self, tmp_path: Path) -> None:
        """File with null bytes → HashlineError('Cannot annotate binary file')."""
        f = tmp_path / "binary.bin"
        f.write_bytes(b"some data\x00more data")
        with pytest.raises(HashlineError, match="Cannot annotate binary file"):
            read_file_annotated(f)

    def test_read_file_annotated_string_path(self, tmp_path: Path) -> None:
        """Accepts string paths as well as Path objects."""
        f = tmp_path / "test.txt"
        f.write_text("hello\n")
        result = read_file_annotated(str(f))
        assert "|hello" in result

    def test_read_file_annotated_unicode(self, tmp_path: Path) -> None:
        """Unicode file content is read correctly."""
        f = tmp_path / "unicode.txt"
        f.write_text("你好世界\n", encoding="utf-8")
        result = read_file_annotated(f)
        assert "你好世界" in result


# ── write_file_with_edits tests ───────────────────────────────────────────────


class TestWriteFileWithEdits:
    def _get_hash(self, content: str, line_idx: int = 0) -> str:
        annotated = annotate(content)
        if content.endswith("\n"):
            lines = annotated.rstrip("\n").split("\n")
        else:
            lines = annotated.split("\n")
        return lines[line_idx].split("|")[0]

    def test_write_file_with_edits_basic(self, tmp_path: Path) -> None:
        """Read + edit + write + verify file on disk."""
        f = tmp_path / "test.py"
        f.write_text("x = 1\ny = 2\n")
        h = self._get_hash("x = 1\ny = 2\n", 0)
        op = EditOp(kind=EditOpKind.REPLACE, hash_ref=h, new_content="x = 100")
        write_file_with_edits(f, [op])
        assert f.read_text() == "x = 100\ny = 2\n"

    def test_write_file_with_edits_returns_annotated(self, tmp_path: Path) -> None:
        """Return value is the new annotated content."""
        f = tmp_path / "test.py"
        f.write_text("x = 1\n")
        h = self._get_hash("x = 1\n", 0)
        op = EditOp(kind=EditOpKind.REPLACE, hash_ref=h, new_content="x = 42")
        result = write_file_with_edits(f, [op])
        # Result should be annotated
        assert "|" in result
        assert "x = 42" in result

    def test_write_file_with_edits_nonexistent(self, tmp_path: Path) -> None:
        """Missing file → FileNotFoundError."""
        op = EditOp(kind=EditOpKind.REPLACE, hash_ref="abc", new_content="new")
        with pytest.raises(FileNotFoundError):
            write_file_with_edits(tmp_path / "nonexistent.txt", [op])

    def test_write_file_with_edits_invalid_hash(self, tmp_path: Path) -> None:
        """Bad hash → HashlineError, file unchanged."""
        f = tmp_path / "test.py"
        original = "x = 1\n"
        f.write_text(original)
        op = EditOp(kind=EditOpKind.REPLACE, hash_ref="zzz", new_content="new")
        with pytest.raises(HashlineError):
            write_file_with_edits(f, [op])
        # File must be unchanged
        assert f.read_text() == original

    def test_write_file_with_edits_atomicity(self, tmp_path: Path) -> None:
        """On error, original file is NOT modified."""
        f = tmp_path / "test.py"
        original = "important_code = True\n"
        f.write_text(original)
        op = EditOp(kind=EditOpKind.DELETE, hash_ref="000")
        with pytest.raises(HashlineError):
            write_file_with_edits(f, [op])
        assert f.read_text() == original

    def test_write_file_with_edits_binary(self, tmp_path: Path) -> None:
        """Binary file → HashlineError, file unchanged."""
        f = tmp_path / "binary.bin"
        f.write_bytes(b"data\x00more")
        op = EditOp(kind=EditOpKind.DELETE, hash_ref="abc")
        with pytest.raises(HashlineError, match="Cannot annotate binary file"):
            write_file_with_edits(f, [op])


# ── parse_edit_ops tests ──────────────────────────────────────────────────────


class TestParseEditOps:
    def test_parse_single_replace(self) -> None:
        """Parse one REPLACE block."""
        text = """\
HASHLINE_EDIT src/main.py
REPLACE a3f
def hello(name: str):
END
HASHLINE_EDIT_END
"""
        ops = parse_edit_ops(text)
        assert len(ops) == 1
        assert ops[0].kind == EditOpKind.REPLACE
        assert ops[0].hash_ref == "a3f"
        assert ops[0].new_content == "def hello(name: str):"

    def test_parse_single_insert_after(self) -> None:
        """Parse one INSERT_AFTER block."""
        text = """\
HASHLINE_EDIT src/foo.py
INSERT_AFTER 7b2
    print("inserted")
END
HASHLINE_EDIT_END
"""
        ops = parse_edit_ops(text)
        assert len(ops) == 1
        assert ops[0].kind == EditOpKind.INSERT_AFTER
        assert ops[0].hash_ref == "7b2"
        assert "inserted" in ops[0].new_content

    def test_parse_single_delete(self) -> None:
        """Parse one DELETE block."""
        text = """\
HASHLINE_EDIT src/bar.py
DELETE 0e1
END
HASHLINE_EDIT_END
"""
        ops = parse_edit_ops(text)
        assert len(ops) == 1
        assert ops[0].kind == EditOpKind.DELETE
        assert ops[0].hash_ref == "0e1"
        assert ops[0].new_content == ""

    def test_parse_multiple_ops(self) -> None:
        """Parse a block with all three op types."""
        text = """\
HASHLINE_EDIT src/example.py
REPLACE a3f
def hello(name: str):
END
INSERT_AFTER 7b2
    print(f"Hello {name}")
END
DELETE 0e1
END
HASHLINE_EDIT_END
"""
        ops = parse_edit_ops(text)
        assert len(ops) == 3
        assert ops[0].kind == EditOpKind.REPLACE
        assert ops[1].kind == EditOpKind.INSERT_AFTER
        assert ops[2].kind == EditOpKind.DELETE

    def test_parse_multiline_content(self) -> None:
        """REPLACE with multi-line new content."""
        text = """\
HASHLINE_EDIT src/example.py
REPLACE a3f
def hello(name: str):
    \"\"\"Say hello.\"\"\"
    return f"Hello, {name}"
END
HASHLINE_EDIT_END
"""
        ops = parse_edit_ops(text)
        assert len(ops) == 1
        assert "def hello(name: str):" in ops[0].new_content
        assert '"""Say hello."""' in ops[0].new_content
        assert "return" in ops[0].new_content

    def test_parse_empty_text(self) -> None:
        """No HASHLINE_EDIT markers → empty list."""
        ops = parse_edit_ops("some random text without markers")
        assert ops == []

    def test_parse_empty_string(self) -> None:
        """Empty string → empty list."""
        ops = parse_edit_ops("")
        assert ops == []

    def test_parse_malformed_raises(self) -> None:
        """Missing HASHLINE_EDIT_END → HashlineError."""
        text = """\
HASHLINE_EDIT src/file.py
REPLACE abc
new content
END
"""
        with pytest.raises(HashlineError, match="HASHLINE_EDIT_END"):
            parse_edit_ops(text)

    def test_parse_unknown_op_raises(self) -> None:
        """Unknown operation type → HashlineError."""
        text = """\
HASHLINE_EDIT src/file.py
FROBULATE abc
new content
END
HASHLINE_EDIT_END
"""
        with pytest.raises(HashlineError, match="expected REPLACE/INSERT_AFTER/DELETE"):
            parse_edit_ops(text)

    def test_parse_multiple_edit_blocks(self) -> None:
        """Multiple HASHLINE_EDIT blocks for different files returns all ops."""
        text = """\
HASHLINE_EDIT src/a.py
REPLACE a1b
line a
END
HASHLINE_EDIT_END

HASHLINE_EDIT src/b.py
DELETE c2d
END
HASHLINE_EDIT_END
"""
        ops = parse_edit_ops(text)
        assert len(ops) == 2
        assert ops[0].kind == EditOpKind.REPLACE
        assert ops[1].kind == EditOpKind.DELETE

    def test_parse_collision_suffix_hash(self) -> None:
        """Collision suffix hash (e.g. a3f_2) is preserved as-is."""
        text = """\
HASHLINE_EDIT src/file.py
REPLACE a3f_2
replaced second occurrence
END
HASHLINE_EDIT_END
"""
        ops = parse_edit_ops(text)
        assert len(ops) == 1
        assert ops[0].hash_ref == "a3f_2"

    def test_parse_op_with_surrounding_text(self) -> None:
        """HASHLINE_EDIT block embedded in other text is parsed correctly."""
        text = """\
I'll make the following changes:

HASHLINE_EDIT src/main.py
REPLACE abc
def new_func():
    pass
END
HASHLINE_EDIT_END

This should fix the issue.
"""
        ops = parse_edit_ops(text)
        assert len(ops) == 1
        assert ops[0].kind == EditOpKind.REPLACE


# ── build_system_prompt_fragment tests ───────────────────────────────────────


class TestBuildSystemPromptFragment:
    def test_prompt_fragment_not_empty(self) -> None:
        """Returns non-empty string."""
        result = build_system_prompt_fragment()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_prompt_fragment_contains_hash_format(self) -> None:
        """Mentions the | separator."""
        result = build_system_prompt_fragment()
        assert "|" in result

    def test_prompt_fragment_contains_edit_ops(self) -> None:
        """Mentions REPLACE, INSERT_AFTER, DELETE."""
        result = build_system_prompt_fragment()
        assert "REPLACE" in result
        assert "INSERT_AFTER" in result
        assert "DELETE" in result

    def test_prompt_fragment_contains_example(self) -> None:
        """Contains at least one usage example."""
        result = build_system_prompt_fragment()
        assert "HASHLINE_EDIT" in result

    def test_prompt_fragment_mentions_collision(self) -> None:
        """Mentions collision handling."""
        result = build_system_prompt_fragment()
        assert "collision" in result.lower() or "_2" in result

    def test_prompt_fragment_is_string(self) -> None:
        """Return type is str."""
        result = build_system_prompt_fragment()
        assert isinstance(result, str)


# ── Integration tests ─────────────────────────────────────────────────────────


class TestIntegration:
    def test_roundtrip_annotate_edit_verify(self) -> None:
        """annotate → parse_edit_ops → apply_edits → verify content correct."""
        original = "def hello():\n    return 'world'\n}"
        annotated = annotate(original)
        lines = annotated.split("\n")
        first_hash = lines[0].split("|")[0]

        edit_text = f"""\
HASHLINE_EDIT src/example.py
REPLACE {first_hash}
def goodbye():
END
HASHLINE_EDIT_END
"""
        ops = parse_edit_ops(edit_text)
        result = apply_edits(original, ops)
        assert "def goodbye():" in result
        assert "def hello():" not in result
        assert "return 'world'" in result

    def test_roundtrip_file_read_write(self, tmp_path: Path) -> None:
        """read_file_annotated → construct edits → write_file_with_edits → verify."""
        f = tmp_path / "test.py"
        original = "x = 1\ny = 2\nz = 3\n"
        f.write_text(original)

        # Read annotated
        annotated = read_file_annotated(f)
        lines = annotated.rstrip("\n").split("\n")
        h1 = lines[1].split("|")[0]  # y = 2

        # Build edit
        op = EditOp(kind=EditOpKind.REPLACE, hash_ref=h1, new_content="y = 200")
        write_file_with_edits(f, [op])

        # Verify file
        assert f.read_text() == "x = 1\ny = 200\nz = 3\n"
        assert "|" in annotated
        assert "y = 2" in annotated  # original value was in the annotated view

    def test_hashline_with_real_python_file(self, tmp_path: Path) -> None:
        """Use a multi-function Python file as input, apply realistic edits."""
        code = """\
import os
import sys


def foo():
    x = 1
    return x


def bar():
    y = 2
    return y
"""
        f = tmp_path / "module.py"
        f.write_text(code)

        annotated = read_file_annotated(f)
        ann_lines = annotated.rstrip("\n").split("\n")
        # Find "def foo():" hash
        foo_hash = None
        for line in ann_lines:
            tag, content = line.split("|", 1)
            if content.strip() == "def foo():":
                foo_hash = tag
                break
        assert foo_hash is not None

        op = EditOp(
            kind=EditOpKind.REPLACE,
            hash_ref=foo_hash,
            new_content="def foo(n: int = 1):",
        )
        write_file_with_edits(f, [op])
        assert "def foo(n: int = 1):" in f.read_text()
        assert "def bar():" in f.read_text()  # unchanged

    def test_collision_hash_resolution(self) -> None:
        """Collision hash resolution works end-to-end."""
        # Create content with colliding lines
        content = "    pass\n    pass\nreturn 1\n"
        annotated = annotate(content)
        ann_lines = annotated.rstrip("\n").split("\n")

        h0 = ann_lines[0].split("|")[0]  # e.g. "xyz"
        h1 = ann_lines[1].split("|")[0]  # e.g. "xyz_2"
        assert h1 == f"{h0}_2"

        # Edit the second "pass" only
        op = EditOp(kind=EditOpKind.REPLACE, hash_ref=h1, new_content="    break")
        result = apply_edits(content, [op])
        lines = result.rstrip("\n").split("\n")
        assert lines[0] == "    pass"
        assert lines[1] == "    break"
        assert lines[2] == "return 1"

    def test_multiple_edits_with_insertions_adjust_offsets(self) -> None:
        """Multiple edits with insertions adjust offsets correctly."""
        content = "a\nb\nc\n"
        annotated = annotate(content)
        ann_lines = annotated.rstrip("\n").split("\n")
        ha = ann_lines[0].split("|")[0]
        hb = ann_lines[1].split("|")[0]
        hc = ann_lines[2].split("|")[0]

        ops = [
            EditOp(kind=EditOpKind.INSERT_AFTER, hash_ref=ha, new_content="a2"),
            EditOp(kind=EditOpKind.INSERT_AFTER, hash_ref=hb, new_content="b2"),
            EditOp(kind=EditOpKind.DELETE, hash_ref=hc),
        ]
        result = apply_edits(content, ops)
        lines = result.rstrip("\n").split("\n")
        assert "a" in lines
        assert "a2" in lines
        assert "b" in lines
        assert "b2" in lines
        assert "c" not in lines


# ── CLI integration tests ─────────────────────────────────────────────────────


class TestCLIEditMode:
    def test_run_accepts_edit_mode_flag(self) -> None:
        """claw-forge run --edit-mode hashline doesn't error on parsing."""
        import re

        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        # We just test that the CLI parses the option correctly by using --help
        result = runner.invoke(app, ["run", "--help"])
        # Strip ANSI escape sequences before asserting (rich may split flag names)
        clean_output = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "--edit-mode" in clean_output
        assert result.exit_code == 0

    def test_run_default_edit_mode(self) -> None:
        """Default is str_replace (shown in help)."""
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["run", "--help"])
        assert "str_replace" in result.output

    def test_run_invalid_edit_mode(self, tmp_path: Path) -> None:
        """Invalid value → error message."""
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        # Create minimal config
        cfg = tmp_path / "claw-forge.yaml"
        cfg.write_text("agent:\n  default_model: claude-sonnet-4-6\n")

        result = runner.invoke(app, [
            "run",
            "--config", str(cfg),
            "--project", str(tmp_path),
            "--edit-mode", "invalid_mode",
        ])
        assert result.exit_code != 0 or "Invalid" in (result.output or "")

    def test_hashline_edit_mode_in_help(self) -> None:
        """hashline is listed as a valid option in the help text."""
        from typer.testing import CliRunner

        from claw_forge.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["run", "--help"])
        assert "hashline" in result.output


# ── Edge case tests ───────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_annotate_single_empty_line(self) -> None:
        """A file with just a newline character."""
        result = annotate("\n")
        # Should have one annotated empty line
        assert "|" in result

    def test_apply_edits_with_no_trailing_newline(self) -> None:
        """File without trailing newline is handled correctly."""
        content = "hello\nworld"  # no trailing newline
        annotated = annotate(content)
        lines = annotated.split("\n")
        h0 = lines[0].split("|")[0]

        op = EditOp(kind=EditOpKind.REPLACE, hash_ref=h0, new_content="goodbye")
        result = apply_edits(content, [op])
        assert result == "goodbye\nworld"
        assert not result.endswith("\n")

    def test_hash_index_building_consistency(self) -> None:
        """compute_hash and annotate are consistent."""
        line = "def foo():"
        h = compute_hash(line)
        annotated = annotate(line)
        tag = annotated.split("|")[0]
        assert tag == h

    def test_ambiguous_hash_error_message(self) -> None:
        """Ambiguous hash (has _2 variant but bare hash used) gives helpful error."""
        content = "    pass\n    pass\n"
        annotated = annotate(content)
        lines = annotated.rstrip("\n").split("\n")
        base_hash = lines[0].split("|")[0]  # e.g. "xyz"

        # Try to use bare hash when _2 exists
        op = EditOp(kind=EditOpKind.REPLACE, hash_ref=base_hash, new_content="new")
        with pytest.raises(HashlineError, match="multiple lines"):
            apply_edits(content, [op])

    def test_parse_edit_ops_missing_end_marker(self) -> None:
        """Missing END marker raises HashlineError."""
        text = """\
HASHLINE_EDIT src/file.py
REPLACE abc
new content without end marker
HASHLINE_EDIT_END
"""
        with pytest.raises(HashlineError):
            parse_edit_ops(text)

    def test_annotate_long_file(self) -> None:
        """Large file with many lines is handled correctly."""
        lines = [f"line_{i}" for i in range(500)]
        content = "\n".join(lines) + "\n"
        result = annotate(content)
        ann_lines = result.rstrip("\n").split("\n")
        assert len(ann_lines) == 500
        # Each line has a tag
        for al in ann_lines:
            assert "|" in al

    def test_write_file_with_edits_string_path(self, tmp_path: Path) -> None:
        """Accepts string paths."""
        f = tmp_path / "test.txt"
        f.write_text("hello\n")
        annotated = annotate("hello\n")
        h = annotated.split("|")[0]
        op = EditOp(kind=EditOpKind.REPLACE, hash_ref=h, new_content="goodbye")
        write_file_with_edits(str(f), [op])
        assert f.read_text() == "goodbye\n"

    def test_dataclass_fields(self) -> None:
        """EditOp default field values are correct."""
        op = EditOp(kind=EditOpKind.DELETE, hash_ref="abc")
        assert op.new_content == ""
        assert op.kind == EditOpKind.DELETE
        assert op.hash_ref == "abc"

    def test_edit_op_kind_values(self) -> None:
        """EditOpKind has correct string values."""
        assert EditOpKind.REPLACE == "replace"
        assert EditOpKind.INSERT_AFTER == "insert_after"
        assert EditOpKind.DELETE == "delete"




class TestHashlineCoverageEdgeCases:
    """Tests to hit uncovered lines in hashline.py for the coverage gate."""

    def test_apply_edits_delete_all_lines_returns_empty(self) -> None:
        """Deleting every line should return empty string (covers line 199→160 branch)."""
        content = "only line\n"
        annotated = annotate(content)
        h = annotated.split("|")[0]
        op = EditOp(kind=EditOpKind.DELETE, hash_ref=h, new_content="")
        result = apply_edits(content, [op])
        assert result == ""

    def test_write_file_with_edits_is_dir_raises(self, tmp_path: Path) -> None:
        """write_file_with_edits raises IsADirectoryError when path is a dir (covers line 261)."""
        op = EditOp(kind=EditOpKind.REPLACE, hash_ref="abc", new_content="x")
        with pytest.raises(IsADirectoryError):
            write_file_with_edits(str(tmp_path), [op])

    def test_parse_edit_ops_delete_op(self) -> None:
        """parse_edit_ops correctly parses a DELETE operation (covers line 437→381)."""
        content = "line one\nline two\n"
        annotated = annotate(content)
        h1 = annotated.split("\n")[0].split("|")[0]
        text = f"HASHLINE_EDIT file.py\nDELETE {h1}\nEND\nHASHLINE_EDIT_END\n"
        ops = parse_edit_ops(text)
        assert len(ops) == 1
        assert ops[0].kind == EditOpKind.DELETE
        assert ops[0].hash_ref == h1
        assert ops[0].new_content == ""

    def test_parse_edit_ops_short_line_skipped(self) -> None:
        """Lines with < 2 parts inside a block are skipped (covers lines 390-391)."""
        content = "foo\n"
        annotated = annotate(content)
        h = annotated.split("|")[0]
        # The bare 'REPLACE' (no hash) should be skipped; the valid one should parse
        text = (
            f"HASHLINE_EDIT file.py\n"
            f"REPLACE\n"           # malformed — single token, skipped
            f"REPLACE {h}\n"
            f"new foo\n"
            f"END\n"
            f"HASHLINE_EDIT_END\n"
        )
        ops = parse_edit_ops(text)
        assert len(ops) == 1
        assert ops[0].hash_ref == h

    def test_parse_edit_ops_trailing_blank_content_stripped(self) -> None:
        """Trailing blank lines in replacement content are stripped (covers line 425)."""
        content = "bar\n"
        annotated = annotate(content)
        h = annotated.split("|")[0]
        text = (
            f"HASHLINE_EDIT file.py\n"
            f"REPLACE {h}\n"
            f"new bar\n"
            f"\n"
            f"\n"
            f"END\n"
            f"HASHLINE_EDIT_END\n"
        )
        ops = parse_edit_ops(text)
        assert len(ops) == 1
        assert ops[0].new_content == "new bar"
