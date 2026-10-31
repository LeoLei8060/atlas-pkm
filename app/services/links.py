from __future__ import annotations

import json
import re
from typing import Any

from ..config import load_config
from ..providers import provider_from_config
from ..vector import cosine, vectorize
from ..vault import scan_notes
from .patches import create_patch


def _candidates(target: dict[str, Any], notes: list[dict[str, Any]], limit: int = 6):
    target_tags = {str(tag).lower() for tag in target["meta"].get("tags", []) or []}
    target_vector = vectorize(target["body"])
    scored = []
    for note in notes:
        if note["path"] == target["path"]:
            continue
        tags = {str(tag).lower() for tag in note["meta"].get("tags", []) or []}
        overlap = len(target_tags & tags) / max(len(target_tags | tags), 1)
        similarity = cosine(target_vector, vectorize(note["body"]))
        score = 0.6 * overlap + 0.4 * max(0.0, similarity)
        if score > 0:
            scored.append((score, note))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [note for _, note in scored[:limit]]


async def suggest_links(
    path: str,
    *,
    config: dict[str, Any] | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    config = config or load_config()
    notes = scan_notes()
    target = next((note for note in notes if note["path"] == path), None)
    if target is None:
        raise ValueError("笔记不存在")
    candidates = _candidates(target, notes, limit=6)
    if not candidates:
        return {"path": path, "suggestions": [], "patch": None}

    selected: list[dict[str, Any]] = []
    try:
        provider = provider_from_config(config)
        lines = "\n".join(
            f"[{index}] {note['title']}（{note['path']}）\n{note['body'][:500]}"
            for index, note in enumerate(candidates)
        )
        user = f"""请从候选笔记中挑选与目标笔记真正相关的条目，并给出关联理由。

目标笔记：{target['title']}
{target['body'][:2500]}

候选笔记：
{lines}

只输出 JSON 数组，最多 {limit} 条，按相关度排序：
[{{"index":0,"reason":"它们的关系，1 句"}}]
不要选择只是泛泛同主题、没有具体关联的条目。"""
        result = await provider.chat(
            [{"role": "user", "content": user}],
            system="你是知识库编辑，负责发现笔记之间的具体关联。",
            temperature=0.1,
            max_tokens=700,
        )
        text = result.text.strip()
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end > start:
            parsed = json.loads(text[start : end + 1])
            existing_links = {
                link.strip().lower()
                for link in re.findall(r"\[\[([^\]|#]+)", target["body"])
            }
            for entry in parsed[:limit]:
                if not isinstance(entry, dict):
                    continue
                index = entry.get("index")
                if not isinstance(index, int) or not (0 <= index < len(candidates)):
                    continue
                note = candidates[index]
                if note["title"].lower() in existing_links:
                    continue
                selected.append(
                    {
                        "path": note["path"],
                        "title": note["title"],
                        "reason": str(entry.get("reason") or "主题相关").strip(),
                    }
                )
    except Exception:
        selected = []

    if not selected:
        existing_links = {
            link.strip().lower()
            for link in re.findall(r"\[\[([^\]|#]+)", target["body"])
        }
        selected = [
            {
                "path": note["path"],
                "title": note["title"],
                "reason": "共享标签或内容相近",
            }
            for note in candidates[: min(3, limit)]
            if note["title"].lower() not in existing_links
        ]

    if not selected:
        return {"path": path, "suggestions": [], "patch": None}

    content = "\n".join(
        ["## 相关笔记", "", *[f"- [[{item['title']}]] — {item['reason']}" for item in selected]]
    )
    patch = create_patch(
        target_path=path,
        patch_type="append_section",
        title="相关笔记建议",
        content=content,
        source_refs=[{"path": item["path"], "title": item["title"]} for item in selected],
    )
    return {"path": path, "suggestions": selected, "patch": patch}


async def suggest_all(
    *, config: dict[str, Any] | None = None, max_notes: int = 8
) -> dict[str, Any]:
    config = config or load_config()
    results = []
    for note in scan_notes()[:max_notes]:
        if "## 相关笔记" in note["body"]:
            continue
        try:
            result = await suggest_links(note["path"], config=config, limit=3)
        except Exception:
            continue
        if result.get("patch"):
            results.append(result)
    return {
        "notes": len(results),
        "patches": len(results),
        "items": [
            {"path": item["path"], "patch": item["patch"].get("id"), "count": len(item["suggestions"])}
            for item in results
        ],
    }
