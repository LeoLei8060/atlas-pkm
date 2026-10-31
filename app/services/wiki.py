from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import settings
from ..vault import scan_notes, slugify


def _slug_for(rel: str, used: set[str]) -> str:
    base = slugify(rel[:-3].replace("/", "-") if rel.endswith(".md") else rel.replace("/", "-"))
    candidate = base or "note"
    index = 2
    while candidate in used:
        candidate = f"{base}-{index}"
        index += 1
    used.add(candidate)
    return candidate


def _render_markdown(text: str) -> str:
    md = markdown.Markdown(
        extensions=["extra", "toc", "sane_lists", "fenced_code", "tables"],
        output_format="html5",
    )
    return md.convert(text)


def _replace_wikilinks(text: str, resolver: dict[str, str]) -> str:
    pattern = re.compile(r"\[\[([^\]]+)\]\]")
    in_fence = False
    output: list[str] = []
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            output.append(line)
            continue
        if in_fence:
            output.append(line)
            continue

        def repl(match: re.Match[str]) -> str:
            raw = match.group(1)
            target, _, label = raw.partition("|")
            target = target.split("#", 1)[0].strip()
            label = (label or target).strip()
            href = resolver.get(target) or resolver.get(target.lower())
            if href:
                return f"[{label}]({href})"
            return f'<span class="wikilink-missing">{html.escape(label)}</span>'

        output.append(pattern.sub(repl, line))
    return "".join(output)


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(settings.templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )


def build_wiki() -> dict[str, Any]:
    settings.ensure()
    notes = scan_notes()
    used: set[str] = set()
    entries: list[dict[str, Any]] = []
    resolver: dict[str, str] = {}

    for note in notes:
        slug = _slug_for(note["path"], used)
        href = f"{slug}.html"
        title = note["title"]
        stem = Path(note["path"]).stem
        entries.append({**note, "slug": slug, "href": href})
        for key in (title, stem, note["path"], note["path"][:-3] if note["path"].endswith(".md") else note["path"]):
            resolver[key] = href
            resolver[key.lower()] = href

    expected = {f"{entry['slug']}.html" for entry in entries} | {"index.html"}
    for stale in settings.wiki_dir.glob("*.html"):
        if stale.name not in expected:
            stale.unlink(missing_ok=True)

    env = _env()
    base = env.get_template("wiki_base.html")
    for entry in entries:
        body = entry["body"]
        body = re.sub(r"^\s*#\s+.*\n+", "", body, count=1)
        body = _replace_wikilinks(body, resolver)
        content = _render_markdown(body)
        page = base.render(
            site_title="LLM Wiki",
            page_title=entry["title"],
            content=content,
            notes=entries,
            current=entry["path"],
            meta=entry["meta"],
        )
        (settings.wiki_dir / f"{entry['slug']}.html").write_text(page, encoding="utf-8")

    index_page = env.get_template("wiki_index.html").render(
        site_title="LLM Wiki",
        notes=entries,
        empty=not entries,
    )
    (settings.wiki_dir / "index.html").write_text(index_page, encoding="utf-8")
    (settings.wiki_dir / "style.css").write_text(_CSS, encoding="utf-8")
    (settings.wiki_dir / "manifest.json").write_text(
        json.dumps(
            [{"title": e["title"], "path": e["path"], "href": e["href"]} for e in entries],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"pages": len(entries), "index": str(settings.wiki_dir / "index.html")}


_CSS = """
:root {
  --bg: #f7f5ef;
  --paper: #fffdf7;
  --ink: #23211d;
  --muted: #6f6a61;
  --line: #e4dfd3;
  --accent: #b45309;
  --accent-soft: #fdf0d5;
  --code: #f0ece2;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
  line-height: 1.75;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.layout { display: grid; grid-template-columns: 280px minmax(0, 1fr); min-height: 100vh; }
.sidebar {
  background: #221f1a; color: #e9e2d4; padding: 28px 22px;
  position: sticky; top: 0; height: 100vh; overflow: auto;
}
.brand { font-size: 22px; font-weight: 700; letter-spacing: .08em; margin-bottom: 4px; }
.brand span { color: #f0b35a; }
.side-sub { color: #9d9587; font-size: 12px; margin-bottom: 24px; }
.sidebar h3 { color: #8d8577; font-size: 11px; letter-spacing: .16em; text-transform: uppercase; margin: 24px 0 8px; }
.note-link { display: block; color: #ddd5c6; font-size: 13px; padding: 6px 8px; border-radius: 6px; }
.note-link:hover { background: #322e27; text-decoration: none; }
.note-link.active { background: #3b342a; color: #fff; }
.main { padding: 48px min(8vw, 96px); max-width: 980px; }
.page-title { font-size: 38px; line-height: 1.2; margin: 0 0 10px; letter-spacing: -.02em; }
.meta { color: var(--muted); font-size: 13px; border-bottom: 1px solid var(--line); padding-bottom: 18px; margin-bottom: 30px; }
.meta code { background: var(--code); padding: 1px 6px; border-radius: 4px; }
article h1 { font-size: 32px; }
article h2 { font-size: 24px; margin-top: 36px; border-bottom: 1px solid var(--line); padding-bottom: 6px; }
article h3 { font-size: 19px; margin-top: 28px; }
article p { margin: 14px 0; }
article ul, article ol { padding-left: 24px; }
article blockquote {
  margin: 18px 0; padding: 12px 18px; border-left: 3px solid var(--accent);
  background: var(--accent-soft); color: #5b4a2f;
}
article pre {
  background: #23211d; color: #f0ece2; padding: 16px; border-radius: 10px;
  overflow: auto; font-size: 13px; line-height: 1.6;
}
article code { font-family: "JetBrains Mono", Consolas, monospace; font-size: .92em; }
article :not(pre) > code { background: var(--code); padding: 2px 5px; border-radius: 4px; }
article table { width: 100%; border-collapse: collapse; margin: 18px 0; }
article th, article td { border: 1px solid var(--line); padding: 8px 10px; text-align: left; }
article th { background: #f1ecdf; }
.wikilink-missing { color: #a8a196; border-bottom: 1px dashed #c9c1b2; }
.empty { padding: 80px 0; color: var(--muted); }
.index-grid { display: grid; gap: 12px; margin-top: 28px; }
.index-card {
  display: block; background: var(--paper); border: 1px solid var(--line);
  border-radius: 12px; padding: 18px 20px; color: var(--ink);
}
.index-card:hover { border-color: #c9a66b; text-decoration: none; transform: translateY(-1px); }
.index-card h3 { margin: 0 0 6px; font-size: 17px; }
.index-card p { margin: 0; color: var(--muted); font-size: 13px; }
.search {
  width: 100%; padding: 12px 14px; border: 1px solid var(--line); border-radius: 10px;
  background: var(--paper); color: var(--ink); font-size: 14px; margin-top: 18px;
}
@media (max-width: 860px) {
  .layout { grid-template-columns: 1fr; }
  .sidebar { position: static; height: auto; }
  .main { padding: 28px 20px; }
}
"""


def wiki_status() -> dict[str, Any]:
    index = settings.wiki_dir / "index.html"
    return {
        "built": index.exists(),
        "pages": len(list(settings.wiki_dir.glob("*.html"))) - (1 if index.exists() else 0),
        "url": "/wiki/",
    }
