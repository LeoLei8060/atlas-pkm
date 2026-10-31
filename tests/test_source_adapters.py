from __future__ import annotations

import asyncio

from app.services import source_adapters
from app.services.feeds import add_source, get_source, list_feed


def test_csdn_source_uses_author_feed(isolated, monkeypatch):
    source = add_source(
        url="https://blog.csdn.net/example_user?type=blog",
        name="CSDN",
        source_group="other",
        adapter="csdn",
    )
    loaded = get_source(source["id"])

    async def fake_rss(url, client=None):
        assert "example_user/rss/list" in url
        return [
            {
                "title": "Qt6 教程",
                "url": "https://blog.csdn.net/example_user/article/details/1",
                "summary": "Qt",
                "content": "Qt",
                "tags": ["Qt"],
            }
        ]

    monkeypatch.setattr(source_adapters, "fetch_rss", fake_rss)
    result = asyncio.run(source_adapters.fetch_source(loaded, {}))
    assert result["new"] == 1
    assert list_feed()[0]["source_type"] == "csdn"


def test_github_search_source_fetches_items(isolated, monkeypatch):
    source = add_source(
        url="https://github.com/search?q=C%2B%2B",
        name="C++",
        source_group="github",
        adapter="github_search",
        config={"query": "C++"},
    )
    loaded = get_source(source["id"])

    async def fake_search(query, *, sort="stars", limit=10, token="", client=None):
        assert "C++" in query
        return [
            {
                "repo_full_name": "example/cpp",
                "title": "example/cpp",
                "url": "https://github.com/example/cpp",
                "summary": "C++ project",
                "content": "C++ project",
                "tags": ["cpp"],
                "stars": 42,
            }
        ]

    monkeypatch.setattr(source_adapters, "search_github", fake_search)
    result = asyncio.run(source_adapters.fetch_source(loaded, {}))
    assert result["new"] == 1
    assert list_feed()[0]["title"] == "example/cpp"
    assert list_feed()[0]["source_name"] == "C++"
    assert get_source(source["id"])["last_status"] == "ok"
