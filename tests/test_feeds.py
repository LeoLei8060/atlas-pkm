from __future__ import annotations

import asyncio
import json

import httpx

from app.services.feeds import fetch_github, ingest_rss, list_feed, list_sources
from app.services.extract import fetch_article_text

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Demo</title>
<item><title>Rust async</title><link>https://example.com/a</link>
<description>Cancel safely.</description></item>
</channel></rss>"""


def test_ingest_rss_with_mock_client(isolated):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=RSS)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(ingest_rss("https://example.com/feed", client=client))
    assert result["fetched"] == 1
    assert result["new"] == 1
    items = list_feed()
    assert items[0]["title"] == "Rust async"
    assert items[0]["canonical_url"] == "https://example.com/a"
    sources = list_sources("rss")
    assert len(sources) == 1
    assert sources[0]["last_status"] == "ok"
    assert sources[0]["item_count"] == 1


def test_ingest_rss_extracts_all_items(isolated):
    items = "".join(
        f"<item><title>Post {index}</title><link>https://example.com/post-{index}</link>"
        f"<description>Short summary.</description></item>"
        for index in range(12)
    )
    feed = f'<?xml version="1.0"?><rss version="2.0"><channel><title>Demo</title>{items}</channel></rss>'
    article = "<html><body><article><p>" + ("Full article body. " * 30) + "</p></article></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/feed":
            return httpx.Response(200, text=feed)
        return httpx.Response(200, text=article, headers={"content-type": "text/html"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(ingest_rss("https://example.com/feed", client=client))
    assert result["fetched"] == 12
    assert result["extracted"] == 12
    assert len(list_feed()) == 12


def test_ignored_feed_item_is_not_updated(isolated):
    from app.services.feeds import _upsert_feed_item, get_feed, update_feed

    item = {
        "url": "https://example.com/ignored",
        "canonical_url": "https://example.com/ignored",
        "title": "First title",
        "summary": "first",
        "content": "first",
        "source_type": "rss",
    }
    feed_id, created = _upsert_feed_item(item)
    assert created
    update_feed(feed_id, status="dismissed")
    _upsert_feed_item({**item, "title": "Changed title", "content": "changed"})
    assert get_feed(feed_id)["title"] == "First title"


def test_fetch_github_maps_repository(isolated):
    payload = {
        "items": [
            {
                "full_name": "tokio-rs/tokio",
                "html_url": "https://github.com/tokio-rs/tokio",
                "description": "Async runtime",
                "stargazers_count": 100,
                "forks_count": 10,
                "language": "Rust",
                "created_at": "2026-10-01T00:00:00Z",
                "topics": ["async"],
                "license": {"spdx_id": "MIT"},
                "owner": {"login": "tokio-rs"},
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "search/repositories" in str(request.url)
        return httpx.Response(200, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    items = asyncio.run(fetch_github(days=7, limit=10, client=client))
    assert len(items) == 1
    item = items[0]
    assert item["repo_full_name"] == "tokio-rs/tokio"
    assert item["stars"] == 100
    assert item["license"] == "MIT"
    assert item["primary_language"] == "Rust"
    assert item["source_type"] == "github"


def test_extract_article_text(isolated):
    html = """<html><body><nav>Menu</nav><article>
    <h1>Rust Async</h1>
    <p>Rust async uses futures and an executor to drive asynchronous computations.</p>
    <p>Cancellation safety means a future can be dropped at an await point without
    leaving inconsistent shared state behind.</p>
    <p>Tokio's select! macro cancels the branches that do not complete.</p>
    </article></body></html>"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    text = asyncio.run(fetch_article_text("https://example.com/a", client=client))
    assert "Cancellation safety" in text
    assert "select!" in text
    assert "Menu" not in text
