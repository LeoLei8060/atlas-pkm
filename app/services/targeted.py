from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from .arxiv import fetch_arxiv
from .devto import fetch_devto
from .feeds import (
    FILTER_ALIASES,
    _upsert_feed_item,
    filter_feed_items,
    filter_recent_items,
    search_github,
)

MAX_TERMS = 6
PER_SOURCE_LIMIT = 5

_DEVTO_TAGS = {
    "c++": "cpp",
    "c#": "csharp",
    "系统设计": "system-design",
    "分布式系统": "distributed-systems",
    "分布式": "distributed-systems",
    "网络编程": "networking",
    "数据库": "database",
    "编译器": "compiler",
    "ai 工程化": "ai",
    "机器学习": "machine-learning",
}


def _target_terms(config: dict[str, Any]) -> list[str]:
    groups = [
        config.get("feed_filter_skills") or [],
        config.get("feed_filter_interests") or [],
        config.get("feed_filter_goals") or [],
    ]
    terms: list[str] = []
    # Round-robin across the three profile groups so learning goals are
    # represented even when many skills/interests are selected.
    for index in range(2):
        for values in groups:
            if index < len(values):
                term = str(values[index]).strip()
                if term and term not in terms:
                    terms.append(term)
                if len(terms) >= MAX_TERMS:
                    return terms
    return terms


def _query_for(term: str) -> str:
    if term.isascii():
        return term
    aliases = FILTER_ALIASES.get(term.lower())
    return aliases[0] if aliases else term


def _devto_tag(term: str) -> str:
    lowered = term.strip().lower()
    if lowered in _DEVTO_TAGS:
        return _DEVTO_TAGS[lowered]
    tag = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return tag


def _prepare(items: list[dict[str, Any]], term: str, source_type: str) -> None:
    for item in items:
        item["source_type"] = source_type
        item["source_id"] = ""
        item["source_name"] = f"画像定向: {term}"


async def ingest_targeted(
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = config or {}
    terms = _target_terms(config)
    if not terms:
        return {
            "terms": [],
            "fetched": 0,
            "new": 0,
            "filtered_out": 0,
            "ids": [],
            "errors": [],
            "success": 0,
        }
    token = str(config.get("github_token") or "")
    selected_sources = config.get("feed_filter_sources") or []
    fetched = 0
    filtered_out = 0
    success = 0
    new_ids: list[str] = []
    errors: list[dict[str, str]] = []

    for term in terms:
        query = _query_for(term)
        jobs: list[tuple[str, Any]] = []
        if not selected_sources or "github" in selected_sources:
            jobs.append(
                (
                    "github",
                    search_github(
                        f'"{query}" stars:>10',
                        sort="stars",
                        limit=PER_SOURCE_LIMIT,
                        token=token,
                    ),
                )
            )
        if not selected_sources or "arxiv" in selected_sources:
            jobs.append(("arxiv", fetch_arxiv(f'"{query}"', limit=PER_SOURCE_LIMIT)))
        tag = _devto_tag(term)
        if tag and (not selected_sources or "devto" in selected_sources):
            jobs.append(("devto", fetch_devto(tag, limit=PER_SOURCE_LIMIT)))

        for source_type, coroutine in jobs:
            try:
                items = await coroutine
                success += 1
            except Exception as exc:
                errors.append(
                    {"term": term, "source": source_type, "error": str(exc)[:240]}
                )
                continue
            fetched += len(items)
            items, time_dropped = filter_recent_items(items, config)
            filtered_out += time_dropped
            _prepare(items, term, source_type)
            items, dropped = filter_feed_items(items, config)
            filtered_out += dropped
            for item in items:
                feed_id, created = _upsert_feed_item(item)
                if created:
                    new_ids.append(feed_id)
                elif item.get("_changed"):
                    new_ids.append(feed_id)

    return {
        "terms": terms,
        "fetched": fetched,
        "new": len(new_ids),
        "filtered_out": filtered_out,
        "ids": new_ids,
        "errors": errors,
        "success": success,
    }
