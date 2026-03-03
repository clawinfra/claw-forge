"""Auto-discover and instantiate providers from config."""

from __future__ import annotations

import logging
from typing import Any

from claw_forge.pool.providers.base import BaseProvider, ProviderConfig, ProviderType

logger = logging.getLogger(__name__)

_PROVIDER_CLASSES: dict[ProviderType, str] = {
    ProviderType.ANTHROPIC: "claw_forge.pool.providers.anthropic.AnthropicProvider",
    ProviderType.BEDROCK: "claw_forge.pool.providers.bedrock.BedrockProvider",
    ProviderType.AZURE: "claw_forge.pool.providers.azure.AzureProvider",
    ProviderType.VERTEX: "claw_forge.pool.providers.vertex.VertexProvider",
    ProviderType.OPENAI_COMPAT: "claw_forge.pool.providers.openai_compat.OpenAICompatProvider",
    ProviderType.ANTHROPIC_COMPAT: "claw_forge.pool.providers.anthropic_compat.AnthropicCompatProvider",  # noqa: E501
    # anthropic_oauth auto-reads the Claude CLI token and delegates to AnthropicProvider
    ProviderType.ANTHROPIC_OAUTH: "claw_forge.pool.providers.anthropic.AnthropicProvider",
    # Local Ollama instance via OpenAI-compat endpoint
    ProviderType.OLLAMA: "claw_forge.pool.providers.ollama.OllamaProvider",
}


def _import_class(dotted_path: str) -> type[BaseProvider]:
    """Import a class from a dotted module path."""
    module_path, class_name = dotted_path.rsplit(".", 1)
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, class_name)  # type: ignore[no-any-return]


def create_provider(config: ProviderConfig) -> BaseProvider:
    """Create a provider instance from config.

    For ``anthropic_oauth`` provider type, the Claude CLI OAuth token is
    auto-read from disk and injected into ``config.oauth_token`` before
    the :class:`~claw_forge.pool.providers.anthropic.AnthropicProvider` is
    instantiated.  A ``ValueError`` is raised if no token can be found.
    """
    ptype = config.provider_type
    if ptype == ProviderType.ANTHROPIC_OAUTH:
        import dataclasses

        import claw_forge.pool.providers.oauth as _oauth_mod

        token = _oauth_mod.get_oauth_token_optional()
        if token:
            # Inject the OAuth token so AnthropicProvider uses Bearer auth.
            config = dataclasses.replace(config, oauth_token=token)
        elif config.api_key:
            # No credentials file but an api_key was supplied — fall back silently.
            logger.debug(
                "anthropic_oauth provider '%s': no OAuth credentials file found; "
                "falling back to api_key auth.",
                config.name,
            )
        else:
            raise ValueError(
                f"anthropic_oauth provider '{config.name}': "
                "no OAuth credentials file (~/.claude/.credentials.json) found "
                "and no api_key supplied. "
                "Run `claude login` first, set oauth_token explicitly, or provide api_key."
            )

    dotted = _PROVIDER_CLASSES.get(ptype)
    if not dotted:
        raise ValueError(f"Unknown provider type: {ptype}")
    cls = _import_class(dotted)
    return cls(config)


def create_providers_from_configs(configs: list[ProviderConfig]) -> list[BaseProvider]:
    """Create all providers, skipping ones that fail to initialize."""
    providers: list[BaseProvider] = []
    for cfg in configs:
        if not cfg.enabled:
            logger.info("Skipping disabled provider: %s", cfg.name)
            continue
        try:
            providers.append(create_provider(cfg))
        except Exception:
            logger.exception("Failed to create provider '%s'", cfg.name)
    return providers


def load_configs_from_yaml(data: dict[str, Any]) -> list[ProviderConfig]:
    """Parse provider configs from YAML dict.

    Supports two provider formats:

    Dict format (default, keyed by name)::

        providers:
          my-provider:
            type: anthropic
            api_key: sk-...

    List format (alternative)::

        providers:
          - name: my-provider
            type: anthropic
            api_key: sk-...
    """
    configs: list[ProviderConfig] = []
    raw_providers = data.get("providers", {})

    if isinstance(raw_providers, list):
        # List format: each item must have a 'name' key
        items: list[tuple[str, dict[str, Any]]] = []
        for entry in raw_providers:
            entry = dict(entry)  # copy so pop() is safe
            name = entry.pop("name", f"provider-{len(items)}")
            items.append((name, entry))
    elif isinstance(raw_providers, dict):
        items = [(name, dict(raw)) for name, raw in raw_providers.items()]
    else:
        return configs

    for name, raw in items:
        try:
            ptype = ProviderType(raw.pop("type", raw.pop("provider_type", "anthropic")))
            configs.append(
                ProviderConfig(
                    name=name,
                    provider_type=ptype,
                    **{
                        k: v
                        for k, v in raw.items()
                        if k in ProviderConfig.__dataclass_fields__
                    },
                )
            )
        except Exception:
            logger.exception("Failed to parse provider config '%s'", name)

    return configs
