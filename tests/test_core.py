from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.config import DEFAULT_CONFIG, load_config, masked_config, save_config
from app.providers.base import ProviderNotConfigured
from app.providers.openai import DeepSeekProvider
from app.services.feeds import parse_feed
from app.services.patches import apply_patch, create_patch, list_patches, reject_patch
from app.services.search import rebuild_search_index, search
from app.services.demo import seed_demo
from app.vault import atomic_write, dump_note, parse_frontmatter, scan_notes, target_path


RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Demo</title>
<item>
  <title>Rust async cancellation</title>
  <link>https://example.com/a?utm_source=x</link>
  <description><![CDATA[<p>Cancellation safety in async Rust.</p>]]></description>
  <pubDate>Wed, 28 Oct 2026 10:00:00 GMT</pubDate>
  <category>Rust</category>
</item>
</channel></rss>"""


def test_masked_config_hides_keys(isolated):
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    config["vault_path"] = str(isolated / "vault")
    config["providers"]["deepseek"]["api_key"] = "d-secret"
    save_config(config)
    loaded = load_config()
    masked = masked_config(loaded)
    assert masked["ready"] is True
    assert masked["providers"]["deepseek"]["has_key"] is True
    assert masked["providers"]["deepseek"]["api_key"] == ""


def test_vault_frontmatter_roundtrip(isolated):
    rel = "02-Knowledge/Concepts/Test.md"
    path = target_path(rel)
    text = dump_note({"title": "测试", "type": "concept"}, "# 正文\n\n内容")
    atomic_write(path, text)
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    assert meta["title"] == "测试"
    assert body.strip() == "# 正文\n\n内容"
    notes = scan_notes()
    assert any(note["path"] == rel for note in notes)


def test_search_chinese_and_fallback(isolated):
    for title, body in [
        ("Rust Async", "取消安全要求 Future 被 drop 后不留下不一致状态。"),
        ("Python", "数据分析与可视化。"),
    ]:
        rel = f"02-Knowledge/Concepts/{title.replace(' ', '-')}.md"
        atomic_write(target_path(rel), dump_note({"title": title}, f"# {title}\n\n{body}"))
    rebuild_search_index()
    results = search("取消安全", limit=5)
    assert results
    assert any("Rust" in item["title"] for item in results)


def test_patch_create_apply_reject(isolated):
    patch = create_patch(
        target_path="02-Knowledge/Concepts/PatchTarget.md",
        patch_type="create_note",
        title="补丁目标",
        content="这是 AI 补充。",
        source_refs=[{"title": "source"}],
    )
    assert patch["status"] == "proposed"
    assert list_patches()
    applied = apply_patch(patch["id"])
    assert applied["status"] == "applied"
    text = target_path("02-Knowledge/Concepts/PatchTarget.md").read_text(encoding="utf-8")
    assert "这是 AI 补充。" in text
    assert f"<!-- ai:begin id={patch['id']} -->" in text

    second = create_patch(
        target_path="02-Knowledge/Concepts/No.md",
        patch_type="create_note",
        title="拒绝",
        content="不要写入",
        source_refs=[],
    )
    rejected = reject_patch(second["id"])
    assert rejected["status"] == "rejected"
    assert not target_path("02-Knowledge/Concepts/No.md").exists()


def test_parse_rss():
    items = parse_feed(RSS)
    assert len(items) == 1
    assert items[0]["title"] == "Rust async cancellation"
    assert items[0]["canonical_url"] == "https://example.com/a"
    assert "Cancellation safety" in items[0]["summary"]
    assert items[0]["tags"] == ["Rust"]


def test_deepseek_uses_openai_shape(isolated):
    assert DeepSeekProvider.default_base_url == "https://api.deepseek.com/v1"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = DeepSeekProvider(
        {"api_key": "d-test", "model": "deepseek-chat", "base_url": "https://api.test/v1"},
        client=client,
    )
    assert asyncio.run(provider.chat([{"role": "user", "content": "hi"}])).text == "OK"


def test_provider_requires_key(isolated):
    provider = DeepSeekProvider({"api_key": "", "model": "deepseek-chat"})
    with pytest.raises(ProviderNotConfigured):
        asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))


def test_seed_demo(isolated):
    result = seed_demo()
    assert result["feed_items"] == 3
    assert target_path("02-Knowledge/Concepts/Rust-Async.md").exists()
    assert search("取消安全", limit=5)
