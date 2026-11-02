from __future__ import annotations

from typing import Any

from .base import BaseProvider, ChatResult, ProviderNotConfigured, response_error


class OpenAIProvider(BaseProvider):
    name = "openai"
    default_base_url = "https://api.openai.com/v1"

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

        payload_messages: list[dict[str, str]] = []
        if system:
            payload_messages.append({"role": "system", "content": system})
        payload_messages.extend(messages)
        body: dict[str, Any] = {
            "model": self.model,
            "messages": payload_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        headers = self.request_headers({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })
        async with self.http() as client:
            response = await client.post(
                f"{self.base_url}/chat/completions", json=body, headers=headers
            )
        if response.status_code >= 400:
            raise response_error(response)
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise response_error(response)
        message = choices[0].get("message") or {}
        content = message.get("content", "")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        return ChatResult(
            text=str(content or ""),
            provider=self.name,
            model=self.model,
            raw=data,
            usage=data.get("usage"),
        )

    async def list_models(self) -> list[str]:
        if not self.api_key:
            raise ProviderNotConfigured()
        headers = self.request_headers({"Authorization": f"Bearer {self.api_key}"})
        async with self.http() as client:
            response = await client.get(f"{self.base_url}/models", headers=headers)
        if response.status_code >= 400:
            raise response_error(response)
        data = response.json()
        rows = data.get("data") if isinstance(data, dict) else data
        models = []
        for row in rows or []:
            model_id = row.get("id") if isinstance(row, dict) else None
            if model_id and model_id not in models:
                models.append(str(model_id))
        return sorted(models)


class DeepSeekProvider(OpenAIProvider):
    name = "deepseek"
    default_base_url = "https://api.deepseek.com/v1"
