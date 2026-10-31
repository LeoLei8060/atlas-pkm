from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_empty_state_and_health(isolated):
    app = create_app()
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["ready"] is False

        state = client.get("/api/state").json()
        assert state["ready"] is False
        assert state["stats"]["feed"] == 0

        assert client.get("/").status_code == 200
        assert client.post("/api/ask", json={"question": "test"}).status_code == 400


def test_seed_and_wiki(isolated):
    app = create_app()
    with TestClient(app) as client:
        response = client.post("/api/dev/seed")
        assert response.status_code == 200
        assert response.json()["feed_items"] == 3

        feed = client.get("/api/feed").json()["items"]
        assert len(feed) == 3

        wiki = client.get("/wiki/")
        assert wiki.status_code == 200
        assert "知识库" in wiki.text

        notes = client.get("/api/notes").json()["items"]
        assert any(note["title"] == "Rust Async" for note in notes)

        search = client.get("/api/search", params={"q": "取消安全"})
        assert search.status_code == 200
        items = search.json()["items"]
        assert items
        assert "vector" not in items[0]


def test_settings_are_masked(isolated):
    app = create_app()
    with TestClient(app) as client:
        response = client.put(
            "/api/settings",
            json={
                "active_provider": "deepseek",
                "providers": {
                    "deepseek": {
                        "api_key": "d-secret",
                        "model": "deepseek-chat",
                        "base_url": "https://api.test/v1",
                    }
                },
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ready"] is True
        assert body["providers"]["deepseek"]["has_key"] is True
        assert body["providers"]["deepseek"]["api_key"] == ""

        state = client.get("/api/state").json()
        assert state["ready"] is True


def test_scheduler_settings_and_status(isolated):
    app = create_app()
    with TestClient(app) as client:
        status = client.get("/api/scheduler").json()
        assert status["enabled"] is True
        assert status["schedule_mode"] == "daily"
        assert status["daily_time"] == "06:00"

        response = client.put(
            "/api/settings",
            json={
                "auto_refresh_enabled": True,
                "schedule_mode": "interval",
                "daily_time": "07:30",
                "refresh_interval_minutes": 60,
                "auto_refresh_github": False,
                "rss_sources": ["https://example.com/feed.xml"],
            },
        )
        assert response.status_code == 200
        settings = response.json()
        assert settings["auto_refresh_enabled"] is True
        assert settings["schedule_mode"] == "interval"
        assert settings["daily_time"] == "07:30"
        assert settings["refresh_interval_minutes"] == 60
        assert settings["rss_sources"] == ["https://example.com/feed.xml"]

        status = client.get("/api/scheduler").json()
        assert status["enabled"] is True
        assert status["schedule_mode"] == "interval"
        assert status["daily_time"] == "07:30"
        assert status["interval_minutes"] == 60

        run = client.post("/api/scheduler/run")
        assert run.status_code == 200
        assert run.json().get("skipped") is True


def test_profile_and_feedback(isolated):
    app = create_app()
    with TestClient(app) as client:
        client.post("/api/dev/seed")
        item = client.get("/api/feed").json()["items"][0]
        updated = client.post(
            f"/api/feed/{item['id']}/feedback", json={"value": 1}
        )
        assert updated.status_code == 200
        assert updated.json()["feedback"] == 1

        response = client.put(
            "/api/settings",
            json={
                "profile": {
                    "target_role": "系统工程师",
                    "level": "中级",
                    "skills": ["Rust", "C++"],
                    "learning_goals": ["系统设计"],
                    "interests": ["数据库"],
                    "weekly_hours": 6,
                }
            },
        )
        assert response.status_code == 200
        profile = response.json()["profile"]
        assert profile["target_role"] == "系统工程师"
        assert profile["skills"] == ["Rust", "C++"]
        assert profile["weekly_hours"] == 6


def test_feed_filters_and_bulk_status(isolated):
    app = create_app()
    with TestClient(app) as client:
        client.post("/api/dev/seed")
        items = client.get("/api/feed").json()["items"]
        assert items
        query = items[0]["title"].split()[0]
        filtered = client.get("/api/feed", params={"q": query}).json()["items"]
        assert filtered
        assert all(query.lower() in (item["title"] + item["summary_zh"]).lower() for item in filtered)

        ids = [item["id"] for item in items[:2]]
        bulk = client.post(
            "/api/feed/bulk", json={"ids": ids, "action": "read"}
        )
        assert bulk.status_code == 200
        assert bulk.json()["updated"] == len(ids)
        read = client.get("/api/feed", params={"status": "read"}).json()["items"]
        assert {item["id"] for item in read} >= set(ids)


def test_feed_ignore_and_delete(isolated):
    app = create_app()
    with TestClient(app) as client:
        client.post("/api/dev/seed")
        items = client.get("/api/feed").json()["items"]
        target = items[0]
        client.post(
            f"/api/feed/{target['id']}/status", json={"status": "dismissed"}
        )
        visible = client.get("/api/feed").json()["items"]
        assert target["id"] not in {item["id"] for item in visible}
        ignored = client.get("/api/feed", params={"status": "dismissed"}).json()["items"]
        assert target["id"] in {item["id"] for item in ignored}

        deleted = client.delete(f"/api/feed/{target['id']}")
        assert deleted.status_code == 200
        assert target["id"] not in {
            item["id"] for item in client.get("/api/feed", params={"status": "dismissed"}).json()["items"]
        }


def test_feed_pagination(isolated):
    app = create_app()
    with TestClient(app) as client:
        client.post("/api/dev/seed")
        first = client.get("/api/feed", params={"limit": 2, "offset": 0}).json()
        second = client.get("/api/feed", params={"limit": 2, "offset": 2}).json()
        assert first["total"] == second["total"]
        assert first["total"] >= 3
        assert first["has_more"] is True
        assert {item["id"] for item in first["items"]}.isdisjoint(
            {item["id"] for item in second["items"]}
        )
        assert first["offset"] == 0
        assert second["offset"] == 2


def test_custom_provider_lifecycle(isolated):
    app = create_app()
    with TestClient(app) as client:
        payload = {
            "id": "my-gateway",
            "label": "My Gateway",
            "protocol": "openai-compatible",
            "base_url": "https://gateway.example.com/v1",
            "model": "gpt-4o-mini",
            "api_key": "test-key",
        }
        created = client.post("/api/providers/custom", json=payload)
        assert created.status_code == 200
        provider = created.json()["providers"]["my-gateway"]
        assert provider["kind"] == "third_party"
        assert provider["protocol"] == "openai-compatible"
        assert provider["has_key"] is True
        assert provider["api_key"] == ""

        duplicate = client.post("/api/providers/custom", json=payload)
        assert duplicate.status_code == 409

        updated = client.put(
            "/api/settings",
            json={
                "active_provider": "my-gateway",
                "providers": {
                    "my-gateway": {
                        "label": "Renamed Gateway",
                        "protocol": "anthropic-compatible",
                    }
                },
            },
        )
        assert updated.status_code == 200
        body = updated.json()
        assert body["active_provider"] == "my-gateway"
        assert body["providers"]["my-gateway"]["label"] == "Renamed Gateway"
        assert body["providers"]["my-gateway"]["protocol"] == "anthropic-compatible"

        removed = client.delete("/api/providers/custom/my-gateway")
        assert removed.status_code == 200
        assert "my-gateway" not in removed.json()["providers"]
        assert removed.json()["active_provider"] == "deepseek"


def test_clear_official_key_falls_back(isolated):
    app = create_app()
    with TestClient(app) as client:
        response = client.put(
            "/api/settings",
            json={
                "active_provider": "openai",
                "providers": {"openai": {"api_key": "test-key", "model": "gpt-4o-mini"}},
            },
        )
        assert response.status_code == 200
        assert response.json()["active_provider"] == "openai"

        cleared = client.put(
            "/api/settings",
            json={"providers": {"openai": {"clear_api_key": True}}},
        )
        assert cleared.status_code == 200
        body = cleared.json()
        assert body["providers"]["openai"]["has_key"] is False
        assert body["active_provider"] == "deepseek"


def test_sources_crud(isolated):
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/api/sources").json()["items"] == []

        created = client.post(
            "/api/sources",
            json={"url": "https://example.com/feed.xml", "name": "Example"},
        )
        assert created.status_code == 200
        source = created.json()
        assert source["enabled"] is True
        assert source["name"] == "Example"
        assert source["url"] == "https://example.com/feed.xml"
        assert source["source_group"] == "other"
        assert source["adapter"] == "rss"

        disabled = client.patch(
            f"/api/sources/{source['id']}", json={"enabled": False}
        )
        assert disabled.status_code == 200
        assert disabled.json()["enabled"] is False

        renamed = client.patch(
            f"/api/sources/{source['id']}", json={"name": "Renamed"}
        )
        assert renamed.json()["name"] == "Renamed"

        removed = client.delete(f"/api/sources/{source['id']}")
        assert removed.status_code == 200
        assert client.get("/api/sources").json()["items"] == []

        bad = client.post("/api/sources", json={"url": "ftp://example.com/feed"})
        assert bad.status_code == 400


def test_source_groups_and_csdn_discovery(isolated):
    app = create_app()
    with TestClient(app) as client:
        github = client.post(
            "/api/sources",
            json={
                "url": "https://github.com/search?q=C%2B%2B",
                "name": "C++",
                "group": "github",
                "adapter": "github_search",
                "config": {"query": "C++"},
            },
        )
        assert github.status_code == 200
        assert github.json()["source_group"] == "github"
        assert github.json()["adapter"] == "github_search"
        assert github.json()["config"]["query"] == "C++"

        other = client.get("/api/sources", params={"group": "other"}).json()["items"]
        assert other == []

        csdn = client.post(
            "/api/sources/discover",
            json={
                "url": "https://blog.csdn.net/example_user",
                "name": "",
                "group": "other",
                "adapter": "rss",
            },
        )
        assert csdn.status_code == 200
        draft = csdn.json()
        assert draft["adapter"] == "csdn"
        assert draft["config"]["user"] == "example_user"
        assert "example_user/rss/list" in draft["config"]["rss_url"]


def test_github_favorite_appears_in_collections(isolated):
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/github/favorite",
            json={
                "item": {
                    "repo_full_name": "example/cpp",
                    "url": "https://github.com/example/cpp",
                    "summary": "C++ project",
                    "stars": 42,
                    "forks": 3,
                    "license": "MIT",
                    "primary_language": "C++",
                    "topics": ["cpp"],
                }
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "saved"
        collections = client.get("/api/collections").json()["items"]
        assert collections[0]["source_type"] == "github"
        assert collections[0]["repo_full_name"] == "example/cpp"


def test_source_catalog(isolated):
    app = create_app()
    with TestClient(app) as client:
        catalog = client.get("/api/sources/catalog")
        assert catalog.status_code == 200
        items = catalog.json()["items"]
        assert any(item["id"] == "cppstories" for item in items)
        assert any(item["priority"] for item in items)

        imported = client.post(
            "/api/sources/catalog",
            json={"ids": ["cppstories", "lwn"]},
        )
        assert imported.status_code == 200
        assert len(imported.json()["items"]) == 2
        sources = client.get("/api/sources").json()["items"]
        assert {source["name"] for source in sources} >= {"C++ Stories", "LWN.net"}


def test_profile_and_feed_window_settings(isolated):
    app = create_app()
    with TestClient(app) as client:
        response = client.put(
            "/api/settings",
            json={
                "profile": {
                    "target_role": "C++ 开发工程师",
                    "is_technical": True,
                    "languages": ["C++", "Rust"],
                    "skills": ["C++"],
                    "learning_goals": ["系统设计"],
                },
                "feed_window_days": 7,
            },
        )
        assert response.status_code == 200
        settings = client.get("/api/settings").json()
        assert settings["profile"]["is_technical"] is True
        assert settings["profile"]["languages"] == ["C++", "Rust"]
        assert settings["feed_window_days"] == 7
        before_vault = settings["vault_path"]
        client.put("/api/settings", json={"vault_path": "C:/somewhere/else"})
        assert client.get("/api/settings").json()["vault_path"] == before_vault


def test_embedding_status(isolated):
    app = create_app()
    with TestClient(app) as client:
        status = client.get("/api/embeddings/status").json()
        assert status["provider"] == "local"
        assert status["indexed_documents"] == status["total_documents"]
        assert status["external"] is False
