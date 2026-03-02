"""Resolve provider/model strings from CLI args and config aliases."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ResolvedModel:
    provider_hint: str | None  # e.g. "anthropic-proxy-1" or None
    model_id: str              # e.g. "claude-opus-4-5"
    raw: str                   # original input string
    alias_resolved: bool       # True if input was an alias


def _split_provider_model(s: str) -> tuple[str | None, str]:
    """Split 'provider/model' into (provider, model).

    Handles model IDs that contain ':' (e.g. ollama/qwen2.5:32b).
    Only splits on the FIRST '/' — everything after is the model id.
    Returns (None, s) if no '/' present.
    """
    if "/" in s:
        provider, _, model = s.partition("/")
        return provider, model
    return None, s


def resolve_model(
    model_str: str, config: dict[str, Any] | None = None
) -> ResolvedModel:
    """Resolve a --model argument to (provider_hint, model_id).

    Resolution order:
    1. Check model_aliases in config (if provided) — single level, no recursive chasing
    2. Check provider/model format (contains "/")
    3. Bare model name → provider_hint=None, pool picks best provider

    Examples:
        resolve_model("anthropic-proxy-1/claude-opus-4-5")
            → ResolvedModel(provider_hint="anthropic-proxy-1", model_id="claude-opus-4-5", ...)
        resolve_model("claude-opus-4-5")
            → ResolvedModel(provider_hint=None, model_id="claude-opus-4-5", ...)
        resolve_model("opus", config={"model_aliases": {"opus": "claude-opus-4-5"}})
            → ResolvedModel(provider_hint=None, model_id="claude-opus-4-5", alias_resolved=True)
        resolve_model("opus", config={"model_aliases": {
            "opus": "anthropic-proxy-1/claude-opus-4-5"}})
            → ResolvedModel(provider_hint="anthropic-proxy-1", model_id="claude-opus-4-5",
                            alias_resolved=True)
    """
    aliases: dict[str, str] = {}
    if config and isinstance(config.get("model_aliases"), dict):
        aliases = config["model_aliases"]

    # Step 1: check aliases (no recursive chasing — prevents infinite loops)
    if model_str in aliases:
        resolved_value = str(aliases[model_str])
        provider_hint, model_id = _split_provider_model(resolved_value)
        return ResolvedModel(
            provider_hint=provider_hint,
            model_id=model_id,
            raw=model_str,
            alias_resolved=True,
        )

    # Step 2: provider/model format
    if "/" in model_str:
        provider_hint, model_id = _split_provider_model(model_str)
        return ResolvedModel(
            provider_hint=provider_hint,
            model_id=model_id,
            raw=model_str,
            alias_resolved=False,
        )

    # Step 3: bare model name
    return ResolvedModel(
        provider_hint=None,
        model_id=model_str,
        raw=model_str,
        alias_resolved=False,
    )
