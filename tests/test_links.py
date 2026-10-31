from __future__ import annotations

import asyncio

from app.services import links
from app.services.patches import apply_patch
from app.vault import atomic_write, dump_note, target_path


def _notes() -> None:
    atomic_write(
        target_path("02-Knowledge/Concepts/A.md"),
        dump_note({"title": "A", "tags": ["rust"]}, "# A\n\nRust async. [1]"),
    )
    atomic_write(
        target_path("02-Knowledge/Concepts/B.md"),
        dump_note({"title": "B", "tags": ["rust"]}, "# B\n\nRust Tokio. [1]"),
    )


def test_suggest_all_creates_patches(isolated):
    _notes()
    result = asyncio.run(links.suggest_all(config={}, max_notes=5))
    assert result["patches"] >= 1
    assert result["items"][0]["patch"]


def test_suggest_links_creates_patch(isolated):
    _notes()
    result = asyncio.run(
        links.suggest_links("02-Knowledge/Concepts/A.md", config={}, limit=3)
    )
    assert result["suggestions"]
    assert result["patch"]["target_path"] == "02-Knowledge/Concepts/A.md"
    assert "[[B]]" in result["patch"]["content"]
    applied = apply_patch(result["patch"]["id"])
    assert applied["status"] == "applied"
    text = target_path("02-Knowledge/Concepts/A.md").read_text(encoding="utf-8")
    assert "## 相关笔记" in text
    assert "[[B]]" in text
