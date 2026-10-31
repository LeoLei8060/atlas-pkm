from __future__ import annotations

import hashlib
import json
from typing import Any

from ..config import load_config
from ..db import db, record_run
from ..providers import ProviderNotConfigured, provider_from_config
from .feeds import get_feed, update_feed
from .search import build_context_async
from .text import compact, parse_json_block

SYSTEM_SUMMARY = """你是一个中文技术知识库的编辑。你的任务是把外部资讯整理成可检索、可引用的中文笔记。
只根据给定内容工作，不要编造事实。输出必须是 JSON，不要输出 Markdown 代码围栏之外的解释。"""

SYSTEM_ANSWER = """你是一个个人知识库问答助手。优先使用给定的本地资料回答；资料不足时明确说明，不要编造引用。
引用使用 [1]、[2] 这样的编号，对应给定资料的编号。回答用中文，简洁、具体。"""


def _run_id(task: str) -> str:
    import uuid

    return f"{task}_{uuid.uuid4().hex[:12]}"


def _start_run(task: str, provider: str, model: str) -> tuple[str, str]:
    run_id = _run_id(task)
    from ..db import now_iso

    record_run(
        run_id=run_id,
        task_type=task,
        provider=provider,
        model=model,
        status="running",
        started_at=now_iso(),
    )
    return run_id, now_iso()


def _finish_run(
    run_id: str,
    *,
    status: str,
    error: str = "",
    meta: dict[str, Any] | None = None,
) -> None:
    from ..db import now_iso

    record_run(
        run_id=run_id,
        task_type="",
        provider="",
        model="",
        status=status,
        error=error,
        finished_at=now_iso(),
        meta=meta or {},
    )


def _provider(config: dict[str, Any]):
    return provider_from_config(config)


def _profile_text(config: dict[str, Any]) -> str:
    profile = config.get("profile") or {}
    parts = []
    if profile.get("target_role"):
        parts.append(f"目标岗位：{profile['target_role']}")
    if profile.get("level"):
        parts.append(f"当前水平：{profile['level']}")
    if profile.get("languages"):
        parts.append(f"编程语言：{', '.join(str(value) for value in profile['languages'])}")
    for key, label in (
        ("skills", "已有技能"),
        ("learning_goals", "学习目标"),
    ):
        values = profile.get(key) or []
        if values:
            parts.append(f"{label}：{', '.join(str(value) for value in values)}")
    if profile.get("weekly_hours"):
        parts.append(f"每周可投入：{profile['weekly_hours']} 小时")
    return "\n".join(parts) if parts else "（用户尚未填写个人画像）"


async def expand_query(question: str, provider) -> list[str]:
    result = await provider.chat(
        [
            {
                "role": "user",
                "content": (
                    "为下面的问题生成用于本地知识库检索的关键词、同义词和英文对应词。"
                    "只输出 JSON 字符串数组，不要解释。最多 8 个。\n\n"
                    f"问题：{question}"
                ),
            }
        ],
        system="你是检索查询扩展器，只输出 JSON 数组。",
        temperature=0.0,
        max_tokens=220,
    )
    text = result.text.strip()
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()][:8]
        except json.JSONDecodeError:
            pass
    return [
        line.strip(" -•\t\"'")
        for line in text.splitlines()
        if line.strip(" -•\t\"'")
    ][:8]


async def _translate_text(text: str, provider) -> str:
    result = await provider.chat(
        [
            {
                "role": "user",
                "content": (
                    "把下面的技术内容翻译成中文。保留代码、URL、API 名称和技术名词；"
                    "如果原文过长，可压缩到 1800 字以内，但不要只给摘要。只输出译文。\n\n"
                    + compact(text, 3200)
                ),
            }
        ],
        system="你是一个严谨的技术翻译。",
        temperature=0.1,
        max_tokens=1800,
    )
    return result.text.strip()


async def summarize_feed_item(feed_id: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_config()
    item = get_feed(feed_id)
    if item is None:
        raise ValueError("内容不存在")
    provider = _provider(config)
    run_id, _ = _start_run("summarize", provider.name, provider.model)
    profile = _profile_text(config)
    try:
        if item["source_type"] == "github":
            user = f"""请为下面这个 GitHub 仓库生成中文档案概述。

仓库：{item['title']}
描述：{item.get('summary') or '（无）'}
语言：{item.get('primary_language') or '未知'}
Star：{item.get('stars', 0)}
License：{item.get('license') or '未知'}
Topics：{', '.join(item.get('tags') or [])}

用户画像：
{profile}

请输出 JSON：
{{
  "summary_zh": "2-4 句中文概述，说明项目解决什么问题、适合谁",
  "translation_zh": "把上面的仓库描述完整翻译成中文，保留项目名和技术名",
  "relevance_score": 0.0,
  "relevance_reason": "它与用户目标岗位/学习目标的关系，1-2 句",
  "knowledge_gaps": ["这条内容暴露出的知识缺口，0-3 条"],
  "key_points": ["3-5 条值得关注的点"],
  "tags": ["3-6 个中文或英文标签"]
}}"""
        else:
            user = f"""请整理下面这篇文章，输出 JSON。

标题：{item['title']}
来源：{item.get('source_name') or item.get('source_type')}
链接：{item['url']}
正文/摘要：
{compact(item.get('content') or item.get('summary'), 3500)}

用户画像：
{profile}

输出格式：
{{
  "summary_zh": "2-4 句中文摘要",
  "translation_zh": "完整中文翻译；原文过长时压缩到 1800 字以内；保留段落、代码、URL 和技术名词；如果原文已经是中文，输出原文",
  "relevance_score": 0.0,
  "relevance_reason": "它与用户目标岗位/学习目标的关系，1-2 句",
  "knowledge_gaps": ["这条内容暴露出的知识缺口，0-3 条"],
  "key_points": ["3-5 条关键点"],
  "tags": ["3-6 个标签"]
}}"""
        result = await provider.chat(
            [{"role": "user", "content": user}],
            system=SYSTEM_SUMMARY,
            temperature=0.2,
            max_tokens=2400,
        )
        parsed = parse_json_block(result.text) or {}
        summary = str(parsed.get("summary_zh") or "").strip()
        translation = str(parsed.get("translation_zh") or "").strip()
        key_points = parsed.get("key_points") if isinstance(parsed.get("key_points"), list) else []
        tags = parsed.get("tags") if isinstance(parsed.get("tags"), list) else []
        gaps = parsed.get("knowledge_gaps") if isinstance(parsed.get("knowledge_gaps"), list) else []
        try:
            relevance = float(parsed.get("relevance_score") or 0)
        except (TypeError, ValueError):
            relevance = 0.0
        relevance = max(0.0, min(1.0, relevance))
        reason = str(parsed.get("relevance_reason") or "").strip()
        if not translation:
            try:
                translation = await _translate_text(
                    item.get("content") or item.get("summary") or item.get("title") or "",
                    provider,
                )
            except Exception:
                translation = ""
        if not summary or summary.lstrip().startswith("{"):
            summary = (
                "（模型摘要输出被截断，以下为中文翻译节选）"
                + translation[:500]
                if translation
                else "（摘要生成失败，请稍后重试）"
            )
        if not summary:
            summary = result.text.strip()[:1200]
        merged_tags = list(dict.fromkeys([*(item.get("tags") or []), *[str(t) for t in tags]]))[:10]
        updated = update_feed(
            feed_id,
            summary_zh=summary,
            translation_zh=translation,
            tags=merged_tags,
            translated=1,
            relevance_score=relevance,
            relevance_reason=reason,
            knowledge_gaps=[str(gap) for gap in gaps][:5],
        )
        _finish_run(
            run_id,
            status="succeeded",
            meta={
                "feed_id": feed_id,
                "summary_chars": len(summary),
                "translation_chars": len(translation),
                "relevance": relevance,
            },
        )
        return {
            "item": updated,
            "summary_zh": summary,
            "translation_zh": translation,
            "relevance_score": relevance,
            "relevance_reason": reason,
            "knowledge_gaps": [str(gap) for gap in gaps][:5],
            "key_points": key_points,
            "tags": merged_tags,
        }
    except Exception as exc:
        _finish_run(run_id, status="failed", error=str(exc)[:800])
        raise


async def score_feed_item(feed_id: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_config()
    profile = config.get("profile") or {}
    if not any(
        [
            profile.get("target_role"),
            profile.get("languages"),
            profile.get("skills"),
            profile.get("learning_goals"),
        ]
    ):
        raise ValueError("请先在设置中填写个人画像")
    item = get_feed(feed_id)
    if item is None:
        raise ValueError("内容不存在")
    provider = _provider(config)
    run_id, _ = _start_run("score", provider.name, provider.model)
    try:
        with db() as conn:
            positive = conn.execute(
                "SELECT title FROM feed_items WHERE feedback=1 ORDER BY retrieved_at DESC LIMIT 3"
            ).fetchall()
            negative = conn.execute(
                "SELECT title FROM feed_items WHERE feedback=-1 ORDER BY retrieved_at DESC LIMIT 3"
            ).fetchall()
        feedback_text = "\n".join(
            [
                *[f"- 有用：{row['title']}" for row in positive],
                *[f"- 不相关：{row['title']}" for row in negative],
            ]
        ) or "（暂无反馈）"
        user = f"""请评估下面这条资讯与用户个人画像的匹配度。

用户画像：
{_profile_text(config)}

历史反馈（用于校准判断）：
{feedback_text}

资讯标题：{item['title']}
中文摘要：{item.get('summary_zh') or item.get('summary') or '（无）'}
标签：{', '.join(item.get('tags') or [])}

只输出 JSON：
{{
  "relevance_score": 0.0,
  "relevance_reason": "与目标岗位/学习目标的关系，1-2 句",
  "knowledge_gaps": ["这条内容暴露出的知识缺口，0-3 条"]
}}"""
        result = await provider.chat(
            [{"role": "user", "content": user}],
            system="你是技术学习顾问，评估资讯对用户目标的实际价值。",
            temperature=0.1,
            max_tokens=500,
        )
        parsed = parse_json_block(result.text) or {}
        try:
            score = float(parsed.get("relevance_score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(1.0, score))
        reason = str(parsed.get("relevance_reason") or "").strip()
        gaps = parsed.get("knowledge_gaps") if isinstance(parsed.get("knowledge_gaps"), list) else []
        updated = update_feed(
            feed_id,
            relevance_score=score,
            relevance_reason=reason,
            knowledge_gaps=[str(gap) for gap in gaps][:5],
        )
        _finish_run(run_id, status="succeeded", meta={"feed_id": feed_id, "relevance": score})
        return {
            "item": updated,
            "relevance_score": score,
            "relevance_reason": reason,
            "knowledge_gaps": [str(gap) for gap in gaps][:5],
        }
    except Exception as exc:
        _finish_run(run_id, status="failed", error=str(exc)[:800])
        raise


async def translate_feed_item(feed_id: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_config()
    item = get_feed(feed_id)
    if item is None:
        raise ValueError("内容不存在")
    provider = _provider(config)
    run_id, _ = _start_run("translate", provider.name, provider.model)
    try:
        text = item.get("content") or item.get("summary") or item.get("title") or ""
        user = f"""把下面的英文技术内容翻译成中文。

要求：
- 保留代码块、行内代码、URL、API 名称、License 名称
- 技术术语使用常见中文译法，必要时保留英文
- 只输出译文，不要解释

内容：
{compact(text, 7000)}"""
        result = await provider.chat(
            [{"role": "user", "content": user}],
            system="你是一个严谨的技术翻译。",
            temperature=0.1,
            max_tokens=1600,
        )
        translation = result.text.strip()
        updated = update_feed(feed_id, translation_zh=translation, translated=1)
        _finish_run(run_id, status="succeeded", meta={"feed_id": feed_id})
        return {"item": updated, "translation": translation}
    except Exception as exc:
        _finish_run(run_id, status="failed", error=str(exc)[:800])
        raise


async def answer_question(
    question: str,
    config: dict[str, Any] | None = None,
    limit: int = 6,
) -> dict[str, Any]:
    config = config or load_config()
    question = (question or "").strip()
    if not question:
        raise ValueError("问题不能为空")
    provider = _provider(config)
    run_id, _ = _start_run("answer", provider.name, provider.model)
    expanded_terms: list[str] = []
    if config.get("query_expansion_enabled", True):
        try:
            expanded_terms = await expand_query(question, provider)
        except Exception:
            expanded_terms = []
    search_query = question
    if expanded_terms:
        search_query = question + " " + " ".join(expanded_terms)
    context = await build_context_async(search_query, config, limit=limit)
    try:
        blocks = []
        for item in context:
            blocks.append(
                f"[{item['index']}] {item['title']}\n"
                f"类型：{item['kind']}\n"
                f"链接：{item.get('source_url') or item.get('path') or ''}\n"
                f"{compact(item['content'], 2200)}"
            )
        context_text = "\n\n".join(blocks) if blocks else "（本地知识库没有检索到相关资料）"
        user = f"""问题：{question}

本地资料：
{context_text}

请回答上面的问题。要求：
1. 优先使用本地资料；如果资料不足，明确说“本地知识库中没有足够依据”，再给出一般性说明。
2. 用 [1]、[2] 标注引用，编号对应资料编号。
3. 回答末尾列出“不确定性”（如果有）。"""
        result = await provider.chat(
            [{"role": "user", "content": user}],
            system=SYSTEM_ANSWER,
            temperature=0.2,
            max_tokens=1400,
        )
        citations = [
            {
                "index": item["index"],
                "title": item["title"],
                "doc_id": item["doc_id"],
                "kind": item["kind"],
                "path": item.get("path"),
                "source_url": item.get("source_url"),
                "snippet": item.get("snippet"),
            }
            for item in context
        ]
        _finish_run(
            run_id,
            status="succeeded",
            meta={
                "question": question[:200],
                "context_count": len(context),
                "expanded_terms": expanded_terms,
            },
        )
        return {
            "answer": result.text.strip(),
            "citations": citations,
            "context_count": len(context),
            "provider": provider.name,
            "model": provider.model,
            "expanded_terms": expanded_terms,
        }
    except Exception as exc:
        _finish_run(run_id, status="failed", error=str(exc)[:800])
        raise


async def enrich_items(
    feed_ids: list[str],
    config: dict[str, Any] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    config = config or load_config()
    results = []
    selected = feed_ids if limit is None else feed_ids[:limit]
    for feed_id in selected:
        try:
            results.append(await summarize_feed_item(feed_id, config))
        except Exception as exc:
            results.append({"feed_id": feed_id, "error": str(exc)})
    return results
