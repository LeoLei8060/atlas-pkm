from __future__ import annotations

import asyncio
import json

from app.providers.base import ChatResult
from app.services import agent, enrichment
from app.services.demo import seed_demo
from app.services.feeds import get_feed, list_feed
from app.services.notes import save_feed_as_source
from app.vault import target_path


class FakeProvider:
    name = "fake"
    model = "fake-model"

    async def chat(self, *args, **kwargs):
        return ChatResult(
            text=json.dumps(
                {
                    "summary_zh": "这是中文摘要。",
                    "translation_zh": "这是完整中文翻译。",
                    "relevance_score": 0.82,
                    "relevance_reason": "与目标岗位相关。",
                    "knowledge_gaps": ["系统设计"],
                    "key_points": ["要点一"],
                    "tags": ["测试"],
                },
                ensure_ascii=False,
            ),
            provider=self.name,
            model=self.model,
        )


def test_summarize_writes_summary_and_translation(isolated, monkeypatch):
    seed_demo()
    item = list_feed()[0]
    monkeypatch.setattr(agent, "_provider", lambda config: FakeProvider())
    result = asyncio.run(agent.summarize_feed_item(item["id"], {}))
    assert result["summary_zh"] == "这是中文摘要。"
    assert result["translation_zh"] == "这是完整中文翻译。"
    updated = get_feed(item["id"])
    assert updated["summary_zh"] == "这是中文摘要。"
    assert updated["translation_zh"] == "这是完整中文翻译。"


def test_saved_note_contains_translation(isolated, monkeypatch):
    seed_demo()
    item = list_feed()[0]
    monkeypatch.setattr(agent, "_provider", lambda config: FakeProvider())
    asyncio.run(agent.summarize_feed_item(item["id"], {}))
    saved = save_feed_as_source(item["id"])
    text = target_path(saved["path"]).read_text(encoding="utf-8")
    assert "## 中文翻译" in text
    assert "这是完整中文翻译。" in text


def test_enrich_items_processes_all_ids(isolated, monkeypatch):
    seed_demo()
    calls = []

    async def fake_summary(feed_id, config=None):
        calls.append(feed_id)
        return {"feed_id": feed_id}

    monkeypatch.setattr(agent, "summarize_feed_item", fake_summary)
    ids = [item["id"] for item in list_feed()]
    result = asyncio.run(agent.enrich_items(ids, {}))
    assert len(result) == len(ids)
    assert calls == ids


def test_score_feed_item_with_profile(isolated, monkeypatch):
    seed_demo()
    item = list_feed()[0]
    monkeypatch.setattr(agent, "_provider", lambda config: FakeProvider())
    result = asyncio.run(
        agent.score_feed_item(
            item["id"],
            {"profile": {"target_role": "系统工程师", "skills": ["Rust"]}},
        )
    )
    assert result["relevance_score"] == 0.82
    assert result["relevance_reason"] == "与目标岗位相关。"
    updated = get_feed(item["id"])
    assert updated["relevance_score"] == 0.82
    assert updated["knowledge_gaps"] == ["系统设计"]


def test_score_requires_profile(isolated):
    seed_demo()
    item = list_feed()[0]
    try:
        asyncio.run(agent.score_feed_item(item["id"], {"profile": {}}))
    except ValueError as exc:
        assert "个人画像" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_pending_ids_includes_missing_translation(isolated):
    seed_demo()
    assert enrichment.pending_ids()
