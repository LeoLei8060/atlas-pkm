from __future__ import annotations

import json
import os

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.usage_accounts import (
    _deepseek_keys_from_payload,
    _normalize_deepseek,
    _normalize_newapi,
)


def test_usage_account_is_masked_and_deletable(isolated):
    app = create_app()
    with TestClient(app) as client:
        created = client.post(
            "/api/usage/accounts",
            json={
                "name": "米醋中转站",
                "kind": "newapi",
                "base_url": "https://www.micuapi.ai",
                "user_id": "42",
                "access_token": "secret-access-token",
            },
        )
        assert created.status_code == 200
        account = created.json()
        assert "secret-access-token" not in str(account)
        assert account["has_access_token"] is True

        items = client.get("/api/usage/accounts").json()["items"]
        assert items[0]["id"] == "米醋中转站" or items[0]["name"] == "米醋中转站"
        assert "secret-access-token" not in str(items)
        config_text = (isolated / "data" / "config.json").read_text(encoding="utf-8")
        assert "secret-access-token" not in config_text
        if os.name == "nt":
            assert "dpapi:" in config_text

        deleted = client.delete(f"/api/usage/accounts/{items[0]['id']}")
        assert deleted.status_code == 200
        assert client.get("/api/usage/accounts").json()["items"] == []


def test_newapi_usage_normalization():
    status = {"quota_per_unit": 500000, "custom_currency_symbol": "¥"}
    user = {"quota": 250000, "used_quota": 1500000}
    today_stat = {"quota": 50000, "rpm": 2, "tpm": 100}
    rows = [
        {
            "created_at": 1793630000,
            "model_name": "deepseek-flash",
            "quota": 50000,
            "token_used": 1200,
            "count": 3,
        }
    ]
    result = _normalize_newapi({"name": "micu"}, status, user, today_stat, rows)
    assert result["balance"]["remaining"] == 0.5
    assert result["balance"]["used"] == 3.0
    assert result["models"][0]["model"] == "deepseek-flash"


def test_deepseek_by_api_key_series_parser():
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date().isoformat()
    balance = {
        "is_available": True,
        "balance_infos": [
            {"currency": "CNY", "total_balance": "10", "granted_balance": "0", "topped_up_balance": "10"}
        ],
    }
    usage = {
        "code": 0,
        "data": {
            "biz_code": 0,
            "biz_data": json.dumps(
                {
                    "series": [
                        {
                            "model": "deepseek-chat",
                            "buckets": [
                                {
                                    "time": f"{today}T00:00:00Z",
                                    "usage": [
                                        {"type": "PROMPT_CACHE_HIT_TOKEN", "amount": "10"},
                                        {"type": "PROMPT_CACHE_MISS_TOKEN", "amount": "20"},
                                        {"type": "RESPONSE_TOKEN", "amount": "5"},
                                        {"type": "REQUEST", "amount": "2"},
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ),
        },
    }
    result = _normalize_deepseek({"name": "deepseek"}, balance, usage)
    assert result["period"]["tokens"] == 35
    assert result["today"]["tokens"] == 35
    assert result["today"]["requests"] == 2
    assert result["period"]["cached_tokens"] == 10
    assert result["models"][0]["model"] == "deepseek-chat"


def test_deepseek_by_key_usage_parser():
    payload = {
        "data": {
            "biz_data": [
                {
                    "api_key_name": "default",
                    "usage": [
                        {"type": "PROMPT_CACHE_MISS_TOKEN", "amount": "100"},
                        {"type": "RESPONSE_TOKEN", "amount": "50"},
                        {"type": "REQUEST", "amount": "2"},
                    ],
                }
            ]
        }
    }
    keys = _deepseek_keys_from_payload(payload)
    assert keys[0]["name"] == "default"
    assert keys[0]["period_tokens"] == 150
    assert keys[0]["requests"] == 2


def test_deepseek_usage_normalization():
    balance = {
        "is_available": True,
        "balance_infos": [
            {
                "currency": "CNY",
                "total_balance": "10.5",
                "granted_balance": "0",
                "topped_up_balance": "10.5",
            }
        ],
    }
    usage = {
        "code": 0,
        "data": {
            "biz_code": 0,
            "biz_data": {
                "total": [],
                "days": [
                    {
                        "date": "2026-11-02",
                        "data": [
                            {
                                "model": "deepseek-chat",
                                "usage": [
                                    {"type": "PROMPT_CACHE_MISS_TOKEN", "amount": "100"},
                                    {"type": "RESPONSE_TOKEN", "amount": "50"},
                                    {"type": "REQUEST", "amount": "2"},
                                ],
                            }
                        ],
                    }
                ],
            },
        },
    }
    result = _normalize_deepseek({"name": "deepseek"}, balance, usage)
    assert result["balance"]["remaining"] == 10.5
    assert result["models"][0]["tokens"] == 150
    assert result["models"][0]["requests"] == 2
