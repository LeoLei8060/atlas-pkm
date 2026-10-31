from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import has_any_key, load_config, save_config
from ..db import now_iso
from .agent import enrich_items
from .feeds import (
    ensure_source,
    list_sources,
    selected_feed_filters,
    source_matches_filter,
    sync_config_sources,
    touch_source,
)
from .source_adapters import fetch_source as fetch_configured_source

logger = logging.getLogger("pkm.scheduler")

_task: asyncio.Task | None = None
_last_run_value = ""
_last_run_ts = 0.0
try:
    _last_run_value = str(load_config().get("scheduler_last_run") or "")
    if _last_run_value:
        _last_run_ts = datetime.fromisoformat(_last_run_value).timestamp()
except Exception:
    _last_run_value = ""
    _last_run_ts = 0.0

_state: dict[str, Any] = {
    "last_run": _last_run_value,
    "last_error": "",
    "last_result": {},
    "running": False,
    "next_run_at": "",
}


def _interval_seconds(config: dict[str, Any]) -> int:
    try:
        minutes = int(config.get("refresh_interval_minutes") or 120)
    except (TypeError, ValueError):
        minutes = 120
    return max(15, minutes) * 60


def _schedule_mode(config: dict[str, Any]) -> str:
    mode = str(config.get("schedule_mode") or "daily")
    return mode if mode in {"daily", "interval"} else "daily"


def _daily_hour_minute(config: dict[str, Any]) -> tuple[int, int]:
    raw = str(config.get("daily_time") or "06:00")
    try:
        hour, minute = raw.split(":", 1)
        return min(23, max(0, int(hour))), min(59, max(0, int(minute)))
    except (ValueError, TypeError):
        return 6, 0


def _daily_target(now: datetime, config: dict[str, Any]) -> datetime:
    hour, minute = _daily_hour_minute(config)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _last_run_datetime() -> datetime | None:
    if not _last_run_ts:
        return None
    return datetime.fromtimestamp(_last_run_ts)


def _schedule_due(config: dict[str, Any], now: datetime | None = None) -> bool:
    if not config.get("auto_refresh_enabled") or not has_any_key(config):
        return False
    now = now or datetime.now()
    last = _last_run_datetime()
    if _schedule_mode(config) == "daily":
        target = _daily_target(now, config)
        if now < target:
            return False
        return last is None or last < target
    interval = _interval_seconds(config)
    if last is None:
        return True
    return (now - last).total_seconds() >= interval


def _next_run_datetime(config: dict[str, Any]) -> datetime | None:
    if not config.get("auto_refresh_enabled") or not has_any_key(config):
        return None
    now = datetime.now()
    last = _last_run_datetime()
    if _schedule_mode(config) == "daily":
        target = _daily_target(now, config)
        if now < target:
            return target
        if last is None or last < target:
            return now
        return target + timedelta(days=1)
    if last is None:
        return now
    return max(now, last + timedelta(seconds=_interval_seconds(config)))


def _is_recent(value: str, interval: int) -> bool:
    if not value:
        return False
    try:
        return time.time() - datetime.fromisoformat(value).timestamp() < interval
    except (ValueError, TypeError):
        return False


def _review_due(config: dict[str, Any]) -> bool:
    try:
        days = max(1, int(config.get("review_interval_days") or 7))
    except (TypeError, ValueError):
        days = 7
    return not _is_recent(str(config.get("last_review_at") or ""), days * 86400)


async def _maybe_review(config: dict[str, Any]) -> dict[str, Any] | None:
    if not config.get("auto_review_enabled") or not _review_due(config):
        return None
    try:
        from datetime import date

        from ..vault import atomic_write, dump_note, target_path
        from .review import weekly_review

        days = max(1, int(config.get("review_interval_days") or 7))
        result = await weekly_review(days, config)
        title = f"周期复盘 {date.today().isoformat()}"
        rel = f"03-Maps/Reviews/{date.today().isoformat()}-review.md"
        atomic_write(
            target_path(rel),
            dump_note(
                {"title": title, "type": "map", "tags": ["复盘", "AI"]},
                result["markdown"],
            ),
        )
        config["last_review_at"] = now_iso()
        save_config(config)
        logger.info("Automatic review saved to %s", rel)
        return {**result, "note_path": rel}
    except Exception as exc:
        logger.warning("Automatic review failed: %s", exc)
        return None


async def run_once(
    config: dict[str, Any] | None = None,
    *,
    force: bool = False,
    replace: bool = False,
) -> dict[str, Any]:
    global _last_run_ts
    if _state["running"]:
        return {"skipped": True, "reason": "scheduler already running"}
    config = config or load_config()
    if not has_any_key(config):
        return {"skipped": True, "reason": "no provider configured"}

    _state["running"] = True
    started_at = now_iso()
    successful_sources = 0
    result: dict[str, Any] = {
        "rss": [],
        "github": None,
        "sources": [],
        "errors": [],
    }
    try:
        sync_config_sources(config)
        if config.get("auto_refresh_github", True):
            ensure_source(
                "github",
                "GitHub Trending",
                "https://github.com/trending",
                source_group="github",
                adapter="github_trending",
            )
        source_interval = (
            20 * 3600
            if _schedule_mode(config) == "daily"
            else _interval_seconds(config)
        )
        github_results: list[dict[str, Any]] = []
        selected_source_types = config.get("feed_filter_sources") or []
        result["source_filter"] = selected_source_types
        for source in list_sources(enabled_only=True):
            name = source.get("name") or source.get("url") or source["id"]
            if not source_matches_filter(source, selected_source_types):
                result["sources"].append(
                    {
                        "source_id": source["id"],
                        "name": name,
                        "group": source.get("source_group") or "other",
                        "skipped": True,
                        "reason": "source_filter",
                        "fetched": 0,
                        "new": 0,
                    }
                )
                continue
            if not force and _is_recent(
                source.get("last_fetch_at") or "", source_interval
            ):
                entry = {
                    "source_id": source["id"],
                    "name": name,
                    "group": source.get("source_group") or "other",
                    "skipped": True,
                    "reason": "recent",
                    "fetched": 0,
                    "new": 0,
                }
                result["sources"].append(entry)
                if entry["group"] == "github":
                    github_results.append(entry)
                else:
                    result["rss"].append(entry)
                continue
            try:
                ing = await fetch_configured_source(source, config)
                enriched = []
                if ing.get("ids"):
                    enriched = await enrich_items(ing["ids"], config)
                successful_sources += 1
                entry = {
                    **ing,
                    "enriched": len(enriched),
                    "source_id": source["id"],
                    "name": name,
                    "group": source.get("source_group") or "other",
                    "adapter": source.get("adapter") or "rss",
                }
                result["sources"].append(entry)
                if entry["group"] == "github":
                    github_results.append(entry)
                else:
                    result["rss"].append(entry)
            except Exception as exc:
                touch_source(source["id"], "error", str(exc))
                logger.warning("Source failed (%s): %s", name, exc)
                result["errors"].append(
                    {
                        "kind": source.get("adapter") or "source",
                        "source_id": source["id"],
                        "name": name,
                        "error": str(exc),
                    }
                )

        if github_results:
            result["github"] = {
                "new": sum(int(item.get("new") or 0) for item in github_results),
                "fetched": sum(int(item.get("fetched") or 0) for item in github_results),
                "filtered_out": sum(
                    int(item.get("filtered_out") or 0) for item in github_results
                ),
                "items": github_results,
            }

        targeted_types = {"github", "arxiv", "devto"}
        targeted_enabled = (
            not selected_source_types
            or bool(targeted_types.intersection(selected_source_types))
        )
        if selected_feed_filters(config) and targeted_enabled:
            try:
                from .targeted import ingest_targeted

                targeted = await ingest_targeted(config)
                if targeted.get("ids"):
                    targeted["enriched"] = len(
                        await enrich_items(targeted["ids"], config)
                    )
                else:
                    targeted["enriched"] = 0
                result["targeted"] = targeted
                successful_sources += int(targeted.get("success") or 0)
            except Exception as exc:
                logger.warning("Targeted fetch failed: %s", exc)
                result["errors"].append({"kind": "targeted", "error": str(exc)})

        removed = 0
        if replace and successful_sources:
            from ..db import db

            with db() as conn:
                old_ids = [
                    row["id"]
                    for row in conn.execute(
                        "SELECT id FROM feed_items WHERE retrieved_at < ? AND status != 'dismissed'",
                        (started_at,),
                    ).fetchall()
                ]
                if old_ids:
                    conn.executemany(
                        "DELETE FROM feed_items WHERE id=?", [(item_id,) for item_id in old_ids]
                    )
                    conn.executemany(
                        "DELETE FROM documents WHERE doc_id=?",
                        [(f"feed:{item_id}",) for item_id in old_ids],
                    )
                    removed = len(old_ids)
            if removed:
                from .search import rebuild_search_index

                rebuild_search_index()
        result["removed"] = removed
        result["replaced"] = bool(replace)
        _last_run_ts = time.time()
        _state["last_run"] = now_iso()
        _state["last_error"] = ""
        _state["last_result"] = result
        config["scheduler_last_run"] = _state["last_run"]
        try:
            save_config(config)
        except Exception:
            logger.warning("Could not persist scheduler last run", exc_info=True)
        logger.info(
            "Refresh finished: %s RSS sources, %s errors",
            len(result["rss"]),
            len(result["errors"]),
        )
        return result
    except Exception as exc:
        _state["last_error"] = str(exc)[:500]
        logger.exception("Refresh failed")
        return {"error": str(exc)}
    finally:
        _state["running"] = False


async def _loop() -> None:
    while True:
        try:
            config = load_config()
            if _schedule_due(config):
                await run_once(config)
            next_run = _next_run_datetime(config)
            _state["next_run_at"] = next_run.isoformat() if next_run else ""
            if not config.get("auto_refresh_enabled") or not has_any_key(config):
                _state["last_error"] = ""
            if config.get("auto_review_enabled") and has_any_key(config):
                await _maybe_review(config)
            try:
                from .embeddings import embed_pending, is_external

                if is_external(config):
                    await embed_pending(config, max_docs=20)
            except Exception as exc:
                logger.debug("Incremental embedding skipped: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _state["last_error"] = str(exc)[:500]
            logger.exception("Scheduler loop error")
        await asyncio.sleep(20)


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop(), name="pkm-scheduler")


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with suppress(asyncio.CancelledError):
            await _task
        _task = None


def status() -> dict[str, Any]:
    config = load_config()
    interval = _interval_seconds(config)
    enabled = bool(config.get("auto_refresh_enabled"))
    next_dt = _next_run_datetime(config)
    next_run = next_dt.isoformat() if next_dt else ""
    sources = list_sources("rss")
    return {
        "enabled": enabled,
        "schedule_mode": _schedule_mode(config),
        "daily_time": f"{_daily_hour_minute(config)[0]:02d}:{_daily_hour_minute(config)[1]:02d}",
        "interval_minutes": interval // 60,
        "rss_sources": [source["url"] for source in sources],
        "source_count": len(sources),
        "github_enabled": bool(config.get("auto_refresh_github", True)),
        "auto_review_enabled": bool(config.get("auto_review_enabled")),
        "review_interval_days": int(config.get("review_interval_days") or 7),
        "last_review_at": config.get("last_review_at") or "",
        "last_run": _state["last_run"],
        "last_error": _state["last_error"],
        "last_result": _state["last_result"],
        "running": _state["running"],
        "next_run": next_run,
    }
