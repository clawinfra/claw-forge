"""Format detector — inspects a path and returns a FormatResult."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class FormatResult:
    format: Literal["bmad", "linear", "jira", "generic"]
    confidence: Literal["high", "medium", "low"]
    artifacts: list[Path] = field(default_factory=list)
    summary: str = ""
