from __future__ import annotations

import asyncio

from app.services import targeted
from app.services.feeds import list_feed


def test_targeted_queries_use_aliases():
    assert targeted._query_for("数据库") == "database"
    assert targeted._query_for("C++") == "C++"
    assert targeted._devto_tag("C++") == "cpp"


def test_targeted_terms_cover_all_profile_groups():
    terms = targeted._target_terms(
        {
            "feed_filter_skills": ["C++", "Python", "网络编程"],
            "feed_filter_interests": ["数据库", "编译器", "网络编程"],
            "feed_filter_goals": ["系统设计", "分布式系统", "AI 工程化"],
        }
    )
    assert len(terms) == 6
    assert "C++" in terms
    assert "系统设计" in terms


def test_targeted_ingest_uses_profile_terms(isolated, monkeypatch):
    async def fake_github(query, *, sort="stars", limit=10, token="", client=None):
        assert "C++" in query
        return [
            {
                "repo_full_name": "example/cpp-project",
                "title": "example/cpp-project",
                "url": "https://github.com/example/cpp-project",
                "summary": "Modern C++ project",
                "content": "Modern C++ project",
                "tags": ["cpp"],
                "stars": 20,
            }
        ]

    async def fake_arxiv(query, *, limit=10, client=None):
        return []

    async def fake_devto(tag="", *, limit=10, client=None):
        return []

    monkeypatch.setattr(targeted, "search_github", fake_github)
    monkeypatch.setattr(targeted, "fetch_arxiv", fake_arxiv)
    monkeypatch.setattr(targeted, "fetch_devto", fake_devto)
    result = asyncio.run(
        targeted.ingest_targeted(
            {
                "feed_filter_skills": ["C++"],
                "feed_filter_interests": [],
                "feed_filter_goals": [],
            }
        )
    )
    assert result["new"] == 1
    assert result["terms"] == ["C++"]
    assert list_feed()[0]["title"] == "example/cpp-project"
    assert list_feed()[0]["source_name"] == "画像定向: C++"
