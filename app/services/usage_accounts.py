from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timedelta
from typing import Any

import httpx

from ..config import load_config, save_config
from ..providers.base import BaseProvider
from .secret_store import protect, protect_json, unprotect, unprotect_json

CACHE_TTL = 300
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_key_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_key_cooldown: dict[str, float] = {}

DEEPSEEK_BALANCE = "https://api.deepseek.com/user/balance"
DEEPSEEK_USAGE = "https://platform.deepseek.com/api/v0/usage/{kind}"
DEEPSEEK_SUMMARY = "https://platform.deepseek.com/api/v0/users/get_user_summary"


def _account_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if slug:
        return slug
    return "account-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]


def _client(base_url: str) -> httpx.AsyncClient:
    proxy = BaseProvider({"base_url": base_url}).proxy_url()
    return httpx.AsyncClient(
        timeout=httpx.Timeout(25.0, connect=10.0),
        trust_env=False,
        proxy=proxy,
    )


def _cookie_header(account: dict[str, Any]) -> str:
    cookies = unprotect_json(str(account.get("session_cookies") or ""), [])
    if not isinstance(cookies, list):
        return ""
    return "; ".join(
        f"{item.get('name')}={item.get('value')}"
        for item in cookies
        if isinstance(item, dict) and item.get("name")
    )


def _headers(account: dict[str, Any]) -> dict[str, str]:
    if account.get("kind") == "newapi":
        headers = {
            "Authorization": unprotect(str(account.get("access_token") or "")),
            "New-Api-User": str(account.get("user_id") or ""),
            "Accept": "application/json",
        }
        if not headers["Authorization"]:
            cookies = _cookie_header(account)
            if cookies:
                headers["Cookie"] = cookies
        return headers
    token = unprotect(str(account.get("platform_token") or "")) or unprotect(
        str(account.get("api_key") or "")
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "x-client-platform": "web",
    }
    cookies = _cookie_header(account)
    if cookies:
        headers["Cookie"] = cookies
    return headers


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _money(quota: Any, quota_per_unit: float) -> float:
    if not quota_per_unit:
        return 0.0
    return round(_number(quota) / quota_per_unit, 4)


def _day(value: Any) -> str:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value).date().isoformat()
    text = str(value or "")
    return text[:10]


def _newapi_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        rows = data.get("items") or data.get("data") or []
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _normalize_newapi(
    account: dict[str, Any],
    status: dict[str, Any],
    user: dict[str, Any],
    today_stat: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    qpu = _number(status.get("quota_per_unit")) or 500000.0
    symbol = str(status.get("custom_currency_symbol") or "¥")
    today = datetime.now().date().isoformat()
    models: dict[str, dict[str, Any]] = {}
    daily: dict[str, dict[str, Any]] = {}
    period_tokens = 0
    period_requests = 0
    today_tokens = 0
    today_requests = 0
    for row in rows:
        date = _day(row.get("created_at") or row.get("date"))
        model = str(row.get("model_name") or row.get("model") or "未知模型")
        tokens = int(_number(row.get("token_used") or row.get("tokens")))
        count = int(_number(row.get("count") or row.get("requests")))
        model_item = models.setdefault(model, {"model": model, "tokens": 0, "requests": 0})
        model_item["tokens"] += tokens
        model_item["requests"] += count
        day_item = daily.setdefault(date, {"date": date, "tokens": 0, "requests": 0})
        day_item["tokens"] += tokens
        day_item["requests"] += count
        period_tokens += tokens
        period_requests += count
        if date == today:
            today_tokens += tokens
            today_requests += count
    if not today_requests:
        today_requests = int(_number(today_stat.get("request_count")))
    quota_today = _number(today_stat.get("quota"))
    return {
        "balance": {
            "remaining": _money(user.get("quota"), qpu),
            "used": _money(user.get("used_quota"), qpu),
            "currency": symbol,
            "quota_per_unit": qpu,
        },
        "today": {
            "tokens": today_tokens,
            "requests": today_requests,
            "cost": round(quota_today / qpu, 4),
        },
        "period": {
            "days": 30,
            "label": "近 30 天",
            "tokens": period_tokens,
            "requests": period_requests,
        },
        "models": sorted(models.values(), key=lambda item: item["tokens"], reverse=True),
        "daily": sorted(daily.values(), key=lambda item: item["date"]),
        "note": "",
    }


def _deepseek_usage_rows(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    data = payload.get("data") or {}
    biz = data.get("biz_data") or {}
    days = biz.get("days") if isinstance(biz, dict) else None
    totals = biz.get("total") if isinstance(biz, dict) else None
    rows: list[dict[str, Any]] = []
    for day in days or []:
        if not isinstance(day, dict):
            continue
        date = str(day.get("date") or "")[:10]
        for model in day.get("data") or []:
            if not isinstance(model, dict):
                continue
            name = str(model.get("model") or "未知模型")
            tokens = 0
            requests = 0
            prompt_tokens = 0
            completion_tokens = 0
            cached_tokens = 0
            for item in model.get("usage") or []:
                if not isinstance(item, dict):
                    continue
                value = int(_number(item.get("amount")))
                kind = str(item.get("type") or "").upper()
                if kind == "REQUEST":
                    requests += value
                else:
                    tokens += value
                    if "CACHE_HIT" in kind:
                        cached_tokens += value
                        prompt_tokens += value
                    elif "PROMPT" in kind:
                        prompt_tokens += value
                    elif "RESPONSE" in kind or "COMPLETION" in kind:
                        completion_tokens += value
            if tokens or requests:
                rows.append(
                    {
                        "date": date,
                        "model": name,
                        "tokens": tokens,
                        "requests": requests,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "cached_tokens": cached_tokens,
                    }
                )
    return rows, list(totals or []), str(payload.get("currency") or "CNY")


def _normalize_deepseek(
    account: dict[str, Any],
    balance_payload: dict[str, Any],
    usage_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    infos = balance_payload.get("balance_infos") or []
    info = next((item for item in infos if str(item.get("currency")) == "CNY"), None) or (infos[0] if infos else {})
    currency = str(info.get("currency") or "CNY")
    result: dict[str, Any] = {
        "balance": {
            "remaining": _number(info.get("total_balance")),
            "granted": _number(info.get("granted_balance")),
            "topped_up": _number(info.get("topped_up_balance")),
            "currency": "¥" if currency == "CNY" else "$",
        },
        "today": {"tokens": 0, "requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0},
        "period": {
            "days": 30,
            "tokens": 0,
            "requests": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cached_tokens": 0,
            "label": "本月",
        },
        "models": [],
        "daily": [],
        "note": "",
    }
    if not usage_payload:
        result["note"] = "DeepSeek API Key 只能查询余额；详细 Token 需要填写 Platform userToken。"
        return result
    rows, totals, _ = _deepseek_usage_rows(usage_payload)
    today = datetime.now().date().isoformat()
    models: dict[str, dict[str, Any]] = {}
    daily: dict[str, dict[str, Any]] = {}
    for row in rows:
        model = models.setdefault(row["model"], {"model": row["model"], "tokens": 0, "requests": 0})
        model["tokens"] += row["tokens"]
        model["requests"] += row["requests"]
        day = daily.setdefault(row["date"], {"date": row["date"], "tokens": 0, "requests": 0})
        day["tokens"] += row["tokens"]
        day["requests"] += row["requests"]
        for metric in ("prompt_tokens", "completion_tokens", "cached_tokens"):
            result["period"][metric] += row.get(metric, 0)
        result["period"]["tokens"] += row["tokens"]
        result["period"]["requests"] += row["requests"]
        if row["date"] == today:
            for metric in ("prompt_tokens", "completion_tokens", "cached_tokens"):
                result["today"][metric] += row.get(metric, 0)
            result["today"]["tokens"] += row["tokens"]
            result["today"]["requests"] += row["requests"]
    result["models"] = sorted(models.values(), key=lambda item: item["tokens"], reverse=True)
    result["daily"] = sorted(daily.values(), key=lambda item: item["date"])
    return result


async def _get_json(client: httpx.AsyncClient, url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    response = await client.get(url, headers=headers)
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:240]}")
    data = response.json()
    if isinstance(data, dict):
        if data.get("success") is False:
            raise RuntimeError(str(data.get("message") or "平台返回失败"))
        if data.get("code") not in (None, 0):
            raise RuntimeError(str(data.get("msg") or f"平台返回错误码 {data.get('code')}"))
    return data if isinstance(data, dict) else {}


def _newapi_token_rows(payload: Any) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        data = data.get("items") or data.get("data") or []
    return [item for item in data or [] if isinstance(item, dict)] if isinstance(data, list) else []


def _newapi_log_rows(payload: Any) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        data = data.get("items") or data.get("data") or []
    return [item for item in data or [] if isinstance(item, dict)] if isinstance(data, list) else []


def _newapi_status_label(status: Any) -> str:
    return {1: "启用", 2: "禁用", 3: "过期", 4: "耗尽"}.get(int(_number(status)), "未知")


async def _fetch_newapi_keys(
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    qpu: float,
    start_ts: int,
    end_ts: int,
) -> list[dict[str, Any]]:
    tokens: list[dict[str, Any]] = []
    for page in range(1, 6):
        payload = await _get_json(client, f"{base}/api/token/?p={page}&size=100", headers)
        rows = _newapi_token_rows(payload)
        tokens.extend(rows)
        if len(rows) < 100:
            break

    logs: list[dict[str, Any]] = []
    for page in range(1, 21):
        payload = await _get_json(
            client,
            f"{base}/api/log/self?p={page}&page_size=100&type=2&start_timestamp={start_ts}&end_timestamp={end_ts}",
            headers,
        )
        rows = _newapi_log_rows(payload)
        logs.extend(rows)
        if len(rows) < 100:
            break

    usage: dict[str, dict[str, Any]] = {}
    for row in logs:
        name = str(row.get("token_name") or row.get("tokenName") or "未命名 Key")
        item = usage.setdefault(
            name,
            {
                "name": name,
                "tokens": 0,
                "today_tokens": 0,
                "requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "quota": 0,
            },
        )
        tokens_used = int(_number(row.get("prompt_tokens"))) + int(_number(row.get("completion_tokens")))
        item["tokens"] += tokens_used
        if _day(row.get("created_at")) == datetime.now().date().isoformat():
            item["today_tokens"] += tokens_used
        item["prompt_tokens"] += int(_number(row.get("prompt_tokens")))
        item["completion_tokens"] += int(_number(row.get("completion_tokens")))
        item["requests"] += 1
        item["quota"] += _number(row.get("quota"))

    result = []
    for token in tokens:
        name = str(token.get("name") or "未命名 Key")
        row = usage.get(name, {})
        result.append(
            {
                "name": name,
                "status": _newapi_status_label(token.get("status")),
                "used": _money(token.get("used_quota"), qpu),
                "remaining": None if token.get("unlimited_quota") else _money(token.get("remain_quota"), qpu),
                "today_tokens": int(row.get("today_tokens", 0)),
                "period_tokens": int(row.get("tokens", 0)),
                "prompt_tokens": int(row.get("prompt_tokens", 0)),
                "completion_tokens": int(row.get("completion_tokens", 0)),
                "requests": int(row.get("requests", 0)),
                "cost": round(_number(row.get("quota")) / qpu, 4),
            }
        )
    return result


async def _fetch_newapi(account: dict[str, Any]) -> dict[str, Any]:
    base = str(account.get("base_url") or "").rstrip("/")
    if not base:
        raise RuntimeError("缺少 Base URL")
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_ts = int(today_start.timestamp())
    end_ts = int(time.time())
    month_start = (today_start - timedelta(days=29)).timestamp()
    async with _client(base) as client:
        status_payload = await _get_json(client, f"{base}/api/status")
        status = status_payload.get("data") or {}
        headers = _headers(account)
        user_payload = await _get_json(client, f"{base}/api/user/self", headers)
        user = user_payload.get("data") or {}
        today_payload = await _get_json(
            client,
            f"{base}/api/log/self/stat?type=2&start_timestamp={start_ts}&end_timestamp={end_ts}",
            headers,
        )
        today_stat = today_payload.get("data") or {}
        data_payload = await _get_json(
            client,
            f"{base}/api/data/self?start_timestamp={int(month_start)}&end_timestamp={end_ts}",
            headers,
        )
        rows = _newapi_rows(data_payload.get("data"))
    return _normalize_newapi(account, status, user, today_stat, rows)


def _deepseek_by_key_rows(payload: Any) -> list[dict[str, Any]]:
    """Best-effort parser for the private by_api_key usage payload."""
    found: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if not isinstance(value, dict):
            return
        usage = value.get("usage") or value.get("usages")
        identity = (
            value.get("api_key_name")
            or value.get("apiKeyName")
            or value.get("key_name")
            or value.get("token_name")
            or value.get("api_key_id")
            or value.get("apiKeyId")
        )
        if identity and isinstance(usage, list):
            found.append(value)
            return
        for key in ("series", "keys", "api_keys", "items", "data", "biz_data", "total"):
            if key in value:
                walk(value[key])

    walk(payload)
    return found


def _deepseek_keys_from_payload(payload: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for block in _deepseek_by_key_rows(payload):
        name = str(
            block.get("api_key_name")
            or block.get("apiKeyName")
            or block.get("key_name")
            or block.get("token_name")
            or block.get("api_key_id")
            or block.get("apiKeyId")
            or "未命名 Key"
        )
        if name.startswith("sk-"):
            name = f"{name[:5]}…{name[-4:]}"
        tokens = 0
        requests = 0
        for item in block.get("usage") or []:
            if not isinstance(item, dict):
                continue
            amount = int(_number(item.get("amount")))
            if str(item.get("type") or "").upper() == "REQUEST":
                requests += amount
            else:
                tokens += amount
        result.append(
            {
                "name": name,
                "status": "启用",
                "today_tokens": 0,
                "period_tokens": tokens,
                "requests": requests,
            }
        )
    return result


async def _fetch_deepseek(account: dict[str, Any]) -> dict[str, Any]:
    api_key = unprotect(str(account.get("api_key") or "")).strip()
    platform_token = unprotect(str(account.get("platform_token") or "")).strip()
    if not api_key and not platform_token:
        raise RuntimeError("缺少 DeepSeek API Key 或 Platform Token")
    async with _client("https://api.deepseek.com") as client:
        if api_key:
            balance_headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
            balance_payload = await _get_json(client, DEEPSEEK_BALANCE, balance_headers)
        else:
            balance_payload = {}
        usage_payload = None
        usage_error = ""
        if platform_token or _cookie_header(account):
            try:
                now = datetime.now()
                headers = _headers(account)
                amount = await _get_json(
                    client,
                    f"{DEEPSEEK_USAGE.format(kind='amount')}?month={now.month}&year={now.year}",
                    headers,
                )
                cost = await _get_json(
                    client,
                    f"{DEEPSEEK_USAGE.format(kind='cost')}?month={now.month}&year={now.year}",
                    headers,
                )
                biz_cost = (cost.get("data") or {}).get("biz_data")
                currency = (
                    biz_cost[0].get("currency")
                    if isinstance(biz_cost, list) and biz_cost
                    else "CNY"
                )
                usage_payload = {**amount, "currency": currency}
            except Exception as exc:
                usage_error = str(exc)[:240]
    result = _normalize_deepseek(account, balance_payload, usage_payload)
    if usage_error:
        result["note"] = f"余额已读取；详细用量读取失败：{usage_error}"
    return result


def mask_account(account: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": account.get("id"),
        "name": account.get("name"),
        "kind": account.get("kind"),
        "base_url": account.get("base_url", ""),
        "user_id": account.get("user_id", ""),
        "has_access_token": bool(account.get("access_token")),
        "has_api_key": bool(account.get("api_key")),
        "has_platform_token": bool(account.get("platform_token")),
        "has_session_cookies": bool(account.get("session_cookies")),
    }


def get_account(account_id: str) -> dict[str, Any] | None:
    return next(
        (item for item in load_config().get("usage_accounts") or [] if item.get("id") == account_id),
        None,
    )


def list_accounts(masked: bool = True) -> list[dict[str, Any]]:
    accounts = load_config().get("usage_accounts") or []
    return [mask_account(item) for item in accounts] if masked else accounts


def add_account(payload: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    accounts = list(config.get("usage_accounts") or [])
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("账户名称不能为空")
    account_id = _account_id(name)
    existing = next((item for item in accounts if item.get("id") == account_id), None)
    if existing:
        account = existing
    else:
        account = {"id": account_id}
        accounts.append(account)
    previous = dict(account)
    access_token = payload.get("access_token") or previous.get("access_token") or ""
    api_key = payload.get("api_key") or previous.get("api_key") or ""
    platform_token = payload.get("platform_token") or previous.get("platform_token") or ""
    cookies = payload.get("session_cookies") or previous.get("session_cookies") or ""
    if isinstance(cookies, list):
        cookies = protect_json(cookies)
    elif isinstance(cookies, str) and cookies and not cookies.startswith(("dpapi:", "plain:")):
        cookies = protect_json(cookies)
    base_url = str(payload.get("base_url") or "").rstrip("/")
    if (payload.get("kind") or "newapi") == "newapi" and base_url.endswith("/v1"):
        base_url = base_url[:-3]
    account.update(
        {
            "name": name,
            "kind": payload.get("kind") or "newapi",
            "base_url": base_url,
            "user_id": str(payload.get("user_id") or ""),
            "access_token": protect(str(access_token)),
            "api_key": protect(str(api_key)),
            "platform_token": protect(str(platform_token)),
            "session_cookies": str(cookies or ""),
        }
    )
    config["usage_accounts"] = accounts
    save_config(config)
    _key_cache.pop(account_id, None)
    _key_cooldown.pop(account_id, None)
    return mask_account(account)


def delete_account(account_id: str) -> bool:
    config = load_config()
    accounts = list(config.get("usage_accounts") or [])
    remaining = [item for item in accounts if item.get("id") != account_id]
    if len(remaining) == len(accounts):
        return False
    config["usage_accounts"] = remaining
    save_config(config)
    _cache.pop(account_id, None)
    _key_cache.pop(account_id, None)
    _key_cooldown.pop(account_id, None)
    return True


async def fetch_account(account: dict[str, Any], force: bool = False) -> dict[str, Any]:
    account_id = str(account.get("id") or "")
    cached = _cache.get(account_id)
    if not force and cached and time.time() - cached[0] < CACHE_TTL:
        return cached[1]
    try:
        if account.get("kind") == "deepseek":
            data = await _fetch_deepseek(account)
        else:
            data = await _fetch_newapi(account)
        result = {
            "id": account_id,
            "name": account.get("name"),
            "kind": account.get("kind"),
            "ok": True,
            "error": "",
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            **data,
        }
    except Exception as exc:
        result = {
            "id": account_id,
            "name": account.get("name"),
            "kind": account.get("kind"),
            "ok": False,
            "error": str(exc)[:400],
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
    _cache[account_id] = (time.time(), result)
    return result


async def fetch_all(force: bool = False) -> list[dict[str, Any]]:
    accounts = load_config().get("usage_accounts") or []
    results = []
    for account in accounts:
        results.append(await fetch_account(account, force=force))
    return results


async def _fetch_newapi_keys_for_account(account: dict[str, Any]) -> list[dict[str, Any]]:
    base = str(account.get("base_url") or "").rstrip("/")
    if not base:
        raise RuntimeError("缺少 Base URL")
    end = int(time.time())
    start = end - 30 * 86400
    async with _client(base) as client:
        status_payload = await _get_json(client, f"{base}/api/status")
        status = status_payload.get("data") or {}
        qpu = _number(status.get("quota_per_unit")) or 500000.0
        return await _fetch_newapi_keys(client, base, _headers(account), qpu, start, end)


async def fetch_keys(account_id: str, force: bool = False) -> dict[str, Any]:
    account = get_account(account_id)
    if not account:
        raise ValueError("用量账户不存在")
    cached = _key_cache.get(account_id)
    if not force and cached and time.time() - cached[0] < CACHE_TTL:
        return cached[1]
    cooldown = _key_cooldown.get(account_id, 0)
    if cooldown > time.time():
        return {
            "keys": [],
            "note": "平台刚刚返回 429，已暂停按 API Key 请求 60 秒；账号级用量不受影响。",
            "limited": True,
        }
    try:
        if account.get("kind") == "deepseek":
            token = unprotect(str(account.get("platform_token") or ""))
            cookies = _cookie_header(account)
            if not token and not cookies:
                raise RuntimeError("DeepSeek 详细 API Key 用量需要 Platform userToken")
            end = int(time.time())
            start = end - 30 * 86400
            tz = int((datetime.now().astimezone().utcoffset() or timedelta()).total_seconds())
            async with _client("https://platform.deepseek.com") as client:
                payload = await _get_json(
                    client,
                    "https://platform.deepseek.com/api/v0/usage/by_api_key/amount"
                    f"?start={start}&end={end}&tz={tz}",
                    _headers(account),
                )
            keys = _deepseek_keys_from_payload(payload)
            note = "" if keys else "平台未返回可识别的 API Key 明细。"
        else:
            keys = await _fetch_newapi_keys_for_account(account)
            note = "累计额度来自令牌列表，区间 Token/请求数来自请求日志。"
        result = {"keys": keys, "note": note, "limited": False}
    except Exception as exc:
        message = str(exc)
        if "429" in message:
            _key_cooldown[account_id] = time.time() + 60
            message = "平台返回 429（请求过于频繁），已暂停 60 秒；账号级用量不受影响。"
        result = {"keys": [], "note": message[:300], "limited": "429" in message}
    _key_cache[account_id] = (time.time(), result)
    return result
