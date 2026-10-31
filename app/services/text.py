from __future__ import annotations

import html as html_lib
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "ref_src",
    "spm",
    "from",
}


def strip_html(value: str, limit: int | None = None) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "lxml")
    for tag in soup(["script", "style", "noscript", "iframe"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def canonicalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), "")
    )


def parse_iso(value: str) -> str:
    if not value:
        return ""
    value = value.strip()
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return value


def parse_json_block(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        value = json.loads(text[start : end + 1])
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def compact(value: Any, limit: int = 6000) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + "…"
