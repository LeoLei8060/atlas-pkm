from __future__ import annotations

import asyncio

from app.db import db, now_iso
from app.services import scheduler
from app.services.feeds import _upsert_feed_item, ensure_source, list_feed


def test_replace_run_removes_old_feed_items(isolated, monkeypatch):
    ensure_source("rss", "Replace Test", "https://example.com/feed")
    _upsert_feed_item(
        {
            "url": "https://example.com/old",
            "canonical_url": "https://example.com/old",
            "title": "Old item",
            "summary": "old",
            "content": "old",
            "source_type": "rss",
        }
    )
    with db() as conn:
        conn.execute("UPDATE feed_items SET retrieved_at='2000-01-01T00:00:00+00:00'")

    async def empty_ingest(*args, **kwargs):
        return {"fetched": 0, "new": 0, "ids": [], "filtered_out": 0}

    async def no_enrich(items, config):
        return []

    monkeypatch.setattr(scheduler, "fetch_configured_source", empty_ingest)
    monkeypatch.setattr(scheduler, "enrich_items", no_enrich)
    config = {
        "active_provider": "deepseek",
        "providers": {"deepseek": {"api_key": "test", "model": "test"}},
        "auto_refresh_github": False,
        "profile": {},
    }
    result = asyncio.run(scheduler.run_once(config, force=True, replace=True))
    assert result["removed"] == 1
    assert list_feed() == []
