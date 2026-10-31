from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from ..config import load_config
from ..db import _search_terms, db
from ..providers import provider_from_config
from ..vector import cosine, vectorize
from ..vault import scan_notes, target_path
from .agent import _profile_text
from .patches import create_patch
from .search import build_context_async
from .text import compact, parse_json_block


def _citations(context: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "index": item["index"],
            "title": item["title"],
            "path": item.get("path"),
            "source_url": item.get("source_url"),
            "kind": item.get("kind"),
        }
        for item in context
    ]


def _context_text(context: list[dict[str, Any]]) -> str:
    if not context:
        return "（本地知识库没有检索到直接相关的资料）"
    return "\n\n".join(
        f"[{item['index']}] {item['title']}\n{compact(item['content'], 1800)}"
        for item in context
    )


def _slug(topic: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", topic.strip()).strip("-")
    return value[:60] or "untitled"


def _draft_path(topic: str) -> str:
    return f"01-Drafts/{_slug(topic)}-{date.today().isoformat()}.md"


def _available_target(topic: str) -> str:
    base = _draft_path(topic)
    stem = base[:-3]
    for index in range(1, 50):
        candidate = base if index == 1 else f"{stem}-{index}.md"
        if target_path(candidate).exists():
            continue
        with db() as conn:
            exists = conn.execute(
                "SELECT 1 FROM patches WHERE target_path=? AND status='proposed' LIMIT 1",
                (candidate,),
            ).fetchone()
        if not exists:
            return candidate
    return f"{stem}-{date.today().isoformat()}-new.md"


def _excerpt(text: str, limit: int = 180) -> str:
    plain = re.sub(r"^#{1,6}\s+.*$", "", text, flags=re.M)
    plain = re.sub(r"<!--.*?-->", "", plain, flags=re.S)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain[:limit]


def analyze_save(topic: str, markdown: str) -> dict[str, Any]:
    """Compare generated content with local notes before writing anything."""
    generated = f"{topic}\n{markdown[:6000]}"
    generated_vector = vectorize(generated)
    terms = _search_terms(topic)
    target = _draft_path(topic)
    target_exists = target_path(target).exists()
    related: list[dict[str, Any]] = []
    for note in scan_notes():
        note_text = f"{note['title']}\n{note['body'][:6000]}"
        note_vector = vectorize(note_text)
        similarity = max(0.0, cosine(generated_vector, note_vector))
        haystack = note_text.lower()
        coverage = (
            sum(1 for term in terms if term.lower() in haystack) / len(terms)
            if terms
            else 0.0
        )
        title_bonus = 0.08 if topic.lower() in note["title"].lower() else 0.0
        score = min(1.0, 0.65 * similarity + 0.35 * coverage + title_bonus)
        if score < 0.08:
            continue
        related.append(
            {
                "path": note["path"],
                "title": note["title"],
                "similarity": round(score, 3),
                "coverage": round(coverage, 3),
                "excerpt": _excerpt(note["body"]),
                "updated_at": note["updated_at"],
                "same_target": note["path"] == target,
            }
        )
    related.sort(key=lambda item: item["similarity"], reverse=True)
    related = related[:5]
    duplicate = next(
        (
            item
            for item in related
            if item["similarity"] >= 0.45
            and item["coverage"] >= 0.60
            and not item["same_target"]
        ),
        None,
    )
    return {
        "target_path": target,
        "target_exists": target_exists,
        "duplicate": duplicate,
        "related": related,
    }


async def generate(
    topic: str,
    *,
    mode: str = "knowledge_doc",
    config: dict[str, Any] | None = None,
    difficulty: str = "中级",
    count: int = 5,
) -> dict[str, Any]:
    config = config or load_config()
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("主题不能为空")
    count = max(3, min(int(count), 10))
    context = await build_context_async(topic, config, limit=6)
    context_text = _context_text(context)
    profile = _profile_text(config)
    provider = provider_from_config(config)

    if mode == "interview":
        user = f"""你在为下面的用户准备技术面试。

用户画像：
{profile}

主题：{topic}
难度：{difficulty}
题目数量：{count}

本地资料：
{context_text}

请输出 JSON：
{{
  "questions": [
    {{
      "question": "面试题",
      "answer": "参考答案，结合本地资料；资料不足时说明",
      "followups": ["追问 1", "追问 2"],
      "difficulty": "初级/中级/高级",
      "why": "考察点"
    }}
  ]
}}
题目要覆盖概念、原理、实践和排错，不要重复。"""
        result = await provider.chat(
            [{"role": "user", "content": user}],
            system="你是严格但务实的技术面试官。只输出指定 JSON。",
            temperature=0.3,
            max_tokens=2600,
        )
        parsed = parse_json_block(result.text) or {}
        questions = parsed.get("questions") if isinstance(parsed.get("questions"), list) else []
        if not questions:
            markdown = f"# 面试题：{topic}\n\n{result.text.strip()}"
            return {
                "mode": mode,
                "topic": topic,
                "markdown": markdown,
                "questions": [],
                "citations": _citations(context),
                "save_context": analyze_save(topic, markdown),
                "provider": provider.name,
                "model": provider.model,
            }
        lines = [f"# 面试题：{topic}", "", f"难度：{difficulty}", ""]
        for index, question in enumerate(questions, start=1):
            lines.append(f"## {index}. {question.get('question', '')}")
            lines.append("")
            lines.append(f"**考察点**：{question.get('why', '')}")
            lines.append("")
            lines.append("**参考答案**")
            lines.append("")
            lines.append(str(question.get("answer", "")))
            lines.append("")
            followups = question.get("followups") or []
            if followups:
                lines.append("**追问**")
                lines.append("")
                lines += [f"- {followup}" for followup in followups]
                lines.append("")
        markdown = "\n".join(lines)
        return {
            "mode": mode,
            "topic": topic,
            "markdown": markdown,
            "questions": questions,
            "citations": _citations(context),
            "save_context": analyze_save(topic, markdown),
            "provider": provider.name,
            "model": provider.model,
        }

    user = f"""你在为下面的用户编写一份可长期查阅的中文知识文档。

用户画像：
{profile}

主题：{topic}

本地资料：
{context_text}

要求：
1. 用 Markdown，包含：概念、为什么重要、核心原理、实践要点、常见误区、延伸学习。
2. 优先使用本地资料；资料不足时明确标注“本地资料不足”，再补充一般性知识。
3. 引用使用 [1]、[2]，编号对应本地资料。
4. 不要编造本地资料中没有的事实。"""
    result = await provider.chat(
        [{"role": "user", "content": user}],
        system="你是技术知识库的主笔，写作准确、结构化、可复习。",
        temperature=0.3,
        max_tokens=2800,
    )
    markdown = result.text.strip()
    if not markdown.startswith("#"):
        markdown = f"# {topic}\n\n{markdown}"
    return {
        "mode": "knowledge_doc",
        "topic": topic,
        "markdown": markdown,
        "questions": [],
        "citations": _citations(context),
        "save_context": analyze_save(topic, markdown),
        "provider": provider.name,
        "model": provider.model,
    }


def save_as_patch(
    topic: str,
    markdown: str,
    *,
    citations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    title = topic.strip() or "学习笔记"
    target = _available_target(title)
    return create_patch(
        target_path=target,
        patch_type="create_note",
        title=title,
        content=markdown.strip() + "\n",
        source_refs=citations or [],
    )


def append_to_note(
    path: str,
    topic: str,
    markdown: str,
    *,
    citations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    note = next((item for item in scan_notes() if item["path"] == path), None)
    if note is None:
        raise ValueError("目标笔记不存在")
    body = re.sub(r"^\s*#\s+.*\n+", "", markdown.strip(), count=1)
    content = f"## 知识文档：{topic.strip()}\n\n{body.strip()}\n"
    return create_patch(
        target_path=path,
        patch_type="append_section",
        title=f"知识文档：{topic.strip()}",
        content=content,
        source_refs=citations or [],
    )
