from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx


class ProviderError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ProviderNotConfigured(ProviderError):
    def __init__(self, message: str = "还没有配置模型 API Key"):
        super().__init__(message, status_code=400)


@dataclass
class ChatResult:
    text: str
    provider: str
    model: str
    raw: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] | None = None


DEFAULT_THIRD_PARTY_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class BaseProvider:
    name = "base"
    default_base_url = ""

    def __init__(
        self,
        config: dict[str, Any],
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config or {}
        self.api_key = str(self.config.get("api_key") or "").strip()
        self.model = str(self.config.get("model") or "").strip()
        self.base_url = str(self.config.get("base_url") or self.default_base_url).rstrip("/")
        self.user_agent = str(self.config.get("user_agent") or "").strip()
        self._client = client

    def request_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(extra or {})
        if self.user_agent:
            headers["User-Agent"] = self.user_agent
        return headers

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model)

    @asynccontextmanager
    async def http(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(90.0, connect=15.0),
            trust_env=False,
        ) as client:
            yield client

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> ChatResult:
        raise NotImplementedError

    async def list_models(self) -> list[str]:
        raise NotImplementedError

    async def ping(self) -> str:
        result = await self.chat(
            [{"role": "user", "content": "Reply with the single word OK."}],
            temperature=0,
            max_tokens=12,
        )
        return result.text.strip()[:80]


def response_error(response: httpx.Response) -> ProviderError:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message") or error.get("status") or str(error)
            else:
                message = payload.get("message") or str(payload)
        else:
            message = str(payload)
    except Exception:
        message = response.text[:600]
    return ProviderError(f"模型接口返回 {response.status_code}: {message}", response.status_code)
