from __future__ import annotations

from typing import Any

from ..config import load_config, save_config
from ..db import db
from ..providers import provider_from_config
from .agent import _profile_text


def _feedback_rows(limit: int = 12) -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT title, tags, feedback, relevance_reason
            FROM feed_items
            WHERE feedback != 0
            ORDER BY retrieved_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


async def suggest_profile(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_config()
    rows = _feedback_rows()
    if not rows:
        raise ValueError("还没有“有用/不相关”反馈，先标记几条资讯")
    provider = provider_from_config(config)
    feedback_text = "\n".join(
        f"- {'有用' if row['feedback'] > 0 else '不相关'}：{row['title']} "
        f"（标签：{row['tags']}；原因：{row['relevance_reason'] or '无'}）"
        for row in rows
    )
    user = f"""根据用户的历史反馈，提出对个人画像的最小修改建议。

当前画像：
{_profile_text(config)}

历史反馈：
{feedback_text}

只输出 JSON：
{{
  "skills_add": ["应该补充的技能，0-3 个"],
  "interests_add": ["应该补充的兴趣方向，0-3 个"],
  "learning_goals_add": ["应该补充的学习目标，0-3 个"],
  "interests_remove": ["应该移除或降低权重的兴趣，0-3 个"],
  "summary": "为什么这样调整，2-3 句"
}}
不要重复画像里已有的条目；没有把握的字段返回空数组。"""
    result = await provider.chat(
        [{"role": "user", "content": user}],
        system="你是谨慎的技术成长顾问，只根据反馈做小幅画像调整。",
        temperature=0.2,
        max_tokens=900,
    )
    from .text import parse_json_block

    parsed = parse_json_block(result.text) or {}
    suggestions = {
        "skills_add": [str(item).strip() for item in (parsed.get("skills_add") or []) if str(item).strip()][:3],
        "interests_add": [str(item).strip() for item in (parsed.get("interests_add") or []) if str(item).strip()][:3],
        "learning_goals_add": [str(item).strip() for item in (parsed.get("learning_goals_add") or []) if str(item).strip()][:3],
        "interests_remove": [str(item).strip() for item in (parsed.get("interests_remove") or []) if str(item).strip()][:3],
        "summary": str(parsed.get("summary") or "").strip(),
    }
    return {
        "current": config.get("profile") or {},
        "suggestions": suggestions,
        "feedback_count": len(rows),
        "provider": provider.name,
        "model": provider.model,
    }


def apply_profile_suggestions(
    suggestions: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    profile = config.setdefault("profile", {})
    for source_key, target_key in (
        ("skills_add", "skills"),
        ("interests_add", "interests"),
        ("learning_goals_add", "learning_goals"),
    ):
        current = list(profile.get(target_key) or [])
        existing = {item.lower() for item in current}
        for value in suggestions.get(source_key) or []:
            value = str(value).strip()
            if value and value.lower() not in existing:
                current.append(value)
                existing.add(value.lower())
        profile[target_key] = current[:20]
    remove = {str(value).lower() for value in suggestions.get("interests_remove") or []}
    if remove:
        profile["interests"] = [
            item for item in profile.get("interests") or [] if item.lower() not in remove
        ]
    save_config(config)
    return profile
