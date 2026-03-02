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
}


def _import_class(dotted_path: str) -> type[BaseProvider]:
    """Import a class from a dotted module path."""
    module_path, class_name = dotted_path.rsplit(".", 1)
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, class_name)  # type: ignore[no-any-return]


def create_provider(config: ProviderConfig) -> BaseProvider:
    """Create a provider instance from config."""
    dotted = _PROVIDER_CLASSES.get(config.provider_type)
    if not dotted:
        raise ValueError(f"Unknown provider type: {config.provider_type}")
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
    """Parse provider configs from YAML dict."""
    configs: list[ProviderConfig] = []
    for name, raw in data.get("providers", {}).items():
        ptype = ProviderType(raw.pop("type", raw.pop("provider_type", "anthropic")))
        configs.append(
            ProviderConfig(
                name=name,
                provider_type=ptype,
                **{k: v for k, v in raw.items() if k in ProviderConfig.__dataclass_fields__},
            )
        )
    return configs
