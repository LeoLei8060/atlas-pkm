from __future__ import annotations

import asyncio

from app.providers.base import ChatResult
from app.services.agent import expand_query
from app.services.search import rebuild_search_index, search
from app.vault import atomic_write, dump_note, target_path
from app.vector import cosine, vectorize


def test_vector_similarity(isolated):
    a = vectorize("Rust 异步取消安全 Future drop")
    b = vectorize("取消安全要求 Future 被取消后不留下不一致状态")
    c = vectorize("Python 数据分析与可视化")
    assert cosine(a, b) > cosine(a, c)


def test_hybrid_search_returns_vector_match(isolated):
    atomic_write(
        target_path("02-Knowledge/Concepts/Rust-Async.md"),
        dump_note(
            {"title": "Rust Async", "type": "concept"},
            "# Rust Async\n\n取消安全要求 Future 在 await 点被 drop 后不留下不一致状态。",
        ),
    )
    atomic_write(
        target_path("02-Knowledge/Concepts/Python.md"),
        dump_note(
            {"title": "Python", "type": "concept"},
            "# Python\n\n数据分析与可视化。",
        ),
    )
    rebuild_search_index()
    results = search("Future 被取消后状态不一致", limit=5)
    assert results
    assert results[0]["title"] == "Rust Async"
    assert "vector" not in results[0]


def test_expand_query_parses_json():
    class FakeProvider:
        async def chat(self, *args, **kwargs):
            return ChatResult(
                text='["取消安全", "cancellation safety", "Future drop"]',
                provider="fake",
                model="fake",
            )

    terms = asyncio.run(expand_query("取消安全是什么", FakeProvider()))
    assert terms == ["取消安全", "cancellation safety", "Future drop"]
