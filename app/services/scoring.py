from __future__ import annotations

import asyncio
from typing import Any

from ..config import load_config
from ..db import db
from .agent import score_feed_item

_running = False
_task: asyncio.Task | None = None
_state: dict[str, Any] = {
    "running": False,
    "total": 0,
    "done": 0,
    "failed": 0,
    "started_at": "",
    "last_error": "",
}


def _has_profile(config: dict[str, Any]) -> bool:
    profile = config.get("profile") or {}
    return bool(
        profile.get("target_role")
        or profile.get("skills")
        or profile.get("learning_goals")
        or profile.get("interests")
    )


def pending_ids() -> list[str]:
    with db() as conn:
        rows = conn.execute(
            "SELECT id FROM feed_items WHERE relevance_reason='' ORDER BY retrieved_at DESC"
        ).fetchall()
    return [row["id"] for row in rows]


def status() -> dict[str, Any]:
    return {**_state, "pending": len(pending_ids())}


async def run_missing(config: dict[str, Any] | None = None) -> dict[str, Any]:
    global _running
    config = config or load_config()
    if _running:
        return status()
    if not _has_profile(config):
        return {**status(), "skipped": True, "reason": "profile empty"}
    ids = pending_ids()
    if not ids:
        return status()

    from ..db import now_iso

    _running = True
    _state.update(
        {
            "running": True,
            "total": len(ids),
            "done": 0,
            "failed": 0,
            "started_at": now_iso(),
            "last_error": "",
        }
    )
    try:
        for feed_id in ids:
            try:
                await score_feed_item(feed_id, config)
                _state["done"] += 1
            except Exception as exc:
                _state["failed"] += 1
                _state["last_error"] = str(exc)[:300]
    finally:
        _running = False
        _state["running"] = False
    return status()


async def _background(config: dict[str, Any]) -> None:
    try:
        await run_missing(config)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _state["last_error"] = str(exc)[:300]
        _state["running"] = False


def start_background(config: dict[str, Any] | None = None) -> None:
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_background(config or load_config()), name="pkm-scoring")
