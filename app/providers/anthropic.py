from __future__ import annotations

from typing import Any

from .base import BaseProvider, ChatResult, ProviderNotConfigured, response_error


class AnthropicProvider(BaseProvider):
    name = "anthropic"
    default_base_url = "https://api.anthropic.com/v1"

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> ChatResult:
        if not self.configured:
            raise ProviderNotConfigured()

        payload: list[dict[str, str]] = [
            {"role": "user" if item.get("role") != "assistant" else "assistant",
             "content": str(item.get("content", ""))}
            for item in messages
        ]
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": payload,
        }
        if system:
            body["system"] = system
        headers = self.request_headers({
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        })
        async with self.http() as client:
            response = await client.post(
                f"{self.base_url}/messages", json=body, headers=headers
            )
        if response.status_code >= 400:
            raise response_error(response)
        data = response.json()
        blocks = data.get("content") or []
        text = "".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
        usage = data.get("usage")
        return ChatResult(
            text=text,
            provider=self.name,
            model=self.model,
            raw=data,
            usage=usage if isinstance(usage, dict) else None,
        )

    async def list_models(self) -> list[str]:
        if not self.api_key:
            raise ProviderNotConfigured()
        headers = self.request_headers({
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        })
        async with self.http() as client:
            response = await client.get(
                f"{self.base_url}/models",
                headers=headers,
                params={"limit": 100},
            )
        if response.status_code >= 400:
            raise response_error(response)
        data = response.json()
        models = []
        for row in data.get("data") or []:
            model_id = row.get("id") if isinstance(row, dict) else None
            if model_id and model_id not in models:
                models.append(str(model_id))
        return sorted(models)
