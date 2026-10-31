from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.feeds import (
    filter_feed_items,
    filter_recent_items,
    selected_feed_filters,
    source_matches_filter,
    source_type_for,
)


def test_profile_filter_keeps_matching_items():
    config = {
        "feed_filter_skills": ["Rust"],
        "feed_filter_interests": ["数据库"],
        "feed_filter_goals": [],
    }
    items = [
        {"title": "Rust async runtime", "summary": "", "content": "", "tags": []},
        {"title": "Cooking with cast iron", "summary": "food", "content": "", "tags": []},
        {"title": "New database engine", "summary": "storage", "content": "", "tags": []},
    ]
    kept, dropped = filter_feed_items(items, config)
    assert [item["title"] for item in kept] == ["Rust async runtime", "New database engine"]
    assert dropped == 1


def test_cpp_alias_matches_cpp_text():
    kept, dropped = filter_feed_items(
        [{"title": "Modern cpp patterns", "tags": []}],
        {"feed_filter_skills": ["C++"]},
    )
    assert len(kept) == 1
    assert dropped == 0


def test_source_type_filter():
    assert source_type_for({"adapter": "github_search"}) == "github"
    assert source_type_for({"adapter": "csdn"}) == "csdn"
    assert source_matches_filter({"adapter": "rss"}, [])
    assert source_matches_filter({"adapter": "csdn"}, ["csdn", "qt"])
    assert not source_matches_filter({"adapter": "rss"}, ["csdn"])


def test_recent_window_filters_articles_but_keeps_github_and_unknown_dates():
    now = datetime.now(timezone.utc)
    items = [
        {"title": "fresh", "published_at": (now - timedelta(days=2)).isoformat()},
        {"title": "old", "published_at": (now - timedelta(days=4)).isoformat()},
        {"title": "github", "source_type": "github", "published_at": "2000-01-01T00:00:00+00:00"},
        {"title": "unknown", "published_at": ""},
    ]
    kept, dropped = filter_recent_items(items, {"feed_window_days": 3})
    assert [item["title"] for item in kept] == ["fresh", "github", "unknown"]
    assert dropped == 1


def test_no_selected_filters_means_all_items():
    items = [{"title": "anything", "tags": []}]
    kept, dropped = filter_feed_items(items, {})
    assert kept == items
    assert dropped == 0
    assert selected_feed_filters({}) == []
