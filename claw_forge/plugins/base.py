"""AgentPlugin protocol and base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any, Protocol, runtime_checkable


@dataclass
class PluginContext:
    """Context passed to plugin execution."""

    project_path: str
    session_id: str
    task_id: str
    config: dict[str, Any] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PluginResult:
    """Result from plugin execution."""

    success: bool
    output: str = ""
    files_modified: list[str] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    tokens_used: int = 0
    cost_usd: float = 0.0


@runtime_checkable
class AgentPlugin(Protocol):
    """Protocol for all agent plugins."""

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def version(self) -> str: ...

    def get_system_prompt(self, context: PluginContext) -> str: ...

    async def execute(self, context: PluginContext) -> PluginResult: ...


class BasePlugin(ABC):
    """Base class providing shared plugin functionality."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    def version(self) -> str:
        return "0.1.0"

    @abstractmethod
    def get_system_prompt(self, context: PluginContext) -> str: ...

    @abstractmethod
    async def execute(self, context: PluginContext) -> PluginResult: ...


def discover_plugins() -> dict[str, type[BasePlugin]]:
    """Discover installed plugins via entry points."""
    plugins: dict[str, type[BasePlugin]] = {}
    eps = entry_points()
    group = eps.get("claw_forge.plugins", []) if isinstance(eps, dict) else eps.select(group="claw_forge.plugins")
    for ep in group:
        try:
            cls = ep.load()
            plugins[ep.name] = cls
        except Exception:
            pass
    return plugins
