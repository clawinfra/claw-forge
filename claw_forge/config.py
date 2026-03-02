"""Config loading for claw-forge."""

from __future__ import annotations

import os
import re
from pathlib import Path


class ConfigError(Exception):
    """Raised when config cannot be loaded or is invalid."""


def _expand_env_vars(obj: object) -> object:
    """Recursively expand ${VAR} placeholders using os.environ."""
    if isinstance(obj, str):
        def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
            return os.environ.get(m.group(1), "")
        return re.sub(r"\$\{([^}]+)\}", _replace, obj)
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(i) for i in obj]
    return obj


def load_config(config_path: str = "claw-forge.yaml") -> dict:
    """Load YAML config, expand ${ENV_VAR} placeholders, return as dict.

    Raises ConfigError if the file is not found or cannot be parsed.
    """
    import yaml  # imported here so callers that don't need yaml don't pay the cost

    path = Path(config_path)
    if not path.exists():
        raise ConfigError(f"Config not found: {path}")

    # Auto-load .env alongside the config
    env_file = path.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

    raw = yaml.safe_load(path.read_text())
    return _expand_env_vars(raw)  # type: ignore[return-value]
