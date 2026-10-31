from __future__ import annotations

from pathlib import Path

from ..db import now_iso
from ..vault import atomic_write, dump_note, ensure_vault
from .feeds import _upsert_feed_item, update_feed
from .search import rebuild_search_index


def seed_demo() -> dict[str, int]:
    ensure_vault()
    items = [
        {
            "title": "Rust async cancellation safety",
            "url": "https://example.com/rust-async-cancellation",
            "canonical_url": "https://example.com/rust-async-cancellation",
            "summary": "A practical explanation of cancellation safety in async Rust.",
            "content": (
                "Cancellation safety describes what happens when a future is dropped before it completes. "
                "In Tokio, select! may cancel the losing branch, so any side effects before the await point "
                "must be safe to abandon. The article compares cancellation-safe and unsafe patterns, "
                "and shows how to structure tasks around owned state."
            ),
            "author": "Demo Author",
            "published_at": now_iso(),
            "tags": ["Rust", "async", "Tokio"],
            "source_type": "rss",
            "source_name": "Demo RSS",
        },
        {
            "title": "tokio-rs/tokio",
            "url": "https://github.com/tokio-rs/tokio",
            "canonical_url": "https://github.com/tokio-rs/tokio",
            "summary": "A runtime for writing reliable asynchronous applications with Rust.",
            "content": "Tokio is an asynchronous runtime for Rust, providing I/O, timers, scheduling, and synchronization primitives.",
            "author": "tokio-rs",
            "published_at": now_iso(),
            "tags": ["Rust", "async", "runtime"],
            "source_type": "github",
            "source_name": "GitHub Trending",
            "repo_full_name": "tokio-rs/tokio",
            "stars": 28000,
            "forks": 2600,
            "license": "MIT",
            "primary_language": "Rust",
        },
        {
            "title": "Local-first software and personal knowledge",
            "url": "https://example.com/local-first-knowledge",
            "canonical_url": "https://example.com/local-first-knowledge",
            "summary": "Why local-first data ownership matters for personal knowledge tools.",
            "content": (
                "Local-first software keeps the primary copy of data on the user's device. "
                "For a knowledge base, this means Markdown files remain readable without the app, "
                "while indexes and AI features are derived and rebuildable."
            ),
            "author": "Demo Author",
            "published_at": now_iso(),
            "tags": ["local-first", "PKM", "Markdown"],
            "source_type": "rss",
            "source_name": "Demo RSS",
        },
    ]
    ids: list[str] = []
    for item in items:
        feed_id, _ = _upsert_feed_item(item)
        ids.append(feed_id)
        update_feed(
            feed_id,
            summary_zh={
                "Rust async cancellation safety": "解释 Rust 异步取消安全：Future 被提前 drop 时，哪些副作用可以安全放弃，以及如何在 Tokio 的 select! 中组织任务。",
                "tokio-rs/tokio": "Tokio 是 Rust 的异步运行时，提供 I/O、定时器、任务调度和同步原语，适合构建高并发网络服务。",
                "Local-first software and personal knowledge": "讨论本地优先软件对个人知识库的意义：Markdown 是可迁移的事实层，索引与 AI 能力是可重建的派生层。",
            }[item["title"]],
            tags=item["tags"],
            translated=1,
        )

    note = Path("02-Knowledge/Concepts/Rust-Async.md")
    note_path = ensure_vault() / note
    if not note_path.exists():
        meta = {
            "id": "demo-rust-async",
            "type": "concept",
            "status": "published",
            "title": "Rust Async",
            "tags": ["Rust", "async", "Tokio"],
            "publish": False,
            "created_at": now_iso(),
        }
        body = """# Rust Async

## 核心概念

Rust 的异步模型围绕 `Future`、`Executor` 和 `Waker` 展开。`Future` 是惰性的状态机，只有被 executor 轮询时才会推进。

## 取消安全

当一个 future 在完成前被 drop，它可能停在任意 `.await` 点。取消安全要求：被取消后，不会留下不一致的共享状态或重复副作用。

## 与 [[Tokio]] 的关系

Tokio 提供 runtime、I/O driver、timer 和任务调度。`select!` 会取消未完成的分支，因此分支中的 future 需要具备取消安全性。

## 来源

- [Rust async cancellation safety](https://example.com/rust-async-cancellation)
"""
        atomic_write(note_path, dump_note(meta, body))

    tokio_note = Path("02-Knowledge/Concepts/Tokio.md")
    tokio_path = ensure_vault() / tokio_note
    if not tokio_path.exists():
        meta = {
            "id": "demo-tokio",
            "type": "concept",
            "status": "published",
            "title": "Tokio",
            "tags": ["Rust", "async", "runtime"],
            "publish": False,
            "created_at": now_iso(),
        }
        body = """# Tokio

## 它是什么

Tokio 是 Rust 的异步运行时，提供任务调度、I/O 驱动、定时器和同步原语。

## 与 [[Rust Async]] 的关系

`Future` 定义异步计算，Tokio 负责轮询和调度这些 future。`select!` 可以同时等待多个分支，并取消未完成的分支。

## 来源

- [tokio-rs/tokio](https://github.com/tokio-rs/tokio)
"""
        atomic_write(tokio_path, dump_note(meta, body))

    rebuild_search_index()
    return {"feed_items": len(ids), "notes": 2}
