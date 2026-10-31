from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import load_config
from ..db import db, now_iso
from .feeds import FeedError, search_github
from .repo_translate import translate_repo_descriptions

CACHE_TTL_SECONDS = 20 * 60

STACKS: list[dict[str, Any]] = [
    {"id": "cpp", "name": "C++", "query": "language:C++"},
    {"id": "ai", "name": "AI", "query": "topic:ai"},
    {"id": "c", "name": "C", "query": "language:C"},
    {"id": "python", "name": "Python", "query": "language:Python"},
    {"id": "go", "name": "Go", "query": "language:Go"},
    {"id": "rust", "name": "Rust", "query": "language:Rust"},
    {
        "id": "skill",
        "name": "Skill",
        "query": "topic:agent-skills",
        "fallbacks": ["topic:claude-skills", '"agent skill" in:name,description'],
    },
    {"id": "typescript", "name": "TypeScript", "query": "language:TypeScript"},
    {
        "id": "network",
        "name": "网络编程",
        "query": "topic:network-programming",
        "fallbacks": ["topic:networking", '"network programming" in:name,description'],
    },
]

METRICS: list[dict[str, Any]] = [
    {
        "id": "new_today",
        "name": "今日 Star 增长",
        "gain_days": 1,
        "min_stars": 100,
        "sort": "gain",
        "hint": "按最近 1 天 Star 增量排序；首次采集次日才有对比数据",
    },
    {
        "id": "new_week",
        "name": "本周 Star 增长",
        "gain_days": 7,
        "min_stars": 100,
        "sort": "gain",
        "hint": "按最近 7 天 Star 增量排序；需要至少两天的快照",
    },
    {
        "id": "new_month",
        "name": "本月 Star 增长",
        "gain_days": 30,
        "min_stars": 100,
        "sort": "gain",
        "hint": "按最近 30 天 Star 增量排序；需要至少两天的快照",
    },
    {
        "id": "stars",
        "name": "总 Star",
        "min_stars": 1000,
        "sort": "stars",
        "hint": "按总 Star 数排序",
    },
    {
        "id": "forks",
        "name": "Fork 榜",
        "min_stars": 100,
        "sort": "forks",
        "hint": "按 Fork 数排序",
    },
    {
        "id": "quality",
        "name": "最新优质",
        "window_days": 90,
        "min_stars": 100,
        "sort": "stars",
        "hint": "近 90 天新建且超过 Star 门槛",
    },
]


class RankingError(Exception):
    pass


def _stack(stack_id: str) -> dict[str, Any]:
    for stack in STACKS:
        if stack["id"] == stack_id:
            return stack
    raise RankingError("未知技术栈")


def _metric(metric_id: str) -> dict[str, Any]:
    for metric in METRICS:
        if metric["id"] == metric_id:
            return metric
    raise RankingError("未知榜单")


def _query(stack: dict[str, Any], metric: dict[str, Any]) -> str:
    clauses = [stack["query"]]
    if metric.get("window_days"):
        since = (
            datetime.now(timezone.utc) - timedelta(days=int(metric["window_days"]))
        ).strftime("%Y-%m-%d")
        clauses.append(f"created:>{since}")
    if metric.get("min_stars"):
        clauses.append(f"stars:>{int(metric['min_stars'])}")
    return " ".join(clauses)


def _age_seconds(value: str) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(value)).total_seconds()
    except (ValueError, TypeError):
        return CACHE_TTL_SECONDS + 1


def _snapshot_date(days_ago: int = 0) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=days_ago)).isoformat()


def _save_snapshots(
    stack_id: str, items: list[dict[str, Any]], captured_at: str
) -> None:
    with db() as conn:
        for item in items:
            repo = str(item.get("repo_full_name") or "")
            if not repo:
                continue
            conn.execute(
                """
                INSERT INTO github_star_snapshots
                    (stack, repo_full_name, stars, captured_at, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(stack, repo_full_name, captured_at) DO UPDATE SET
                    stars=excluded.stars, payload=excluded.payload
                """,
                (
                    stack_id,
                    repo,
                    int(item.get("stars") or 0),
                    captured_at,
                    json.dumps(item, ensure_ascii=False),
                ),
            )


async def _capture_snapshots(
    stack: dict[str, Any], *, token: str, limit: int = 100
) -> list[dict[str, Any]]:
    queries = [stack["query"], *(stack.get("fallbacks") or [])]
    items: list[dict[str, Any]] = []
    for query in queries:
        items = await search_github(
            f"{query} stars:>100",
            sort="stars",
            limit=limit,
            token=token,
        )
        if items:
            break
    if items:
        _save_snapshots(stack["id"], items, _snapshot_date())
    return items


def _gain_ranking(stack_id: str, days: int, limit: int) -> list[dict[str, Any]]:
    since = _snapshot_date(days)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT repo_full_name, stars, captured_at, payload
            FROM github_star_snapshots
            WHERE stack=? AND captured_at>=?
            ORDER BY repo_full_name, captured_at
            """,
            (stack_id, since),
        ).fetchall()
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(row["repo_full_name"], []).append(row)
    gained: list[dict[str, Any]] = []
    for repo_rows in grouped.values():
        if len(repo_rows) < 2:
            continue
        first, last = repo_rows[0], repo_rows[-1]
        gain = int(last["stars"]) - int(first["stars"])
        if gain <= 0:
            continue
        try:
            item = json.loads(last["payload"])
        except json.JSONDecodeError:
            continue
        item["star_gain"] = gain
        item["star_baseline"] = int(first["stars"])
        item["snapshot_days"] = len(repo_rows)
        gained.append(item)
    gained.sort(key=lambda item: item["star_gain"], reverse=True)
    return gained[:limit]


async def get_ranking(
    stack_id: str,
    metric_id: str,
    *,
    limit: int = 10,
    refresh: bool = False,
    token: str = "",
) -> dict[str, Any]:
    stack = _stack(stack_id)
    metric = _metric(metric_id)
    limit = max(5, min(limit, 20))

    cached_items: list[dict[str, Any]] | None = None
    cached_at = ""
    with db() as conn:
        row = conn.execute(
            "SELECT items, fetched_at FROM github_rankings WHERE stack=? AND metric=?",
            (stack_id, metric_id),
        ).fetchone()
    if row:
        cached_items = json.loads(row["items"])
        cached_at = row["fetched_at"]
        if not refresh and _age_seconds(cached_at) < CACHE_TTL_SECONDS:
            return {
                "stack": stack,
                "metric": metric,
                "items": cached_items,
                "fetched_at": cached_at,
                "cached": True,
                "stale": False,
                "error": "",
                "notice": ""
                if cached_items or not metric.get("gain_days")
                else "已记录今日 Star 快照；至少需要两天的快照才能计算增长。",
            }

    if metric.get("gain_days"):
        try:
            await _capture_snapshots(stack, token=token)
        except FeedError as exc:
            if cached_items:
                return {
                    "stack": stack,
                    "metric": metric,
                    "items": cached_items,
                    "fetched_at": cached_at,
                    "cached": True,
                    "stale": True,
                    "error": str(exc),
                    "notice": "",
                }
            raise RankingError(str(exc)) from exc
        items = _gain_ranking(stack_id, int(metric["gain_days"]), limit)
        if items:
            items = await translate_repo_descriptions(items, load_config())
        fetched_at = now_iso()
        with db() as conn:
            conn.execute(
                """
                INSERT INTO github_rankings(stack, metric, items, fetched_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(stack, metric) DO UPDATE SET
                    items=excluded.items, fetched_at=excluded.fetched_at
                """,
                (stack_id, metric_id, json.dumps(items, ensure_ascii=False), fetched_at),
            )
        return {
            "stack": stack,
            "metric": metric,
            "items": items,
            "fetched_at": fetched_at,
            "cached": False,
            "stale": False,
            "error": "",
            "notice": "" if items else "已记录今日 Star 快照；至少需要两天的快照才能计算增长。",
        }

    queries = [stack["query"], *(stack.get("fallbacks") or [])]
    items: list[dict[str, Any]] = []
    error = ""
    for query in queries:
        try:
            items = await search_github(
                _query({**stack, "query": query}, metric),
                sort=metric.get("sort") or "stars",
                limit=limit,
                token=token,
            )
        except FeedError as exc:
            error = str(exc)
            break
        if items:
            break

    if not items and error:
        if cached_items:
            return {
                "stack": stack,
                "metric": metric,
                "items": cached_items,
                "fetched_at": cached_at,
                "cached": True,
                "stale": True,
                "error": error,
            }
        raise RankingError(error)

    if items:
        items = await translate_repo_descriptions(items, load_config())

    fetched_at = now_iso()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO github_rankings(stack, metric, items, fetched_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(stack, metric) DO UPDATE SET
                items=excluded.items, fetched_at=excluded.fetched_at
            """,
            (stack_id, metric_id, json.dumps(items, ensure_ascii=False), fetched_at),
        )
    return {
        "stack": stack,
        "metric": metric,
        "items": items,
        "fetched_at": fetched_at,
        "cached": False,
        "stale": False,
        "error": "",
    }


def meta() -> dict[str, Any]:
    return {
        "stacks": [{key: value for key, value in stack.items() if key != "fallbacks"} for stack in STACKS],
        "metrics": METRICS,
        "cache_ttl_minutes": CACHE_TTL_SECONDS // 60,
        "notice": "Star 增长按每日快照计算；首次采集后会建立基线，至少需要两天的快照才能计算增长。",
    }


def default_token() -> str:
    return str(load_config().get("github_token") or "")
