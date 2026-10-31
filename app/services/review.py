from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import load_config
from ..db import db
from ..providers import provider_from_config
from ..vault import scan_notes
from .agent import _profile_text


def _stats(days: int) -> dict[str, Any]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with db() as conn:
        feed_total = conn.execute(
            "SELECT COUNT(*) FROM feed_items WHERE retrieved_at >= ?", (since,)
        ).fetchone()[0]
        saved = conn.execute(
            "SELECT COUNT(*) FROM feed_items WHERE retrieved_at >= ? AND status='saved'",
            (since,),
        ).fetchone()[0]
        feedback = conn.execute(
            "SELECT SUM(CASE WHEN feedback=1 THEN 1 ELSE 0 END), SUM(CASE WHEN feedback=-1 THEN 1 ELSE 0 END) FROM feed_items WHERE retrieved_at >= ?",
            (since,),
        ).fetchone()
        rows = conn.execute(
            "SELECT tags FROM feed_items WHERE retrieved_at >= ?", (since,)
        ).fetchall()
        avg_relevance = conn.execute(
            "SELECT AVG(relevance_score) FROM feed_items WHERE retrieved_at >= ? AND relevance_score > 0",
            (since,),
        ).fetchone()[0]
    tags = Counter()
    for row in rows:
        try:
            tags.update(json.loads(row["tags"] or "[]"))
        except json.JSONDecodeError:
            pass
    notes = scan_notes()
    return {
        "days": days,
        "feed_total": int(feed_total or 0),
        "saved": int(saved or 0),
        "notes_total": len(notes),
        "feedback_useful": int(feedback[0] or 0),
        "feedback_not_useful": int(feedback[1] or 0),
        "avg_relevance": round(float(avg_relevance or 0), 2),
        "top_tags": [tag for tag, _ in tags.most_common(8)],
    }


async def weekly_review(days: int = 7, config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_config()
    days = max(1, min(int(days), 90))
    stats = _stats(days)
    with db() as conn:
        recent = conn.execute(
            "SELECT title, summary_zh, relevance_score FROM feed_items ORDER BY retrieved_at DESC LIMIT 12"
        ).fetchall()
    titles = "\n".join(
        f"- {row['title']}（匹配度 {round(float(row['relevance_score'] or 0) * 100)}%）"
        for row in recent
    )
    provider = provider_from_config(config)
    user = f"""请为下面的个人知识库生成一份中文周期复盘。

用户画像：
{_profile_text(config)}

最近 {days} 天统计：
- 新增资讯：{stats['feed_total']}
- 收藏：{stats['saved']}
- 笔记总数：{stats['notes_total']}
- 平均匹配度：{stats['avg_relevance']}
- 有用反馈：{stats['feedback_useful']}；不相关反馈：{stats['feedback_not_useful']}
- 高频标签：{', '.join(stats['top_tags']) or '无'}

最近资讯：
{titles}

输出 Markdown，包含：
1. 本期概况（用统计说话）
2. 学到的核心主题
3. 知识缺口（结合画像）
4. 下期建议（3-5 条，按优先级）
5. 建议投入时间（用户每周 {config.get('profile', {}).get('weekly_hours', 5)} 小时）

不要编造统计之外的数据。"""
    result = await provider.chat(
        [{"role": "user", "content": user}],
        system="你是务实的个人技术成长教练。",
        temperature=0.3,
        max_tokens=1800,
    )
    return {
        "days": days,
        "stats": stats,
        "markdown": result.text.strip(),
        "provider": provider.name,
        "model": provider.model,
    }


def stats(days: int = 7) -> dict[str, Any]:
    return _stats(max(1, min(int(days), 90)))
