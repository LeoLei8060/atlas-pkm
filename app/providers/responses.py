from __future__ import annotations

from typing import Any

from .base import BaseProvider, ChatResult, ProviderNotConfigured, response_error
from .openai import OpenAIProvider


class OpenAIResponsesProvider(OpenAIProvider):
    """OpenAI Responses API (/responses), used by Codex-style gateways."""

    name = "openai-responses"

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

        body: dict[str, Any] = {
            "model": self.model,
            "input": [
                {"role": str(item.get("role") or "user"), "content": str(item.get("content") or "")}
                for item in messages
            ],
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            body["instructions"] = system
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with self.http() as client:
            response = await client.post(
                f"{self.base_url}/responses", json=body, headers=headers
            )
        if response.status_code >= 400:
            raise response_error(response)
        data = response.json()
        texts: list[str] = []
        for block in data.get("output") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "message":
                for part in block.get("content") or []:
                    if isinstance(part, dict) and part.get("type") == "output_text":
                        texts.append(str(part.get("text") or ""))
            elif block.get("type") == "output_text":
                texts.append(str(block.get("text") or ""))
        text = "".join(texts).strip()
        if not text:
            text = str(data.get("output_text") or "").strip()
        if not text:
            raise response_error(response)
        usage = data.get("usage")
        return ChatResult(
            text=text,
            provider=self.name,
            model=self.model,
            raw=data,
            usage=usage if isinstance(usage, dict) else None,
        )
