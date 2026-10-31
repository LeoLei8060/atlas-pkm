from __future__ import annotations

import json
from typing import Any

from ..config import load_config
from ..providers import ProviderNotConfigured, provider_from_config


async def translate_repo_descriptions(
    items: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not items:
        return items
    config = config or load_config()
    try:
        provider = provider_from_config(config)
    except ProviderNotConfigured:
        return items

    lines = [
        f"[{index}] {item.get('repo_full_name') or item.get('title')}: "
        f"{item.get('summary') or '（无描述）'}"
        for index, item in enumerate(items)
    ]
    user = (
        "下面是 GitHub 仓库的英文描述。逐条输出中文摘要和完整中文翻译。"
        "只输出 JSON 数组，顺序与输入一致，不要解释。\n"
        '格式：[{"index":0,"summary_zh":"1-2 句中文概括","translation_zh":"完整中文翻译"}]\n\n'
        + "\n".join(lines)
    )
    try:
        result = await provider.chat(
            [{"role": "user", "content": user}],
            system="你是技术编辑，负责把英文仓库描述准确地译成中文。",
            temperature=0.1,
            max_tokens=1800,
        )
        text = result.text.strip()
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            return items
        parsed = json.loads(text[start : end + 1])
        if not isinstance(parsed, list):
            return items
        by_index = {
            int(entry.get("index")): entry
            for entry in parsed
            if isinstance(entry, dict) and str(entry.get("index", "")).isdigit()
        }
        translated = []
        for index, item in enumerate(items):
            entry = by_index.get(index)
            if entry:
                summary = str(entry.get("summary_zh") or "").strip()
                translation = str(entry.get("translation_zh") or "").strip()
                if summary:
                    item = {**item, "summary_zh": summary}
                if translation:
                    item = {**item, "translation_zh": translation}
            translated.append(item)
        return translated
    except Exception:
        return items
