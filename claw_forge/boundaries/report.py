"""Emit and parse ``boundaries_report.md``.

The format is human-readable markdown that the user reads directly to
decide which hotspots to apply.  We also parse it back so ``apply``
doesn't need to re-run the audit (which costs a model call per hotspot
in the classifier step).

Format:

    # Boundaries Audit — <project>

    N hotspot(s) identified.

    ## 1. <path>  (score X.X)
    - signals: dispatch=N, import=N, churn=N, function=N
    **Proposed pattern:** <pattern>

The ``**Proposed pattern:**`` line is optional — emitted only when the
classifier produced a known pattern.
"""
from __future__ import annotations

import re
from pathlib import Path

from claw_forge.boundaries.scorer import Hotspot

_HEADER_RE = re.compile(
    r"^## (?P<idx>\d+)\.\s+(?P<path>\S+)\s+\(score\s+(?P<score>[\d.]+)\)\s*$"
)
_SIGNAL_RE = re.compile(
    r"^- signals:\s+dispatch=(?P<d>\d+),\s+"
    r"import=(?P<i>\d+),\s+churn=(?P<c>\d+),\s+function=(?P<f>\d+)\s*$"
)
_PATTERN_RE = re.compile(r"^\*\*Proposed pattern:\*\*\s+(?P<pattern>\w+)\s*$")


def emit_report(
    hotspots: list[Hotspot],
    *,
    out_path: Path,
    project_name: str = "",
) -> None:
    """Write a human-readable report.  Round-trippable by ``parse_report``."""
    title = (
        f"# Boundaries Audit — {project_name}"
        if project_name else "# Boundaries Audit"
    )
    lines: list[str] = [title, ""]
    lines.append(f"{len(hotspots)} hotspot(s) identified.")
    lines.append("")
    for idx, h in enumerate(hotspots, 1):
        lines.append(f"## {idx}. {h.path}  (score {h.score:.1f})")
        s = h.signals
        lines.append(
            f"- signals: dispatch={s.get('dispatch', 0)}, "
            f"import={s.get('import', 0)}, "
            f"churn={s.get('churn', 0)}, "
            f"function={s.get('function', 0)}"
        )
        if h.pattern:
            lines.append(f"**Proposed pattern:** {h.pattern}")
        lines.append("")
    out_path.write_text("\n".join(lines) + "\n")


def parse_report(path: Path) -> list[Hotspot]:
    """Parse a previously-emitted report back into Hotspots.

    Tolerant: lines that don't match any known pattern are ignored.  The
    result preserves the file order from the report.
    """
    text = path.read_text(encoding="utf-8")
    hotspots: list[Hotspot] = []
    current: Hotspot | None = None
    for line in text.splitlines():
        m_h = _HEADER_RE.match(line)
        if m_h:
            if current is not None:
                hotspots.append(current)
            current = Hotspot(
                path=m_h.group("path"),
                score=float(m_h.group("score")),
            )
            continue
        if current is None:
            continue
        m_s = _SIGNAL_RE.match(line)
        if m_s:
            current.signals = {
                "dispatch": int(m_s.group("d")),
                "import": int(m_s.group("i")),
                "churn": int(m_s.group("c")),
                "function": int(m_s.group("f")),
            }
            continue
        m_p = _PATTERN_RE.match(line)
        if m_p:
            current.pattern = m_p.group("pattern")
    if current is not None:
        hotspots.append(current)
    return hotspots
