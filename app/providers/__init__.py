from __future__ import annotations

from typing import Any

import httpx

from .anthropic import AnthropicProvider
from .base import BaseProvider, ProviderError, ProviderNotConfigured
from .gemini import GeminiProvider
from .openai import DeepSeekProvider, OpenAIProvider
from .responses import OpenAIResponsesProvider

PROVIDERS: dict[str, type[BaseProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "deepseek": DeepSeekProvider,
}

PROVIDER_LABELS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Google Gemini",
    "deepseek": "DeepSeek",
}


def build_provider(
    name: str,
    config: dict[str, Any],
    client: httpx.AsyncClient | None = None,
) -> BaseProvider:
    cls = PROVIDERS.get(name)
    if cls is None:
        protocol = str(config.get("protocol") or "openai-compatible").lower()
        if protocol in {"anthropic", "anthropic-compatible"}:
            cls = AnthropicProvider
        elif protocol in {"responses", "openai-responses"}:
            cls = OpenAIResponsesProvider
        elif protocol in {"openai", "openai-compatible"}:
            cls = OpenAIProvider
        else:
            raise ProviderError(f"不支持的第三方模型协议: {protocol}", 400)
    provider = cls(config, client=client)
    if name not in PROVIDERS:
        provider.name = name
    return provider


def provider_from_config(
    config: dict[str, Any],
    name: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> BaseProvider:
    name = name or str(config.get("active_provider") or "openai")
    item = (config.get("providers") or {}).get(name) or {}
    provider = build_provider(name, item, client=client)
    if not provider.configured:
        label = str(item.get("label") or PROVIDER_LABELS.get(name, name))
        raise ProviderNotConfigured(f"{label} 还没有配置 API Key")
    return provider
