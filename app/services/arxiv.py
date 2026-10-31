from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

import httpx

from .feeds import (
    FeedError,
    _upsert_feed_item,
    ensure_source,
    filter_feed_items,
    touch_source,
)
from .text import canonicalize_url, strip_html

ATOM = {"a": "http://www.w3.org/2005/Atom"}


async def fetch_arxiv(
    query: str,
    *,
    limit: int = 10,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    owns_client = client is None
    client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(45.0, connect=15.0),
        follow_redirects=True,
        trust_env=False,
        headers={"User-Agent": "AI-PKM-Agent/0.1"},
    )
    try:
        response = await client.get(
            "https://export.arxiv.org/api/query",
            params={
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": max(1, min(limit, 20)),
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            },
        )
    except httpx.HTTPError as exc:
        raise FeedError(f"arXiv 请求失败: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()
    if response.status_code >= 400:
        raise FeedError(f"arXiv 返回 {response.status_code}: {response.text[:200]}")
    try:
        root = ET.fromstring(response.text)
    except ET.ParseError as exc:
        raise FeedError(f"arXiv 返回格式错误: {exc}") from exc

    items = []
    for entry in root.findall("a:entry", ATOM):
        title = " ".join((entry.findtext("a:title", default="", namespaces=ATOM) or "").split())
        abstract = strip_html(entry.findtext("a:summary", default="", namespaces=ATOM) or "")
        url = entry.findtext("a:id", default="", namespaces=ATOM) or ""
        for link in entry.findall("a:link", ATOM):
            if link.get("rel") == "alternate" and link.get("href"):
                url = link.get("href")
                break
        if not title or not url:
            continue
        authors = [
            author.findtext("a:name", default="", namespaces=ATOM)
            for author in entry.findall("a:author", ATOM)
        ]
        categories = [category.get("term", "") for category in entry.findall("a:category", ATOM)]
        items.append(
            {
                "title": title,
                "url": url,
                "canonical_url": canonicalize_url(url),
                "summary": abstract,
                "content": abstract,
                "author": ", ".join(author for author in authors if author)[:200],
                "published_at": entry.findtext("a:published", default="", namespaces=ATOM)
                or "",
                "tags": [category for category in categories if category],
                "source_type": "arxiv",
                "source_name": "arXiv",
            }
        )
    return items


async def ingest_arxiv(
    query: str,
    *,
    limit: int = 10,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        raise FeedError("arXiv 搜索词不能为空")
    source_url = f"https://arxiv.org/search/?query={quote(query)}&searchtype=all"
    source_id = ensure_source("arxiv", f"arXiv: {query}", source_url)
    try:
        items = await fetch_arxiv(query, limit=limit, client=client)
        fetched_count = len(items)
        items, filtered_out = filter_feed_items(items)
        new_ids = []
        for item in items:
            item["source_id"] = source_id
            item["source_name"] = f"arXiv: {query}"
            feed_id, created = _upsert_feed_item(item)
            if created:
                new_ids.append(feed_id)
        touch_source(source_id, "ok")
        return {
            "fetched": fetched_count,
            "kept": len(items),
            "filtered_out": filtered_out,
            "new": len(new_ids),
            "ids": new_ids,
        }
    except Exception as exc:
        touch_source(source_id, "error", str(exc))
        raise
