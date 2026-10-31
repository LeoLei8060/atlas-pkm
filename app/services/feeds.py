from __future__ import annotations

import asyncio
import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from ..config import load_config
from ..db import db, now_iso, upsert_document
from .extract import fetch_article_text
from .text import canonicalize_url, parse_iso, strip_html


class FeedError(Exception):
    pass


def source_id_for(kind: str, url: str) -> str:
    return "src_" + hashlib.sha1(f"{kind}:{url}".encode("utf-8")).hexdigest()[:12]


def source_host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def source_label(name: str, url: str) -> str:
    label = (name or "").strip()
    if not label or label in {"RSS", "Auto RSS"}:
        return source_host(url) or url
    return label


DEFAULT_ADAPTERS = {
    "rss": ("other", "rss"),
    "github": ("github", "github_trending"),
    "arxiv": ("other", "arxiv"),
    "devto": ("other", "devto"),
}


def ensure_source(
    kind: str,
    name: str,
    url: str,
    enabled: int = 1,
    *,
    source_group: str | None = None,
    adapter: str | None = None,
    config: dict[str, Any] | None = None,
) -> str:
    source_id = source_id_for(kind, url)
    group, default_adapter = DEFAULT_ADAPTERS.get(kind, ("other", "rss"))
    group = source_group or group
    adapter = adapter or default_adapter
    payload = json.dumps(config or {}, ensure_ascii=False)
    with db() as conn:
        conn.execute(
            """
            INSERT INTO sources(
                id, kind, name, url, enabled, created_at,
                source_group, adapter, config_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, url=excluded.url
            """,
            (
                source_id,
                kind,
                source_label(name, url),
                url,
                enabled,
                now_iso(),
                group,
                adapter,
                payload,
            ),
        )
    return source_id


def touch_source(source_id: str, status: str, error: str = "") -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE sources
            SET last_fetch_at=?, last_status=?, last_error=?
            WHERE id=?
            """,
            (now_iso(), status, error[:800], source_id),
        )


def _source_row(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["enabled"] = bool(item.get("enabled"))
    item["item_count"] = int(item.get("item_count") or 0)
    try:
        config = json.loads(item.get("config_json") or "{}")
    except (TypeError, ValueError):
        config = {}
    item["config"] = config if isinstance(config, dict) else {}
    item["source_group"] = item.get("source_group") or "other"
    item["adapter"] = item.get("adapter") or DEFAULT_ADAPTERS.get(
        item.get("kind", ""), ("other", "rss")
    )[1]
    return item


def list_sources(
    kind: str | None = None,
    enabled_only: bool = False,
    source_group: str | None = None,
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if kind:
        clauses.append("s.kind=?")
        params.append(kind)
    if source_group:
        clauses.append("s.source_group=?")
        params.append(source_group)
    if enabled_only:
        clauses.append("s.enabled=1")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with db() as conn:
        rows = conn.execute(
            f"""
            SELECT s.*,
                   (SELECT COUNT(*) FROM feed_items f WHERE f.source_id=s.id) AS item_count
            FROM sources s
            {where}
            ORDER BY s.created_at DESC
            """,
            params,
        ).fetchall()
    return [_source_row(row) for row in rows]


def get_source(source_id: str) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT s.*,
                   (SELECT COUNT(*) FROM feed_items f WHERE f.source_id=s.id) AS item_count
            FROM sources s WHERE s.id=?
            """,
            (source_id,),
        ).fetchone()
    return _source_row(row) if row else None


def add_rss_source(url: str, name: str = "") -> dict[str, Any]:
    return add_source(
        url=url,
        name=name,
        source_group="other",
        adapter="rss",
    )


def add_source(
    *,
    url: str,
    name: str = "",
    source_group: str = "other",
    adapter: str = "rss",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise FeedError("来源地址必须是 http(s)")
    if source_group not in {"github", "other"}:
        raise FeedError("来源分组必须是 github 或 other")
    if adapter not in {
        "rss",
        "github_trending",
        "github_search",
        "github_repo",
        "csdn",
        "qt",
        "arxiv",
        "devto",
        "author",
        "html",
    }:
        raise FeedError("不支持的来源类型")
    kind = {
        "github_trending": "github",
        "github_search": "github",
        "github_repo": "github",
        "arxiv": "arxiv",
        "devto": "devto",
    }.get(adapter, "rss")
    source_id = ensure_source(
        kind,
        name or url,
        url,
        source_group=source_group,
        adapter=adapter,
        config=config or {},
    )
    with db() as conn:
        conn.execute(
            "UPDATE sources SET source_group=?, adapter=?, config_json=? WHERE id=?",
            (
                source_group,
                adapter,
                json.dumps(config or {}, ensure_ascii=False),
                source_id,
            ),
        )
    return get_source(source_id) or {}


def update_source_config(
    source_id: str,
    *,
    name: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    with db() as conn:
        if name is not None:
            conn.execute(
                "UPDATE sources SET name=? WHERE id=?",
                (name.strip() or "来源", source_id),
            )
        if config is not None:
            conn.execute(
                "UPDATE sources SET config_json=? WHERE id=?",
                (json.dumps(config, ensure_ascii=False), source_id),
            )
    return get_source(source_id)


def set_source_enabled(source_id: str, enabled: bool) -> dict[str, Any] | None:
    with db() as conn:
        conn.execute(
            "UPDATE sources SET enabled=? WHERE id=?",
            (1 if enabled else 0, source_id),
        )
    return get_source(source_id)


def delete_source(source_id: str) -> bool:
    with db() as conn:
        cursor = conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
    return cursor.rowcount > 0


def sync_config_sources(config: dict[str, Any]) -> None:
    for url in (config.get("rss_sources") or [])[:20]:
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            ensure_source("rss", "Auto RSS", url)


def dedupe_sources() -> int:
    """Merge legacy source rows that shared a URL but used an older ID scheme."""
    removed = 0
    with db() as conn:
        rows = conn.execute("SELECT * FROM sources ORDER BY created_at").fetchall()
        groups: dict[tuple[str, str], list[Any]] = {}
        for row in rows:
            groups.setdefault((row["kind"], row["url"]), []).append(row)
        for group in groups.values():
            if len(group) == 1 and group[0]["name"] in {"RSS", "Auto RSS"}:
                conn.execute(
                    "UPDATE sources SET name=? WHERE id=?",
                    (source_label(group[0]["name"], group[0]["url"]), group[0]["id"]),
                )
                continue
            if len(group) < 2:
                continue
            keep = sorted(
                group,
                key=lambda row: (
                    row["last_status"] == "ok",
                    bool(row["last_fetch_at"]),
                    row["created_at"],
                ),
                reverse=True,
            )[0]
            if keep["name"] in {"RSS", "Auto RSS"}:
                conn.execute(
                    "UPDATE sources SET name=? WHERE id=?",
                    (source_label(keep["name"], keep["url"]), keep["id"]),
                )
            for row in group:
                if row["id"] == keep["id"]:
                    continue
                conn.execute(
                    "UPDATE feed_items SET source_id=? WHERE source_id=?",
                    (keep["id"], row["id"]),
                )
                conn.execute("DELETE FROM sources WHERE id=?", (row["id"],))
                removed += 1
    return removed


def backfill_source_ids() -> int:
    updated = 0
    with db() as conn:
        sources = conn.execute("SELECT id, kind, name, url FROM sources").fetchall()
        items = conn.execute(
            "SELECT id, source_type, url, source_id FROM feed_items"
        ).fetchall()
        for item in items:
            host = source_host(item["url"])
            matches = [
                source for source in sources
                if source["kind"] == item["source_type"]
                and host
                and source_host(source["url"]) == host
            ]
            if not matches:
                continue
            target = matches[0]["id"]
            if item["source_id"] != target:
                cursor = conn.execute(
                    "UPDATE feed_items SET source_id=? WHERE id=?",
                    (target, item["id"]),
                )
                updated += cursor.rowcount
        for source in sources:
            cursor = conn.execute(
                """
                UPDATE feed_items
                SET source_id=?
                WHERE source_id='' AND source_type=?
                  AND (source_name=? OR source_name=?)
                """,
                (source["id"], source["kind"], source["url"], source["name"]),
            )
            updated += cursor.rowcount
    return updated


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element: ET.Element, names: set[str]) -> str:
    for child in element:
        if _local(child.tag) in names and (child.text or "").strip():
            return (child.text or "").strip()
    return ""


def _atom_link(element: ET.Element) -> str:
    links = [child for child in element if _local(child.tag) == "link"]
    for link in links:
        if link.get("rel") in (None, "", "alternate") and link.get("href"):
            return link.get("href", "")
    for link in links:
        if link.get("href"):
            return link.get("href", "")
    return ""


def parse_feed(xml_text: str) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FeedError(f"RSS 解析失败: {exc}") from exc

    entries = [node for node in root.iter() if _local(node.tag) in {"item", "entry"}]
    items: list[dict[str, Any]] = []
    for entry in entries:
        title = strip_html(_child_text(entry, {"title"}), 300)
        link = _atom_link(entry) or _child_text(entry, {"link", "guid", "id"})
        if not link and title:
            link = _child_text(entry, {"guid", "id"})
        if not title or not link:
            continue
        link = link.strip()
        if not link.startswith(("http://", "https://")):
            continue

        raw_summary = _child_text(entry, {"description", "summary", "content"})
        raw_content = _child_text(entry, {"encoded", "content"}) or raw_summary
        summary = strip_html(raw_summary, 1200)
        content = strip_html(raw_content, 12000)
        published = _child_text(entry, {"pubdate", "published", "updated", "date"})
        if published and not published[:4].isdigit():
            try:
                published = parsedate_to_datetime(published).astimezone(timezone.utc).isoformat()
            except Exception:
                pass
        else:
            published = parse_iso(published)

        author = _child_text(entry, {"author", "creator"})
        if not author:
            author_el = next(
                (child for child in entry if _local(child.tag) == "author"), None
            )
            if author_el is not None:
                author = _child_text(author_el, {"name"})
        tags = [
            (child.text or "").strip()
            for child in entry
            if _local(child.tag) == "category" and (child.text or "").strip()
        ]
        items.append(
            {
                "title": title,
                "url": link,
                "canonical_url": canonicalize_url(link),
                "summary": summary,
                "content": content,
                "author": author,
                "published_at": published,
                "tags": tags,
                "source_type": "rss",
            }
        )
    return items


async def fetch_rss(
    url: str, client: httpx.AsyncClient | None = None
) -> list[dict[str, Any]]:
    owns_client = client is None
    client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(45.0, connect=15.0),
        follow_redirects=True,
        trust_env=False,
        headers={"User-Agent": "AI-PKM-Agent/0.1"},
    )
    try:
        response = await client.get(url)
    except httpx.HTTPError as exc:
        raise FeedError(f"RSS 请求失败: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()
    if response.status_code >= 400:
        raise FeedError(f"RSS 请求返回 {response.status_code}")
    return parse_feed(response.text)


def _upsert_feed_item(item: dict[str, Any]) -> tuple[str, bool]:
    canonical = item.get("canonical_url") or canonicalize_url(item.get("url", ""))
    if not canonical:
        raise FeedError("条目缺少 URL")
    item_id = "feed_" + hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]
    tags = json.dumps(item.get("tags") or [], ensure_ascii=False)
    with db() as conn:
        existing = conn.execute(
            """
            SELECT id, status, title, summary, content, published_at
            FROM feed_items WHERE canonical_url = ?
            """,
            (canonical,),
        ).fetchone()
        if existing:
            feed_id = str(existing["id"])
            created = False
            if existing["status"] == "dismissed":
                item["_ignored"] = True
            else:
                changed = any(
                    str(existing[field] or "") != str(item.get(field) or "")
                    for field in ("title", "summary", "content", "published_at")
                )
                item["_changed"] = changed
                conn.execute(
                    """
                    UPDATE feed_items SET
                        source_id=?, source_type=?, source_name=?,
                        title=?, author=?, summary=?, content=?, published_at=?,
                        retrieved_at=?, tags=?, repo_full_name=?, stars=?, forks=?,
                        license=?, primary_language=?
                    WHERE canonical_url=?
                    """,
                    (
                        item.get("source_id", ""),
                        item.get("source_type", "rss"),
                        item.get("source_name", ""),
                        item.get("title", ""),
                        item.get("author", ""),
                        item.get("summary", ""),
                        item.get("content", ""),
                        item.get("published_at", ""),
                        now_iso(),
                        tags,
                        item.get("repo_full_name", ""),
                        int(item.get("stars") or 0),
                        int(item.get("forks") or 0),
                        item.get("license", ""),
                        item.get("primary_language", ""),
                        canonical,
                    ),
                )
                if changed:
                    conn.execute(
                        """
                        UPDATE feed_items SET
                            summary_zh='', translation_zh='', translated=0,
                            relevance_score=0, relevance_reason='', knowledge_gaps='[]'
                        WHERE id=?
                        """,
                        (feed_id,),
                    )
        else:
            conn.execute(
                """
                INSERT INTO feed_items(
                    id, source_id, source_type, source_name, url, canonical_url,
                    title, author, summary, content, language, published_at,
                    retrieved_at, tags, raw_json, status, repo_full_name, stars,
                    forks, license, primary_language, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unread', ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    item.get("source_id", ""),
                    item.get("source_type", "rss"),
                    item.get("source_name", ""),
                    item.get("url", ""),
                    canonical,
                    item.get("title", ""),
                    item.get("author", ""),
                    item.get("summary", ""),
                    item.get("content", ""),
                    item.get("language", ""),
                    item.get("published_at", ""),
                    now_iso(),
                    tags,
                    "{}",
                    item.get("repo_full_name", ""),
                    int(item.get("stars") or 0),
                    int(item.get("forks") or 0),
                    item.get("license", ""),
                    item.get("primary_language", ""),
                    now_iso(),
                ),
            )
            feed_id = item_id
            created = True

        row = conn.execute("SELECT * FROM feed_items WHERE id = ?", (feed_id,)).fetchone()
        if row:
            upsert_document(
                conn,
                doc_id=f"feed:{feed_id}",
                kind="feed",
                title=row["title"],
                content=row["summary_zh"] or row["summary"] or row["content"],
                source_url=row["url"],
                metadata={
                    "source_type": row["source_type"],
                    "tags": json.loads(row["tags"] or "[]"),
                    "feed_id": feed_id,
                },
            )
    return feed_id, created


FILTER_ALIASES: dict[str, tuple[str, ...]] = {
    "c++": ("cpp", "c plus plus"),
    "数据库": ("database", "db", "sql", "postgres", "mysql", "sqlite", "storage"),
    "编译器": ("compiler", "llvm", "clang", "gcc", "codegen"),
    "分布式": ("distributed", "cluster", "consensus", "raft", "paxos"),
    "分布式系统": ("distributed system", "distributed systems", "distributed"),
    "系统设计": ("system design", "architecture", "design"),
    "ai 工程化": ("ai engineering", "llmops", "mlops", "ai agent", "rag"),
    "编程基础": ("programming", "coding"),
    "计算机系统": ("computer systems", "operating system", "runtime"),
    "可靠性工程": ("reliability", "resilience", "fault tolerance", "sre"),
    "网络编程": ("network programming", "networking", "socket", "tcp", "udp"),
    "性能优化": ("performance", "optimization", "latency", "throughput"),
    "并发": ("concurrency", "concurrent", "parallel"),
    "云原生": ("cloud native", "kubernetes", "container"),
    "机器学习": ("machine learning", "ml", "pytorch", "tensorflow"),
}


SOURCE_TYPE_LABELS = {
    "github": "GitHub",
    "rss": "RSS",
    "arxiv": "arXiv",
    "devto": "Dev.to",
    "csdn": "CSDN",
    "qt": "Qt Blog",
    "author": "博主",
    "html": "网页",
}


def source_type_for(source: dict[str, Any]) -> str:
    adapter = str(source.get("adapter") or "rss")
    if adapter.startswith("github_"):
        return "github"
    return adapter


def filter_recent_items(
    items: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Keep article items published within the configured window.

    GitHub items are repository records rather than articles; they use their
    own query window and are not removed here. Items without a parseable date
    are kept rather than silently dropped.
    """
    config = config or {}
    days = int(config.get("feed_window_days") or 3)
    if days <= 0:
        return items, 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    kept: list[dict[str, Any]] = []
    dropped = 0
    for item in items:
        if str(item.get("source_type") or "") == "github":
            kept.append(item)
            continue
        raw = str(item.get("published_at") or "").strip()
        if not raw:
            kept.append(item)
            continue
        parsed: datetime | None = None
        try:
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                parsed = parsedate_to_datetime(raw)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                parsed = None
        if parsed is not None and parsed.astimezone(timezone.utc) < cutoff:
            dropped += 1
            continue
        kept.append(item)
    return kept, dropped


def source_matches_filter(
    source: dict[str, Any], selected: list[str] | None
) -> bool:
    if not selected:
        return True
    return source_type_for(source) in selected


def selected_feed_filters(config: dict[str, Any] | None = None) -> list[str]:
    config = load_config() if config is None else config
    terms: list[str] = []
    for key in ("feed_filter_skills", "feed_filter_interests", "feed_filter_goals"):
        for value in config.get(key) or []:
            text = str(value).strip()
            if text and text not in terms:
                terms.append(text)
    return terms


def filter_feed_items(
    items: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    terms = selected_feed_filters(config)
    if not terms:
        return items, 0
    kept: list[dict[str, Any]] = []
    for item in items:
        haystack = " ".join(
            [
                str(item.get("title") or ""),
                str(item.get("summary") or ""),
                str(item.get("content") or ""),
                " ".join(str(tag) for tag in item.get("tags") or []),
                str(item.get("source_name") or ""),
                str(item.get("primary_language") or ""),
                str(item.get("repo_full_name") or ""),
            ]
        ).lower()
        variants = [
            variant
            for term in terms
            for variant in (term, *FILTER_ALIASES.get(term.lower(), ()))
        ]
        if any(variant.lower() in haystack for variant in variants):
            kept.append(item)
    return kept, len(items) - len(kept)


async def ingest_rss(
    url: str,
    *,
    name: str = "",
    client: httpx.AsyncClient | None = None,
    max_articles: int | None = None,
) -> dict[str, Any]:
    source_id = ensure_source("rss", name or url, url)
    owns_client = client is None
    client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(45.0, connect=15.0),
        follow_redirects=True,
        trust_env=False,
        headers={"User-Agent": "Mozilla/5.0 (compatible; AI-PKM-Agent/0.1)"},
    )
    extracted = 0
    try:
        items = await fetch_rss(url, client=client)
        targets = items if max_articles is None else items[:max_articles]
        semaphore = asyncio.Semaphore(6)

        async def extract_one(item: dict[str, Any]) -> bool:
            raw = item.get("content") or item.get("summary") or ""
            needs_extraction = (
                len(raw.strip()) < 600
                or "Article URL:" in raw
                or "Comments URL:" in raw
            )
            if not needs_extraction:
                return False
            async with semaphore:
                try:
                    article = await asyncio.wait_for(
                        fetch_article_text(item["url"], client=client),
                        timeout=25,
                    )
                except Exception:
                    return False
            if article and len(article) > len(raw.strip()):
                item["content"] = article
                item["summary"] = article[:1200]
                return True
            return False

        if targets:
            extracted = sum(await asyncio.gather(*(extract_one(item) for item in targets)))

        fetched_count = len(items)
        items, filtered_out = filter_feed_items(items)
        new_ids: list[str] = []
        for item in items:
            item["source_type"] = "rss"
            item["source_id"] = source_id
            item["source_name"] = name or url
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
            "extracted": extracted,
        }
    except Exception as exc:
        touch_source(source_id, "error", str(exc))
        raise
    finally:
        if owns_client:
            await client.aclose()


def _github_item(repo: dict[str, Any]) -> dict[str, Any]:
    url = str(repo.get("html_url") or "")
    description = strip_html(str(repo.get("description") or ""), 800)
    topics = repo.get("topics") or []
    license_info = repo.get("license") or {}
    return {
        "title": f"{repo.get('full_name', '')}",
        "url": url,
        "canonical_url": canonicalize_url(url),
        "summary": description,
        "content": "\n".join(
            [description, "Topics: " + ", ".join(topics) if topics else ""]
        ).strip(),
        "author": str((repo.get("owner") or {}).get("login") or ""),
        "published_at": str(repo.get("created_at") or ""),
        "tags": topics,
        "source_type": "github",
        "source_name": "GitHub Trend",
        "repo_full_name": str(repo.get("full_name") or ""),
        "stars": int(repo.get("stargazers_count") or 0),
        "forks": int(repo.get("forks_count") or 0),
        "license": str(license_info.get("spdx_id") or ""),
        "primary_language": str(repo.get("language") or ""),
        "pushed_at": str(repo.get("pushed_at") or ""),
        "open_issues": int(repo.get("open_issues_count") or 0),
        "topics": topics,
    }


async def search_github(
    query: str,
    *,
    sort: str = "stars",
    limit: int = 10,
    token: str = "",
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AI-PKM-Agent/0.1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    owns_client = client is None
    client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(45.0, connect=15.0),
        follow_redirects=True,
        trust_env=False,
    )
    try:
        response = await client.get(
            "https://api.github.com/search/repositories",
            params={
                "q": query,
                "sort": sort,
                "order": "desc",
                "per_page": max(1, min(limit, 100)),
            },
            headers=headers,
        )
    except httpx.HTTPError as exc:
        raise FeedError(f"GitHub 请求失败: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()
    if response.status_code >= 400:
        raise FeedError(f"GitHub 请求返回 {response.status_code}: {response.text[:200]}")
    payload = response.json()
    items = []
    for repo in payload.get("items") or []:
        if repo.get("html_url"):
            items.append(_github_item(repo))
    return items


async def fetch_github(
    *,
    days: int = 7,
    limit: int = 10,
    token: str = "",
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).strftime("%Y-%m-%d")
    query = f"created:>{since} stars:>50"
    return await search_github(
        query, sort="stars", limit=limit, token=token, client=client
    )


async def ingest_github(
    *,
    days: int = 7,
    limit: int = 10,
    token: str = "",
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    source_id = ensure_source(
        "github", "GitHub Trending", "https://github.com/trending"
    )
    try:
        items = await fetch_github(days=days, limit=limit, token=token, client=client)
        fetched_count = len(items)
        items, filtered_out = filter_feed_items(items)
        new_ids: list[str] = []
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


def _feed_clause(
    status: str | None,
    *,
    q: str = "",
    source_type: str = "",
    source_id: str = "",
    tag: str = "",
) -> tuple[str, list[Any]]:
    where: list[str] = []
    params: list[Any] = []
    if status:
        where.append("status = ?")
        params.append(status)
    else:
        where.append("status != 'dismissed'")
    if source_type:
        where.append("source_type = ?")
        params.append(source_type)
    if source_id:
        where.append("source_id = ?")
        params.append(source_id)
    if tag:
        where.append("tags LIKE ?")
        params.append(f'%"{tag}"%')
    if q.strip():
        like = f"%{q.strip()}%"
        where.append("(title LIKE ? OR summary LIKE ? OR summary_zh LIKE ? OR content LIKE ?)")
        params.extend([like, like, like, like])
    return (f"WHERE {' AND '.join(where)}" if where else ""), params


def count_feed(
    status: str | None = None,
    *,
    q: str = "",
    source_type: str = "",
    source_id: str = "",
    tag: str = "",
) -> int:
    clause, params = _feed_clause(
        status, q=q, source_type=source_type, source_id=source_id, tag=tag
    )
    with db() as conn:
        return int(
            conn.execute(
                f"SELECT COUNT(*) FROM feed_items {clause}", params
            ).fetchone()[0]
        )


def list_feed(
    status: str | None = None,
    limit: int = 100,
    sort: str = "recent",
    *,
    q: str = "",
    source_type: str = "",
    source_id: str = "",
    tag: str = "",
    offset: int = 0,
) -> list[dict[str, Any]]:
    order = (
        "(relevance_score + CASE feedback WHEN 1 THEN 0.15 WHEN -1 THEN -0.25 ELSE 0 END) DESC, retrieved_at DESC"
        if sort == "relevance"
        else "retrieved_at DESC"
    )
    clause, params = _feed_clause(
        status, q=q, source_type=source_type, source_id=source_id, tag=tag
    )
    with db() as conn:
        rows = conn.execute(
            f"SELECT * FROM feed_items {clause} ORDER BY {order} LIMIT ? OFFSET ?",
            (*params, limit, max(0, offset)),
        ).fetchall()
    return [_feed_row(row) for row in rows]


def delete_feed(feed_id: str) -> bool:
    with db() as conn:
        cursor = conn.execute("DELETE FROM feed_items WHERE id=?", (feed_id,))
        conn.execute("DELETE FROM documents WHERE doc_id=?", (f"feed:{feed_id}",))
        return cursor.rowcount > 0


def favorite_github_item(repo: dict[str, Any]) -> dict[str, Any]:
    url = str(repo.get("url") or "").strip()
    if not url:
        raise FeedError("GitHub 条目缺少 URL")
    source_id = ""
    sources = list_sources(source_group="github")
    if sources:
        source_id = sources[0]["id"]
    item = {
        "title": str(repo.get("repo_full_name") or repo.get("title") or url),
        "url": url,
        "canonical_url": canonicalize_url(url),
        "summary": str(repo.get("summary") or ""),
        "content": str(repo.get("summary") or ""),
        "author": "",
        "published_at": str(repo.get("published_at") or ""),
        "tags": repo.get("topics") or [],
        "source_type": "github",
        "source_name": "GitHub 榜单",
        "source_id": source_id,
        "repo_full_name": str(repo.get("repo_full_name") or ""),
        "stars": int(repo.get("stars") or 0),
        "forks": int(repo.get("forks") or 0),
        "license": str(repo.get("license") or ""),
        "primary_language": str(repo.get("primary_language") or ""),
    }
    feed_id, _ = _upsert_feed_item(item)
    updated = update_feed(
        feed_id,
        status="saved",
        summary_zh=str(repo.get("summary_zh") or ""),
        translation_zh=str(repo.get("translation_zh") or ""),
        relevance_score=float(repo.get("relevance_score") or 0),
        relevance_reason=str(repo.get("relevance_reason") or ""),
    )
    return updated or get_feed(feed_id) or {}


def get_feed(feed_id: str) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM feed_items WHERE id = ?", (feed_id,)).fetchone()
    return _feed_row(row) if row else None


def _feed_row(row: Any) -> dict[str, Any]:
    item = dict(row)
    try:
        item["tags"] = json.loads(item.get("tags") or "[]")
    except json.JSONDecodeError:
        item["tags"] = []
    try:
        item["knowledge_gaps"] = json.loads(item.get("knowledge_gaps") or "[]")
    except json.JSONDecodeError:
        item["knowledge_gaps"] = []
    item["feedback"] = int(item.get("feedback") or 0)
    item["effective_score"] = max(
        0.0,
        min(1.0, float(item.get("relevance_score") or 0) + item["feedback"] * 0.15),
    )
    item["favorite"] = item.get("status") == "saved"
    return item


def update_feed(feed_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {
        "title",
        "summary",
        "content",
        "summary_zh",
        "translation_zh",
        "translated",
        "relevance_score",
        "relevance_reason",
        "knowledge_gaps",
        "feedback",
        "status",
        "tags",
        "language",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return get_feed(feed_id)
    if "tags" in updates and not isinstance(updates["tags"], str):
        updates["tags"] = json.dumps(updates["tags"], ensure_ascii=False)
    if "knowledge_gaps" in updates and not isinstance(updates["knowledge_gaps"], str):
        updates["knowledge_gaps"] = json.dumps(
            updates["knowledge_gaps"], ensure_ascii=False
        )
    assignments = ", ".join(f"{key}=?" for key in updates)
    with db() as conn:
        conn.execute(
            f"UPDATE feed_items SET {assignments} WHERE id=?",
            (*updates.values(), feed_id),
        )
        row = conn.execute("SELECT * FROM feed_items WHERE id = ?", (feed_id,)).fetchone()
        if row:
            upsert_document(
                conn,
                doc_id=f"feed:{feed_id}",
                kind="feed",
                title=row["title"],
                content=row["summary_zh"] or row["summary"] or row["content"],
                source_url=row["url"],
                metadata={
                    "source_type": row["source_type"],
                    "tags": json.loads(row["tags"] or "[]"),
                    "feed_id": feed_id,
                },
            )
    return _feed_row(row) if row else None
