from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import db, expire_patches, now_iso
from ..vault import append_ai_section


def create_patch(
    *,
    target_path: str,
    patch_type: str,
    title: str,
    content: str,
    source_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    patch_id = "patch_" + hashlib.sha1(
        f"{target_path}:{title}:{now_iso()}".encode("utf-8")
    ).hexdigest()[:16]
    created = now_iso()
    expires = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    with db() as conn:
        existing = conn.execute(
            """
            SELECT id FROM patches
            WHERE status='proposed' AND target_path=? AND title=?
            ORDER BY created_at DESC LIMIT 1
            """,
            (target_path, title),
        ).fetchone()
        if existing:
            patch_id = str(existing["id"])
            conn.execute(
                """
                UPDATE patches SET content=?, source_refs=?, created_at=?, expires_at=?
                WHERE id=?
                """,
                (
                    content,
                    json.dumps(source_refs or [], ensure_ascii=False),
                    created,
                    expires,
                    patch_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO patches(id, target_path, patch_type, title, content, source_refs,
                                    status, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, 'proposed', ?, ?)
                """,
                (
                    patch_id,
                    target_path,
                    patch_type,
                    title,
                    content,
                    json.dumps(source_refs or [], ensure_ascii=False),
                    created,
                    expires,
                ),
            )
    return get_patch(patch_id) or {}


def _row(row: Any) -> dict[str, Any]:
    item = dict(row)
    try:
        item["source_refs"] = json.loads(item.get("source_refs") or "[]")
    except json.JSONDecodeError:
        item["source_refs"] = []
    return item


def get_patch(patch_id: str) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM patches WHERE id = ?", (patch_id,)).fetchone()
    return _row(row) if row else None


def list_patches(limit: int = 20) -> list[dict[str, Any]]:
    expire_patches()
    with db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM patches
            WHERE status='proposed'
            ORDER BY CASE patch_type WHEN 'conflict' THEN 0 ELSE 1 END, created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_row(row) for row in rows]


def reject_patch(patch_id: str) -> dict[str, Any] | None:
    with db() as conn:
        conn.execute(
            "UPDATE patches SET status='rejected' WHERE id=? AND status='proposed'",
            (patch_id,),
        )
    return get_patch(patch_id)


def apply_patch(patch_id: str) -> dict[str, Any] | None:
    patch = get_patch(patch_id)
    if patch is None:
        return None
    if patch["status"] != "proposed":
        return patch
    rel = append_ai_section(
        patch["target_path"],
        patch_id,
        patch["title"],
        patch["content"],
    )
    with db() as conn:
        conn.execute(
            "UPDATE patches SET status='applied', applied_at=?, target_path=? WHERE id=?",
            (now_iso(), rel, patch_id),
        )
    from .search import reindex_note

    reindex_note(rel)
    result = get_patch(patch_id) or {}
    result["note_path"] = rel
    return result


def make_answer_patch(
    *,
    question: str,
    answer: str,
    citations: list[dict[str, Any]],
) -> dict[str, Any]:
    from ..vault import slugify

    title = question.strip().splitlines()[0][:80] or "问答记录"
    rel = f"02-Knowledge/Concepts/{slugify(title)}.md"
    source_lines = []
    for citation in citations:
        label = citation.get("title") or citation.get("doc_id") or "来源"
        url = citation.get("source_url") or ""
        path = citation.get("path") or ""
        if path:
            source_lines.append(f"- {label} (`{path}`)")
        elif url:
            source_lines.append(f"- [{label}]({url})")
        else:
            source_lines.append(f"- {label}")
    content = "\n".join(
        [
            f"## 问题",
            "",
            question.strip(),
            "",
            "## 回答",
            "",
            answer.strip(),
            "",
            "## 来源",
            "",
            *source_lines,
        ]
    )
    return create_patch(
        target_path=rel,
        patch_type="create_note",
        title=title,
        content=content,
        source_refs=citations,
    )
