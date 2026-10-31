from __future__ import annotations

import asyncio

import pytest

from app.services import github_rankings


def test_meta_lists_stacks_and_metrics():
    data = github_rankings.meta()
    ids = {stack["id"] for stack in data["stacks"]}
    assert {"cpp", "ai", "c", "python", "go", "rust", "skill", "typescript", "network"} <= ids
    metrics = {metric["id"] for metric in data["metrics"]}
    assert {"new_today", "new_week", "new_month", "stars", "forks", "quality"} == metrics
    assert "Star" in data["notice"]


def test_ranking_query_and_cache(isolated, monkeypatch):
    calls = []

    async def fake_search(query, *, sort="stars", limit=10, token="", client=None):
        calls.append({"query": query, "sort": sort, "limit": limit})
        return [
            {
                "repo_full_name": "example/repo",
                "title": "example/repo",
                "url": "https://github.com/example/repo",
                "summary": "demo",
                "stars": 1200,
                "forks": 80,
                "primary_language": "Rust",
                "topics": ["cli"],
                "published_at": "2026-10-01T00:00:00Z",
            }
        ]

    monkeypatch.setattr(github_rankings, "search_github", fake_search)

    first = asyncio.run(github_rankings.get_ranking("rust", "stars", limit=10))
    assert first["cached"] is False
    assert first["items"][0]["repo_full_name"] == "example/repo"
    assert calls[0]["sort"] == "stars"
    assert "language:Rust" in calls[0]["query"]

    second = asyncio.run(github_rankings.get_ranking("rust", "stars", limit=10))
    assert second["cached"] is True
    assert len(calls) == 1

    refreshed = asyncio.run(
        github_rankings.get_ranking("rust", "stars", limit=10, refresh=True)
    )
    assert refreshed["cached"] is False
    assert len(calls) == 2


def test_star_gain_uses_daily_snapshots(isolated):
    base = {
        "repo_full_name": "example/growing",
        "title": "example/growing",
        "url": "https://github.com/example/growing",
        "summary": "demo",
        "stars": 1000,
        "forks": 10,
        "primary_language": "C++",
        "topics": [],
        "published_at": "2026-10-01T00:00:00Z",
    }
    github_rankings._save_snapshots(
        "cpp", [{**base, "stars": 1000}], github_rankings._snapshot_date(1)
    )
    github_rankings._save_snapshots(
        "cpp", [{**base, "stars": 1250}], github_rankings._snapshot_date(0)
    )
    gains = github_rankings._gain_ranking("cpp", 1, 10)
    assert gains[0]["repo_full_name"] == "example/growing"
    assert gains[0]["star_gain"] == 250
    assert gains[0]["star_baseline"] == 1000


def test_star_gain_first_snapshot_has_notice(isolated, monkeypatch):
    calls = []

    async def fake_search(query, *, sort="stars", limit=10, token="", client=None):
        calls.append(query)
        return [
            {
                "repo_full_name": "example/new",
                "title": "example/new",
                "url": "https://github.com/example/new",
                "summary": "demo",
                "stars": 500,
                "forks": 1,
            }
        ]

    monkeypatch.setattr(github_rankings, "search_github", fake_search)
    result = asyncio.run(github_rankings.get_ranking("cpp", "new_today"))
    assert "language:C++" in calls[0]
    assert "created:>" not in calls[0]
    assert result["items"] == []
    assert "两天的快照" in result["notice"]


def test_unknown_stack_or_metric(isolated):
    with pytest.raises(github_rankings.RankingError):
        asyncio.run(github_rankings.get_ranking("unknown", "stars"))
