from __future__ import annotations

from typing import Any

from ..vault import create_source_note
from .feeds import get_feed, update_feed
from .search import reindex_note


def save_feed_as_source(feed_id: str) -> dict[str, Any] | None:
    item = get_feed(feed_id)
    if item is None:
        return None
    rel = create_source_note(item)
    updated = update_feed(feed_id, status="saved")
    reindex_note(rel)
    return {"path": rel, "item": updated}
