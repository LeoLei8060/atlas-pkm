from __future__ import annotations

import asyncio

import httpx

from app.services.arxiv import fetch_arxiv, ingest_arxiv
from app.services.feeds import list_feed, list_sources

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>https://arxiv.org/abs/2610.00001v1</id>
    <published>2026-10-28T10:00:00Z</published>
    <title>Agent Skills for Retrieval</title>
    <summary>A paper about agent skills and retrieval.</summary>
    <author><name>Alice</name></author>
    <category term="cs.AI"/>
    <link rel="alternate" href="https://arxiv.org/abs/2610.00001v1"/>
  </entry>
</feed>"""


def _client():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "export.arxiv.org" in str(request.url)
        return httpx.Response(
            200, text=ATOM, headers={"content-type": "application/atom+xml"}
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_fetch_arxiv(isolated):
    items = asyncio.run(fetch_arxiv("agent skills", client=_client()))
    assert len(items) == 1
    assert items[0]["title"] == "Agent Skills for Retrieval"
    assert items[0]["source_type"] == "arxiv"
    assert "cs.AI" in items[0]["tags"]


def test_ingest_arxiv(isolated):
    result = asyncio.run(ingest_arxiv("agent skills", client=_client()))
    assert result["fetched"] == 1
    assert result["new"] == 1
    feed = list_feed()
    assert feed[0]["source_type"] == "arxiv"
    sources = list_sources("arxiv")
    assert sources[0]["last_status"] == "ok"
    assert sources[0]["item_count"] == 1
