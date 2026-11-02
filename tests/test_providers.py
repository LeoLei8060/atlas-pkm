from __future__ import annotations

from app.providers import (
    AnthropicProvider,
    OpenAIProvider,
    OpenAIResponsesProvider,
    build_provider,
)


def test_custom_provider_protocol_mapping():
    base = {
        "api_key": "test-key",
        "model": "test-model",
        "base_url": "https://gateway.example.com/v1",
    }
    openai = build_provider("my-gateway", {**base, "protocol": "openai-compatible"})
    anthropic = build_provider("my-gateway", {**base, "protocol": "anthropic-compatible"})
    responses = build_provider("my-gateway", {**base, "protocol": "openai-responses"})
    assert isinstance(openai, OpenAIProvider)
    assert isinstance(anthropic, AnthropicProvider)
    assert isinstance(responses, OpenAIResponsesProvider)
    assert openai.name == "my-gateway"
    assert anthropic.name == "my-gateway"
    assert responses.name == "my-gateway"
    assert anthropic.base_url == "https://gateway.example.com/v1"
