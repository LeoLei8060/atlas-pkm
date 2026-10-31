from __future__ import annotations

import asyncio
import json

from app.providers.base import ChatResult
from app.services import profile_learning
from app.services.demo import seed_demo
from app.services.feeds import list_feed, update_feed


class FakeProvider:
    name = "fake"
    model = "fake"

    async def chat(self, *args, **kwargs):
        payload = {
            "skills_add": ["分布式系统"],
            "interests_add": ["数据库"],
            "learning_goals_add": ["系统设计"],
            "interests_remove": [],
            "summary": "反馈显示用户更关注系统设计。",
        }
        return ChatResult(json.dumps(payload, ensure_ascii=False), "fake", "fake")


def test_suggest_profile_requires_feedback(isolated):
    seed_demo()
    try:
        asyncio.run(profile_learning.suggest_profile({"profile": {}}))
    except ValueError as exc:
        assert "反馈" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_suggest_and_apply_profile(isolated, monkeypatch):
    seed_demo()
    item = list_feed()[0]
    update_feed(item["id"], feedback=1)
    monkeypatch.setattr(
        profile_learning, "provider_from_config", lambda config: FakeProvider()
    )
    config = {
        "profile": {
            "target_role": "系统工程师",
            "skills": ["Rust"],
            "interests": ["Rust"],
            "learning_goals": [],
        }
    }
    result = asyncio.run(profile_learning.suggest_profile(config))
    assert result["suggestions"]["skills_add"] == ["分布式系统"]
    profile = profile_learning.apply_profile_suggestions(
        result["suggestions"], config
    )
    assert "分布式系统" in profile["skills"]
    assert "数据库" in profile["interests"]
    assert "系统设计" in profile["learning_goals"]
