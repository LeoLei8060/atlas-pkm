from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from .text import strip_html


def _extract_from_html(html: str, max_chars: int) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()

    candidates: list[tuple[int, object]] = []
    for tag in soup.find_all(["article", "main", "section", "div"]):
        paragraphs = tag.find_all("p")
        if not paragraphs:
            continue
        length = sum(len(p.get_text(" ", strip=True)) for p in paragraphs)
        if length >= 240:
            candidates.append((length, tag))

    node = max(candidates, key=lambda item: item[0])[1] if candidates else soup.body
    if node is None:
        return ""
    text = strip_html(str(node), max_chars)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text if len(text) >= 240 else ""


async def fetch_article_text(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    max_chars: int = 12000,
) -> str:
    """Fetch and extract the main article text. Returns empty string on failure."""
    owns_client = client is None
    client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(35.0, connect=12.0),
        follow_redirects=True,
        trust_env=False,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; AI-PKM-Agent/0.1; +https://localhost)"
        },
    )
    try:
        response = await client.get(url)
        if response.status_code >= 400:
            return ""
        content_type = response.headers.get("content-type", "").lower()
        if "html" not in content_type and "xml" not in content_type:
            return ""
        html = response.text
        if len(html) < 200:
            return ""
        return _extract_from_html(html, max_chars)
    except Exception:
        return ""
    finally:
        if owns_client:
            await client.aclose()

