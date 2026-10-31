from __future__ import annotations

import asyncio
import json

from app.providers.base import ChatResult
from app.services import graph, learning, review
from app.services.demo import seed_demo
from app.services.patches import list_patches
from app.vault import atomic_write, dump_note, target_path


class DocProvider:
    name = "fake"
    model = "fake"

    async def chat(self, *args, **kwargs):
        return ChatResult("# Rust 取消安全\n\n本地资料总结。 [1]", "fake", "fake")


class InterviewProvider:
    name = "fake"
    model = "fake"

    async def chat(self, *args, **kwargs):
        payload = {
            "questions": [
                {
                    "question": "什么是取消安全？",
                    "answer": "Future 被 drop 后不留下不一致状态。",
                    "followups": ["select! 如何取消分支？"],
                    "difficulty": "中级",
                    "why": "考察异步基础",
                }
            ]
        }
        return ChatResult(json.dumps(payload, ensure_ascii=False), "fake", "fake")


def test_generate_knowledge_doc_and_save(isolated, monkeypatch):
    seed_demo()
    monkeypatch.setattr(learning, "provider_from_config", lambda config: DocProvider())
    result = asyncio.run(learning.generate("Rust 取消安全", config={"profile": {}}))
    assert result["mode"] == "knowledge_doc"
    assert "Rust 取消安全" in result["markdown"]
    assert "save_context" in result
    patch = learning.save_as_patch(
        result["topic"], result["markdown"], citations=result["citations"]
    )
    assert patch["target_path"].startswith("01-Drafts/")
    assert list_patches()


def test_analyze_save_and_append(isolated):
    seed_demo()
    analysis = learning.analyze_save(
        "Rust 取消安全",
        "# Rust 取消安全\n\n取消安全是 future 被 drop 后状态仍一致。",
    )
    assert analysis["related"]
    assert any(item["path"].startswith("02-Knowledge/") for item in analysis["related"])
    patch = learning.append_to_note(
        "02-Knowledge/Concepts/Rust-Async.md",
        "Rust 取消安全",
        "# Rust 取消安全\n\n补充内容。",
    )
    assert patch["target_path"] == "02-Knowledge/Concepts/Rust-Async.md"
    assert "## 知识文档：Rust 取消安全" in patch["content"]


def test_save_does_not_overwrite_existing_draft(isolated):
    from app.vault import atomic_write, dump_note, target_path

    base = learning._draft_path("Rust 取消安全")
    atomic_write(target_path(base), dump_note({"title": "旧草稿"}, "# 旧草稿\n"))
    first = learning.save_as_patch("Rust 取消安全", "# 新文档\n")
    assert first["target_path"] != base
    assert "-2.md" in first["target_path"]


def test_generate_interview_questions(isolated, monkeypatch):
    seed_demo()
    monkeypatch.setattr(learning, "provider_from_config", lambda config: InterviewProvider())
    result = asyncio.run(
        learning.generate("Rust 取消安全", mode="interview", config={"profile": {}})
    )
    assert result["questions"][0]["question"] == "什么是取消安全？"
    assert "## 1. 什么是取消安全？" in result["markdown"]


def test_review_stats_and_generation(isolated, monkeypatch):
    seed_demo()
    monkeypatch.setattr(review, "provider_from_config", lambda config: DocProvider())
    stats = review.stats(7)
    assert stats["feed_total"] >= 3
    result = asyncio.run(review.weekly_review(7, {"profile": {}}))
    assert result["markdown"]
    assert result["stats"]["feed_total"] >= 3


def test_graph_builds_wikilink_edges(isolated):
    atomic_write(
        target_path("02-Knowledge/Concepts/A.md"),
        dump_note({"title": "A", "tags": ["rust"]}, "# A\n\n参见 [[B]]。"),
    )
    atomic_write(
        target_path("02-Knowledge/Concepts/B.md"),
        dump_note({"title": "B", "tags": ["rust"]}, "# B\n\n内容。"),
    )
    data = graph.build_graph()
    assert data["stats"]["notes"] == 2
    assert any(edge["kind"] == "wiki" for edge in data["edges"])
    assert any(edge["kind"] == "tag" for edge in data["edges"])
