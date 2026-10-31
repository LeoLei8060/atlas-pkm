from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .arxiv import fetch_arxiv
from .devto import fetch_devto
from .extract import fetch_article_text
from .feeds import (
    FeedError,
    _upsert_feed_item,
    filter_feed_items,
    filter_recent_items,
    fetch_rss,
    touch_source,
)
from .github_rankings import search_github
from .text import canonicalize_url, strip_html

USER_AGENT = "Mozilla/5.0 (compatible; Atlas-PKM/0.2; +https://localhost)"
CSDN_RSS = "https://blog.csdn.net/{user}/rss/list"
QT_RSS = "https://www.qt.io/blog/rss.xml"


def _has_any(haystack: str, terms: list[str]) -> bool:
    lowered = haystack.lower()
    return any(str(term).lower() in lowered for term in terms if str(term).strip())


def _apply_source_rules(
    items: list[dict[str, Any]], config: dict[str, Any]
) -> tuple[list[dict[str, Any]], int]:
    include = [str(value) for value in config.get("include_any") or [] if str(value).strip()]
    exclude = [str(value) for value in config.get("exclude_any") or [] if str(value).strip()]
    if not include and not exclude:
        return items, 0
    kept: list[dict[str, Any]] = []
    for item in items:
        text = " ".join(
            [
                str(item.get("title") or ""),
                str(item.get("summary") or ""),
                str(item.get("content") or ""),
                " ".join(str(tag) for tag in item.get("tags") or []),
            ]
        )
        if include and not _has_any(text, include):
            continue
        if exclude and _has_any(text, exclude):
            continue
        kept.append(item)
    return kept, len(items) - len(kept)


async def _extract_article_content(items: list[dict[str, Any]]) -> None:
    semaphore = asyncio.Semaphore(6)

    async def extract_one(item: dict[str, Any]) -> None:
        raw = str(item.get("content") or item.get("summary") or "")
        if len(raw.strip()) >= 600 or not item.get("url"):
            return
        async with semaphore:
            try:
                article = await asyncio.wait_for(
                    fetch_article_text(str(item["url"])), timeout=20
                )
            except Exception:
                return
        if article and len(article) > len(raw.strip()):
            item["content"] = article
            item["summary"] = article[:1200]

    await asyncio.gather(*(extract_one(item) for item in items))


def _store_items(
    source: dict[str, Any],
    items: list[dict[str, Any]],
    config: dict[str, Any],
    source_type: str,
) -> dict[str, Any]:
    raw_count = len(items)
    items, time_dropped = filter_recent_items(items, config)
    items, rule_dropped = _apply_source_rules(items, source.get("config") or {})
    for item in items:
        item["source_id"] = source["id"]
        item["source_type"] = source_type
        item["source_name"] = source.get("name") or source_type
    items, profile_dropped = filter_feed_items(items, config)
    changed_ids: list[str] = []
    new_count = 0
    for item in items:
        feed_id, created = _upsert_feed_item(item)
        if created:
            new_count += 1
        if created or item.get("_changed"):
            changed_ids.append(feed_id)
    return {
        "fetched": raw_count,
        "kept": len(items),
        "filtered_out": time_dropped + rule_dropped + profile_dropped,
        "window_dropped": time_dropped,
        "new": new_count,
        "ids": changed_ids,
    }


def _site_name(html: str, fallback: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.string if soup.title and soup.title.string else "").strip()
    return title[:120] or fallback


def _csdn_user(url: str) -> str:
    parsed = urlparse(url)
    if "csdn.net" not in parsed.netloc:
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    return parts[0] if parts else ""


def _extract_feed_url(html: str, page_url: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for link in soup.find_all("link", href=True):
        rel = " ".join(link.get("rel") or []).lower()
        kind = (link.get("type") or "").lower()
        if "alternate" in rel and ("rss" in kind or "atom" in kind or "xml" in kind):
            href = urljoin(page_url, link["href"])
            if href.startswith(("http://", "https://")):
                return href
    return ""


def _extract_links(html: str, page_url: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    item_selector = str(config.get("item_selector") or "article")
    nodes = soup.select(item_selector)
    if not nodes:
        nodes = soup.select("main article, .post, .blog-post, li")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in nodes[:50]:
        if node.name == "a" and node.get("href"):
            link = node
        else:
            link = node.select_one(str(config.get("link_selector") or "a[href]"))
        if not link or not link.get("href"):
            continue
        href = urljoin(page_url, link["href"])
        if not href.startswith(("http://", "https://")) or href in seen:
            continue
        seen.add(href)
        title = " ".join(link.get_text(" ", strip=True).split())
        if len(title) < 4:
            continue
        summary_node = node.select_one(str(config.get("summary_selector") or "p"))
        summary = (
            " ".join(summary_node.get_text(" ", strip=True).split())
            if summary_node
            else ""
        )
        date_node = node.select_one(str(config.get("date_selector") or "time"))
        published = ""
        if date_node:
            published = str(date_node.get("datetime") or date_node.get_text(strip=True))
        items.append(
            {
                "title": title[:300],
                "url": href,
                "canonical_url": canonicalize_url(href),
                "summary": strip_html(summary, 1200),
                "content": strip_html(summary, 4000),
                "author": "",
                "published_at": published,
                "tags": [],
                "source_type": "html",
            }
        )
    return items


async def discover_source(url: str) -> dict[str, Any]:
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise FeedError("地址必须是 http(s)")
    parsed = urlparse(url)
    if "csdn.net" in parsed.netloc:
        user = _csdn_user(url)
        if not user:
            raise FeedError("无法从 CSDN 地址识别博主用户名")
        return {
            "group": "other",
            "adapter": "csdn",
            "name": f"CSDN: {user}",
            "url": url if "/article/" in url else f"https://blog.csdn.net/{user}",
            "config": {
                "user": user,
                "rss_url": CSDN_RSS.format(user=user),
                "mode": "rss",
            },
        }
    if "qt.io" in parsed.netloc and "blog" in parsed.path:
        return {
            "group": "other",
            "adapter": "qt",
            "name": "Qt Blog",
            "url": "https://www.qt.io/blog",
            "config": {"rss_url": QT_RSS},
        }
    if re.search(r"(\.rss|\.xml|/feed|/rss)(/|$|\?)", url, re.I):
        return {
            "group": "other",
            "adapter": "rss",
            "name": parsed.netloc,
            "url": url,
            "config": {"feed_url": url},
        }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=8.0),
            follow_redirects=True,
            trust_env=False,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        raise FeedError(f"无法访问页面: {exc}") from exc
    if response.status_code >= 400:
        raise FeedError(f"页面返回 {response.status_code}")
    feed_url = _extract_feed_url(response.text, str(response.url))
    name = _site_name(response.text, parsed.netloc)
    if feed_url:
        return {
            "group": "other",
            "adapter": "rss",
            "name": name,
            "url": url,
            "config": {"feed_url": feed_url, "discovered": True},
        }
    return {
        "group": "other",
        "adapter": "html",
        "name": name,
        "url": url,
        "config": {
            "list_url": url,
            "item_selector": "article",
            "link_selector": "a[href]",
        },
    }


async def _fetch_html_items(source: dict[str, Any]) -> list[dict[str, Any]]:
    config = source.get("config") or {}
    url = str(config.get("list_url") or source.get("url") or "")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(25.0, connect=8.0),
        follow_redirects=True,
        trust_env=False,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        response = await client.get(url)
    if response.status_code >= 400:
        raise FeedError(f"页面返回 {response.status_code}")
    return _extract_links(response.text, str(response.url), config)


async def fetch_source(source: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    adapter = source.get("adapter") or "rss"
    source_config = source.get("config") or {}
    token = str(config.get("github_token") or "")
    source_type = adapter
    if adapter in {"github_search", "github_repo"}:
        query = str(source_config.get("query") or "").strip()
        if not query:
            raise FeedError("GitHub 订阅需要查询词")
        if adapter == "github_repo":
            query = f"repo:{query}"
        query = f"{query} stars:>{int(source_config.get('min_stars') or 0)}"
        if source_config.get("language"):
            query += f" language:{source_config['language']}"
        if source_config.get("updated_within_days"):
            from datetime import datetime, timedelta, timezone

            cutoff = datetime.now(timezone.utc) - timedelta(
                days=int(source_config["updated_within_days"])
            )
            query += f" pushed:>{cutoff.date().isoformat()}"
        items = await search_github(
            query,
            sort=str(source_config.get("sort") or "stars"),
            limit=int(source_config.get("limit") or 10),
            token=token,
        )
        source_type = "github"
    elif adapter == "github_trending":
        from .feeds import fetch_github

        items = await fetch_github(
            days=int(source_config.get("days") or 7),
            limit=int(source_config.get("limit") or 10),
            token=token,
        )
        source_type = "github"
    elif adapter == "arxiv":
        items = await fetch_arxiv(
            str(source_config.get("query") or "large language model"),
            limit=int(source_config.get("limit") or 10),
        )
    elif adapter == "devto":
        items = await fetch_devto(
            str(source_config.get("tag") or ""),
            limit=int(source_config.get("limit") or 10),
        )
    elif adapter == "csdn":
        user = str(source_config.get("user") or _csdn_user(source.get("url") or ""))
        feed_url = str(source_config.get("rss_url") or CSDN_RSS.format(user=user))
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
            trust_env=False,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
                "Referer": "https://blog.csdn.net/",
            },
        )
        try:
            try:
                items = await fetch_rss(feed_url, client=client)
            except Exception:
                items = await _fetch_html_items(source)
        finally:
            await client.aclose()
        source_type = "csdn"
    elif adapter == "qt":
        feed_url = str(source_config.get("rss_url") or QT_RSS)
        try:
            items = await fetch_rss(feed_url)
        except Exception:
            items = await _fetch_html_items(
                {**source, "config": {**source_config, "list_url": "https://www.qt.io/blog"}}
            )
        source_type = "qt"
    elif adapter == "author":
        page_url = str(source_config.get("page_url") or source.get("url") or "")
        draft = await discover_source(page_url)
        if draft.get("adapter") == "rss":
            items = await fetch_rss(str(draft["config"].get("feed_url") or page_url))
        else:
            items = await _fetch_html_items(
                {**source, "config": draft.get("config") or source_config}
            )
        source_type = "author"
    else:
        feed_url = str(source_config.get("feed_url") or source.get("url") or "")
        items = await fetch_rss(feed_url)
        source_type = "rss"
    if adapter not in {"github_search", "github_repo", "github_trending", "arxiv", "devto"}:
        await _extract_article_content(items)
    result = _store_items(source, items, config, source_type)
    result["adapter"] = adapter
    touch_source(source["id"], "ok")
    return result
