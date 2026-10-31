from __future__ import annotations

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


async def fetch_devto(
    tag: str = "",
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
    params: dict[str, Any] = {"top": 7, "per_page": max(1, min(limit, 20))}
    if tag.strip():
        params["tag"] = tag.strip()
    try:
        response = await client.get("https://dev.to/api/articles", params=params)
    except httpx.HTTPError as exc:
        raise FeedError(f"Dev.to 请求失败: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()
    if response.status_code >= 400:
        raise FeedError(f"Dev.to 返回 {response.status_code}: {response.text[:200]}")
    payload = response.json()
    items = []
    for article in payload if isinstance(payload, list) else []:
        title = str(article.get("title") or "").strip()
        url = str(article.get("url") or "").strip()
        if not title or not url:
            continue
        description = strip_html(str(article.get("description") or ""), 1200)
        items.append(
            {
                "title": title,
                "url": url,
                "canonical_url": canonicalize_url(url),
                "summary": description,
                "content": description,
                "author": str((article.get("user") or {}).get("name") or ""),
                "published_at": str(article.get("published_at") or ""),
                "tags": article.get("tag_list") or [],
                "source_type": "devto",
                "source_name": "Dev.to",
            }
        )
    return items


async def ingest_devto(
    tag: str = "",
    *,
    limit: int = 10,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    label = f"Dev.to {tag}".strip()
    source_url = f"https://dev.to/t/{quote(tag)}" if tag.strip() else "https://dev.to/top/week"
    source_id = ensure_source("devto", label, source_url)
    try:
        items = await fetch_devto(tag, limit=limit, client=client)
        fetched_count = len(items)
        items, filtered_out = filter_feed_items(items)
        new_ids = []
        for item in items:
            item["source_id"] = source_id
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
