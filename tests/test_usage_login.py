from __future__ import annotations

import json

from http.cookies import SimpleCookie

from app.usage_login import (
    _extract_deepseek,
    _extract_newapi,
    _login_url,
    _serialize_cookies,
)


class FakeWindow:
    def __init__(self, payload):
        self.payload = payload

    def evaluate_js(self, _script):
        return json.dumps(self.payload)


def test_extract_newapi_credentials():
    window = FakeWindow(
        {
            "self": {"data": {"id": 42, "username": "tester"}},
            "token": {"data": {"token": "system-token"}},
        }
    )
    result = _extract_newapi(window)
    assert result == {"user_id": "42", "access_token": "system-token"}


def test_extract_deepseek_token():
    window = FakeWindow({"values": {"userToken": "platform-token"}})
    assert _extract_deepseek(window) == {"platform_token": "platform-token"}


def test_serialize_pywebview_simple_cookies():
    cookie = SimpleCookie()
    cookie["session"] = "abc123"
    assert _serialize_cookies([cookie]) == [{"name": "session", "value": "abc123"}]
    assert _serialize_cookies([{"name": "uid", "value": "42"}]) == [
        {"name": "uid", "value": "42"}
    ]


def test_login_urls_strip_v1_for_newapi():
    assert _login_url("newapi", "https://www.micuapi.ai/v1") == "https://www.micuapi.ai/login"
    assert _login_url("deepseek", "") == "https://platform.deepseek.com/sign_in"
