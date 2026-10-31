from __future__ import annotations

from app.services.patches import create_patch, list_patches
from app.services.search import rebuild_search_index, search
from app.vault import atomic_write, dump_note, target_path


def test_natural_language_question_retrieves_local_note(isolated):
    atomic_write(
        target_path("02-Knowledge/Concepts/Rust-Async.md"),
        dump_note(
            {"title": "Rust Async", "type": "concept"},
            "# Rust Async\n\n取消安全要求 Future 被 drop 后不留下不一致状态。",
        ),
    )
    atomic_write(
        target_path("02-Knowledge/Concepts/Rust-Release.md"),
        dump_note(
            {"title": "Announcing Rust 1.99.1", "type": "source"},
            "# Rust 1.99.1\n\nRust 发布了一个新的点版本，修复编译器回归。",
        ),
    )
    rebuild_search_index()
    results = search("Rust async 的取消安全是什么？", limit=5)
    assert results
    assert any("Rust Async" in item["title"] for item in results)
    assert all("1.99.1" not in item["title"] for item in results)


def test_duplicate_patches_are_merged(isolated):
    first = create_patch(
        target_path="02-Knowledge/Concepts/Merged.md",
        patch_type="create_note",
        title="Merged",
        content="first",
        source_refs=[{"title": "a"}],
    )
    second = create_patch(
        target_path="02-Knowledge/Concepts/Merged.md",
        patch_type="create_note",
        title="Merged",
        content="second",
        source_refs=[{"title": "b"}],
    )
    assert first["id"] == second["id"]
    assert second["content"] == "second"
    assert len(list_patches()) == 1
