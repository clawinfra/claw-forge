"""Session manifest for hydrating agent context on cold start."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FileContext:
    """A file to pre-load into agent context."""

    path: str
    role: str = "context"  # context | instruction | reference
    summary: str | None = None


@dataclass
class SkillRef:
    """Reference to a skill to activate."""

    name: str
    version: str = "latest"
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionManifest:
    """Complete session manifest for agent hydration.

    Contains everything an agent needs to resume work without
    cold-start delays: project context, file tree, skills,
    prior decisions, and tool configurations.
    """

    project_path: str
    project_name: str = ""
    language: str = "python"
    framework: str = ""
    description: str = ""

    # Files to inject into context
    files: list[FileContext] = field(default_factory=list)

    # Skills to activate
    skills: list[SkillRef] = field(default_factory=list)

    # Environment variables to set
    env: dict[str, str] = field(default_factory=dict)

    # Prior decisions / memory
    decisions: list[str] = field(default_factory=list)

    # Tool configurations
    tools: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Custom metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionManifest:
        files = [FileContext(**f) for f in data.pop("files", [])]
        skills = [SkillRef(**s) for s in data.pop("skills", [])]
        return cls(files=files, skills=skills, **data)

    @classmethod
    def from_json(cls, text: str) -> SessionManifest:
        return cls.from_dict(json.loads(text))

    @classmethod
    def from_file(cls, path: str | Path) -> SessionManifest:
        return cls.from_json(Path(path).read_text())

    def hydrate_prompt(self) -> str:
        """Generate a system prompt fragment from this manifest."""
        parts: list[str] = []
        parts.append(f"# Project: {self.project_name or self.project_path}")
        if self.description:
            parts.append(f"\n{self.description}")
        if self.language:
            parts.append(f"\nLanguage: {self.language}")
        if self.framework:
            parts.append(f"Framework: {self.framework}")

        if self.files:
            parts.append("\n## Key Files")
            for f in self.files:
                line = f"- `{f.path}` ({f.role})"
                if f.summary:
                    line += f": {f.summary}"
                parts.append(line)

        if self.skills:
            parts.append("\n## Active Skills")
            for s in self.skills:
                parts.append(f"- {s.name} ({s.version})")

        if self.decisions:
            parts.append("\n## Prior Decisions")
            for d in self.decisions:
                parts.append(f"- {d}")

        return "\n".join(parts)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json())
