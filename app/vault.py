from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from .config import load_config, vault_path

VAULT_DIRS = [
    "00-Inbox",
    "01-Drafts",
    "02-Knowledge/Sources",
    "02-Knowledge/Concepts",
    "02-Knowledge/Technologies",
    "02-Knowledge/Practices",
    "02-Knowledge/Github-Repositories",
    "03-Maps",
    "08-Collections",
    "90-Attachments",
    "_system/publish",
    "_system/skills",
    "_system/wiki-build",
]

SKIP_PARTS = {".obsidian", "_system", "90-Attachments", ".git", "data"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_vault(path: Path | str | None = None) -> Path:
    root = Path(path) if path else vault_path()
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for rel in VAULT_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)
    system_readme = root / "_system" / "README.md"
    if not system_readme.exists():
        system_readme.write_text(
            "# _system\n\n此目录由 AI-PKM Agent 使用，不进入 Wiki 索引。\n",
            encoding="utf-8",
        )
    return root


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
    if not match:
        return {}, text
    raw = match.group(1)
    body = text[match.end() :]
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        data = {}
    return (data if isinstance(data, dict) else {}), body


def dump_note(meta: dict[str, Any], body: str) -> str:
    front = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{front}\n---\n\n{body.lstrip()}"


def slugify(value: str, fallback: str = "note") -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value, flags=re.UNICODE)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return (value or fallback)[:72]


def safe_relpath(rel: str) -> str:
    rel = rel.replace("\\", "/").lstrip("/")
    parts = [part for part in rel.split("/") if part not in ("", ".", "..")]
    if not parts:
        raise ValueError("empty path")
    return "/".join(parts)


def target_path(rel: str, root: Path | None = None) -> Path:
    root = (root or vault_path()).resolve()
    rel = safe_relpath(rel)
    path = (root / rel).resolve()
    if root not in path.parents and path != root:
        raise ValueError("path escapes vault")
    return path


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_note(rel: str) -> tuple[dict[str, Any], str, Path]:
    path = target_path(rel)
    text = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    return meta, body, path


def source_note_rel(item: dict[str, Any]) -> str:
    title = item.get("title") or item.get("repo_full_name") or "source"
    stamp = (item.get("retrieved_at") or now_iso())[:10]
    digest = hashlib.sha1(
        (item.get("canonical_url") or item.get("url") or title).encode("utf-8")
    ).hexdigest()[:8]
    return f"02-Knowledge/Sources/{stamp}-{slugify(title)}-{digest}.md"


def _tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, str):
        try:
            import json

            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except Exception:
            pass
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def create_source_note(item: dict[str, Any]) -> str:
    rel = source_note_rel(item)
    path = target_path(rel)
    if path.exists():
        return rel

    title = item.get("title") or item.get("repo_full_name") or "未命名来源"
    summary = item.get("summary_zh") or item.get("summary") or ""
    translation = item.get("translation_zh") or ""
    content = item.get("content") or ""
    excerpt = re.sub(r"\s+", " ", content).strip()[:1200]
    key_points = [
        line.strip("-• ").strip()
        for line in (item.get("key_points") or "").splitlines()
        if line.strip()
    ]
    if not key_points:
        key_points = [
            part.strip()
            for part in re.split(r"[。！？\n]", summary)
            if len(part.strip()) >= 8
        ][:4]

    meta = {
        "id": item.get("id", ""),
        "type": "source",
        "status": "published",
        "source_type": item.get("source_type", ""),
        "source_name": item.get("source_name", ""),
        "source_url": item.get("url", ""),
        "title": title,
        "author": item.get("author", ""),
        "published_at": item.get("published_at", ""),
        "retrieved_at": item.get("retrieved_at", now_iso()),
        "tags": _tags(item.get("tags")),
        "publish": False,
        "created_at": now_iso(),
    }
    if item.get("repo_full_name"):
        meta["repo_full_name"] = item["repo_full_name"]
        meta["stars"] = item.get("stars", 0)
        meta["license"] = item.get("license", "")
        meta["primary_language"] = item.get("primary_language", "")

    parts = [f"# {title}", ""]
    parts += ["## 摘要", "", summary or "（暂无摘要，配置模型后可生成）", ""]
    if key_points:
        parts += ["## 关键点", ""] + [f"- {point}" for point in key_points] + [""]
    if translation:
        parts += ["## 中文翻译", "", translation, ""]
    if excerpt:
        parts += ["## 原文摘录", "", f"> {excerpt}", ""]
    parts += ["## 来源", "", f"- [{title}]({item.get('url', '')})", ""]
    atomic_write(path, dump_note(meta, "\n".join(parts)))
    return rel


def append_ai_section(rel: str, patch_id: str, title: str, content: str) -> str:
    path = target_path(rel)
    marker = f"<!-- ai:begin id={patch_id} -->"
    if path.exists():
        meta, body, _ = read_note(rel)
        if marker in body:
            return rel
        addition = f"\n\n## AI 补充\n\n{marker}\n{content.strip()}\n<!-- ai:end -->\n"
        atomic_write(path, dump_note(meta, body.rstrip() + addition))
        return rel

    meta = {
        "id": hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16],
        "type": "knowledge",
        "status": "published",
        "title": title,
        "publish": False,
        "created_at": now_iso(),
    }
    body = f"# {title}\n\n## AI 补充\n\n{marker}\n{content.strip()}\n<!-- ai:end -->\n"
    atomic_write(path, dump_note(meta, body))
    return rel


def scan_notes(root: Path | None = None) -> list[dict[str, Any]]:
    root = (root or vault_path()).resolve()
    notes: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.md")):
        rel_parts = path.relative_to(root).parts
        if any(part in SKIP_PARTS for part in rel_parts):
            continue
        if len(rel_parts) == 1 and path.name.lower() == "readme.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        meta, body = parse_frontmatter(text)
        rel = path.relative_to(root).as_posix()
        title = str(meta.get("title") or path.stem)
        notes.append(
            {
                "path": rel,
                "title": title,
                "meta": meta,
                "body": body,
                "updated_at": datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            }
        )
    return notes


def iter_note_documents(root: Path | None = None) -> Iterable[dict[str, Any]]:
    for note in scan_notes(root):
        meta = note["meta"]
        yield {
            "doc_id": f"note:{note['path']}",
            "kind": "note",
            "title": note["title"],
            "content": note["body"],
            "path": note["path"],
            "source_url": str(meta.get("source_url") or ""),
            "metadata": {
                "type": meta.get("type", "note"),
                "tags": meta.get("tags", []),
                "status": meta.get("status", "published"),
            },
        }


def list_notes(root: Path | None = None) -> list[dict[str, Any]]:
    return [
        {
            "path": note["path"],
            "title": note["title"],
            "type": note["meta"].get("type", "note"),
            "tags": note["meta"].get("tags", []),
            "updated_at": note["updated_at"],
        }
        for note in scan_notes(root)
    ]
