from __future__ import annotations

import asyncio

import httpx

from app.services.devto import fetch_devto, ingest_devto
from app.services.feeds import list_feed, list_sources

ARTICLES = [
    {
        "title": "Rust async in practice",
        "description": "A practical guide to Rust async.",
        "url": "https://dev.to/example/rust-async",
        "published_at": "2026-10-28T10:00:00Z",
        "tag_list": ["rust", "async"],
        "user": {"name": "Alice"},
    }
]


def _client():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "dev.to/api/articles" in str(request.url)
        return httpx.Response(200, json=ARTICLES)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_fetch_devto(isolated):
    items = asyncio.run(fetch_devto("rust", client=_client()))
    assert len(items) == 1
    assert items[0]["title"] == "Rust async in practice"
    assert items[0]["source_type"] == "devto"


def test_ingest_devto(isolated):
    result = asyncio.run(ingest_devto("rust", client=_client()))
    assert result["new"] == 1
    assert list_feed()[0]["source_type"] == "devto"
    sources = list_sources("devto")
    assert sources[0]["last_status"] == "ok"
    assert sources[0]["item_count"] == 1
