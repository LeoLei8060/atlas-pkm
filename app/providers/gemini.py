from __future__ import annotations

from typing import Any

from .base import BaseProvider, ChatResult, ProviderNotConfigured, response_error


class GeminiProvider(BaseProvider):
    name = "gemini"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"

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

        contents: list[dict[str, Any]] = []
        for item in messages:
            role = "model" if item.get("role") == "assistant" else "user"
            contents.append(
                {"role": role, "parts": [{"text": str(item.get("content", ""))}]}
            )
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        model = self.model
        if model.startswith("models/"):
            model = model.split("/", 1)[1]
        url = f"{self.base_url}/models/{model}:generateContent"
        async with self.http() as client:
            response = await client.post(
                url,
                params={"key": self.api_key},
                json=body,
                headers={"Content-Type": "application/json"},
            )
        if response.status_code >= 400:
            raise response_error(response)
        data = response.json()
        candidates = data.get("candidates") or []
        text = ""
        if candidates:
            parts = (candidates[0].get("content") or {}).get("parts") or []
            text = "".join(
                part.get("text", "") for part in parts if isinstance(part, dict)
            )
        usage = data.get("usageMetadata")
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
        async with self.http() as client:
            response = await client.get(
                f"{self.base_url}/models",
                params={"key": self.api_key, "pageSize": 1000},
            )
        if response.status_code >= 400:
            raise response_error(response)
        data = response.json()
        models = []
        for row in data.get("models") or []:
            name = str(row.get("name") or "")
            if name.startswith("models/"):
                name = name.split("/", 1)[1]
            methods = row.get("supportedGenerationMethods") or []
            if name and (not methods or "generateContent" in methods):
                if name not in models:
                    models.append(name)
        return sorted(models)
