"""Format detector — inspects a path and returns a FormatResult."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class FormatResult:
    format: Literal["bmad", "linear", "jira", "generic"]
    confidence: Literal["high", "medium", "low"]
    artifacts: list[Path] = field(default_factory=list)
    summary: str = ""


def detect(path: Path) -> FormatResult:
    """Inspect *path* (file or directory) and return a FormatResult.

    Raises FileNotFoundError if path does not exist.
    Falls back to 'generic' with confidence 'low' when no format matched.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No files found at {path}")

    if path.is_file():
        files = [path]
        search_root = path.parent
    else:
        files = list(path.rglob("*"))
        search_root = path

    # ── BMAD detection ──────────────────────────────────────────────────────
    prd_md = search_root / "prd.md"
    stories_dir = search_root / "stories"
    bmad_output_dir = search_root / "_bmad-output"

    has_prd = prd_md.exists()
    has_stories = (
        stories_dir.is_dir()
        and any(
            d.is_dir() and d.name.startswith("epic-")
            for d in stories_dir.iterdir()
        )
    ) if stories_dir.exists() else False
    has_bmad_dir = bmad_output_dir.is_dir()

    if has_prd or has_stories or has_bmad_dir:
        root = bmad_output_dir if has_bmad_dir else search_root
        artifacts: list[Path] = []
        if (root / "prd.md").exists():
            artifacts.append(root / "prd.md")
        if (root / "architecture.md").exists():
            artifacts.append(root / "architecture.md")
        if (root / "stories").is_dir():
            artifacts += sorted((root / "stories").rglob("*.md"))
        epic_count = (
            sum(1 for d in (root / "stories").iterdir() if d.is_dir())
            if (root / "stories").is_dir()
            else 0
        )
        story_count = len([p for p in artifacts if "stories" in str(p)])
        return FormatResult(
            format="bmad",
            confidence="high",
            artifacts=artifacts,
            summary=f"BMAD output — {epic_count} epic(s), {story_count} story file(s)",
        )

    # ── Linear detection ────────────────────────────────────────────────────
    for f in files:
        if f.suffix == ".json":
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(data.get("issues"), list) and data["issues"]:
                first = data["issues"][0]
                if "identifier" in first and "state" in first:
                    count = len(data["issues"])
                    return FormatResult(
                        format="linear",
                        confidence="high",
                        artifacts=[f],
                        summary=f"Linear export — {count} issue(s)",
                    )

    # ── Jira detection ──────────────────────────────────────────────────────
    for f in files:
        if f.suffix == ".xml":
            try:
                root_el = ET.fromstring(f.read_text(encoding="utf-8"))
            except ET.ParseError:
                continue
            if root_el.tag in ("rss", "jira"):
                items = root_el.findall(".//item")
                return FormatResult(
                    format="jira",
                    confidence="high",
                    artifacts=[f],
                    summary=f"Jira XML export — {len(items)} item(s)",
                )
        if f.suffix == ".csv":
            try:
                header = f.read_text(encoding="utf-8").splitlines()[0]
            except (OSError, IndexError):
                continue
            if "Issue key" in header and "Epic Link" in header:
                import csv as _csv

                with f.open(encoding="utf-8") as fh:
                    rows = list(_csv.DictReader(fh))
                return FormatResult(
                    format="jira",
                    confidence="high",
                    artifacts=[f],
                    summary=f"Jira CSV export — {len(rows)} row(s)",
                )

    # ── Generic markdown fallback ───────────────────────────────────────────
    md_files = [f for f in files if f.suffix == ".md"]
    return FormatResult(
        format="generic",
        confidence="low",
        artifacts=md_files,
        summary=f"Generic markdown — {len(md_files)} file(s) (format unrecognised)",
    )
