"""Bug report parser — reads bug_report.md and structures it for agent injection."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# ── Section name normalisation ────────────────────────────────────────────────

_SECTION_MAP: dict[str, str] = {}


def _register(*aliases: str) -> str:
    """Register aliases and return the canonical field name."""
    canonical = aliases[0]
    for alias in aliases:
        _SECTION_MAP[alias.lower()] = canonical
    return canonical


_SYMPTOMS = _register("symptoms", "problem", "issue")
_REPRO = _register("reproduction_steps", "reproduction steps", "steps to reproduce", "repro")
_EXPECTED = _register("expected_behaviour", "expected behavior", "expected behaviour", "expected")
_ACTUAL = _register(
    "actual_behaviour", "actual behavior", "actual behaviour", "actual", "current behavior"
)
_SCOPE = _register("affected_scope", "affected files", "affected scope", "suspected files")
_CONSTRAINTS = _register("constraints", "requirements", "must not change")
_REGRESSION = _register("regression_test_required", "regression test", "regression")
_ENVIRONMENT = _register("environment")


def _normalise_heading(heading: str) -> str | None:
    """Return canonical field name for a markdown heading text, or None if unknown."""
    key = heading.strip().lower()
    # Try exact match first, then prefix match
    if key in _SECTION_MAP:
        return _SECTION_MAP[key]
    for alias, canonical in _SECTION_MAP.items():
        if key.startswith(alias) or alias.startswith(key):
            return canonical
    return None


# ── Bullet / item parsers ─────────────────────────────────────────────────────

_BULLET_RE = re.compile(r"^[\*\-]\s+(.+)")
_NUMBERED_RE = re.compile(r"^\d+\.\s+(.+)")
_KV_RE = re.compile(r"^([^:]+):\s*(.*)")


def _is_comment(line: str) -> bool:
    return line.strip().startswith("<!--") or line.strip().endswith("-->")


def _parse_list_item(line: str) -> str | None:
    """Return text of a bullet/numbered item, or None."""
    stripped = line.strip()
    if _is_comment(stripped):
        return None
    m = _BULLET_RE.match(stripped) or _NUMBERED_RE.match(stripped)
    return m.group(1).strip() if m else None


# ── BugReport dataclass ───────────────────────────────────────────────────────


@dataclass
class BugReport:
    """Structured representation of a bug_report.md file."""

    title: str
    symptoms: list[str] = field(default_factory=list)
    reproduction_steps: list[str] = field(default_factory=list)
    expected_behaviour: str = ""
    actual_behaviour: str = ""
    affected_scope: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    regression_test_required: bool = True
    environment: dict[str, str] = field(default_factory=dict)
    raw_text: str = ""

    # ── Constructors ──────────────────────────────────────────────────────────

    @classmethod
    def from_file(cls, path: str | Path) -> BugReport:
        """Parse a bug_report.md file into a BugReport."""
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        return cls._parse(text)

    @classmethod
    def from_description(cls, description: str) -> BugReport:
        """Create a minimal BugReport from a plain-English description."""
        return cls(title=description, raw_text=description)

    # ── Internal parser ───────────────────────────────────────────────────────

    @classmethod
    def _parse(cls, text: str) -> BugReport:
        lines = text.splitlines()

        title = ""
        current_section: str | None = None
        section_lines: dict[str, list[str]] = {}

        for line in lines:
            stripped = line.strip()

            # Top-level heading → title
            if stripped.startswith("# ") and not title:
                title = stripped[2:].strip()
                # Strip "Bug:" prefix if present
                if title.lower().startswith("bug:"):
                    title = title[4:].strip()
                continue

            # ## or ### heading → section marker
            heading_match = re.match(r"^#{2,3}\s+(.+)", stripped)
            if heading_match:
                heading_text = heading_match.group(1).strip()
                canonical = _normalise_heading(heading_text)
                if canonical:
                    current_section = canonical
                    if current_section not in section_lines:
                        section_lines[current_section] = []
                else:
                    current_section = None
                continue

            if current_section and stripped and not _is_comment(stripped):
                section_lines.setdefault(current_section, []).append(line)

        def _collect_list(key: str) -> list[str]:
            items: list[str] = []
            for ln in section_lines.get(key, []):
                item = _parse_list_item(ln)
                if item:
                    items.append(item)
            return items

        def _collect_text(key: str) -> str:
            parts: list[str] = []
            for ln in section_lines.get(key, []):
                stripped_ln = ln.strip()
                if stripped_ln and not _is_comment(stripped_ln):
                    item = _parse_list_item(ln)
                    parts.append(item if item else stripped_ln)
            return " ".join(parts).strip()

        def _collect_bool(key: str) -> bool:
            for ln in section_lines.get(key, []):
                lower = ln.lower()
                if any(word in lower for word in ("yes", "true", "required")):
                    return True
                if any(word in lower for word in ("no", "false")):
                    return False
            return True  # default

        def _collect_env(key: str) -> dict[str, str]:
            env: dict[str, str] = {}
            for ln in section_lines.get(key, []):
                stripped_ln = ln.strip()
                if _is_comment(stripped_ln):
                    continue
                # Could be a bullet item "- Key: value"
                item = _parse_list_item(ln)
                target = item if item else stripped_ln
                if not target:
                    continue
                m = _KV_RE.match(target)
                if m:
                    k, v = m.group(1).strip(), m.group(2).strip()
                    if k:
                        env[k] = v
            return env

        return cls(
            title=title,
            symptoms=_collect_list(_SYMPTOMS),
            reproduction_steps=_collect_list(_REPRO),
            expected_behaviour=_collect_text(_EXPECTED),
            actual_behaviour=_collect_text(_ACTUAL),
            affected_scope=_collect_list(_SCOPE),
            constraints=_collect_list(_CONSTRAINTS),
            regression_test_required=_collect_bool(_REGRESSION),
            environment=_collect_env(_ENVIRONMENT),
            raw_text=text,
        )

    # ── Agent prompt ──────────────────────────────────────────────────────────

    def to_agent_prompt(self) -> str:
        """Format as a structured prompt for injection into the agent system prompt."""
        lines: list[str] = [f"## Bug Report: {self.title}", ""]

        if self.symptoms:
            lines.append("### Symptoms")
            for s in self.symptoms:
                lines.append(f"- {s}")
            lines.append("")

        if self.reproduction_steps:
            lines.append("### Reproduction Steps")
            for i, step in enumerate(self.reproduction_steps, 1):
                lines.append(f"{i}. {step}")
            lines.append("")

        if self.expected_behaviour:
            lines.append("### Expected Behaviour")
            lines.append(self.expected_behaviour)
            lines.append("")

        if self.actual_behaviour:
            lines.append("### Actual Behaviour")
            lines.append(self.actual_behaviour)
            lines.append("")

        if self.affected_scope:
            lines.append("### Affected Scope (suspected)")
            for s in self.affected_scope:
                lines.append(f"- {s}")
            lines.append("")

        if self.constraints:
            lines.append("### Constraints")
            for c in self.constraints:
                lines.append(f"- {c}")
            lines.append("")

        lines.append("### Protocol")
        lines.append(
            "Follow systematic-debug skill: Reproduce → Isolate → Hypothesize → Verify → Fix"
        )
        lines.append("Write a FAILING regression test FIRST, then fix until it passes.")
        lines.append("Run full test suite after fix — must be 100% green.")

        return "\n".join(lines)
