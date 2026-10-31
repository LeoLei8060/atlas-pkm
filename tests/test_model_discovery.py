from __future__ import annotations

import asyncio
import json

import httpx

from app.providers.anthropic import AnthropicProvider
from app.providers.gemini import GeminiProvider
from app.providers.openai import OpenAIProvider


def _client(payload: dict, path: str):
    def handler(request: httpx.Request) -> httpx.Response:
        assert path in str(request.url)
        return httpx.Response(200, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_openai_list_models():
    provider = OpenAIProvider(
        {
            "api_key": "key",
            "model": "m",
            "base_url": "https://gateway.example.com/v1",
        },
        client=_client({"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]}, "/models"),
    )
    models = asyncio.run(provider.list_models())
    assert models == ["gpt-4o", "gpt-4o-mini"]


def test_anthropic_list_models():
    provider = AnthropicProvider(
        {
            "api_key": "key",
            "model": "m",
            "base_url": "https://gateway.example.com/v1",
        },
        client=_client({"data": [{"id": "claude-3-5-sonnet"}]}, "/models"),
    )
    models = asyncio.run(provider.list_models())
    assert models == ["claude-3-5-sonnet"]


def test_gemini_list_models():
    provider = GeminiProvider(
        {
            "api_key": "key",
            "model": "m",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
        },
        client=_client(
            {
                "models": [
                    {"name": "models/gemini-2.0-flash", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
                ]
            },
            "/models",
        ),
    )
    models = asyncio.run(provider.list_models())
    assert models == ["gemini-2.0-flash"]
