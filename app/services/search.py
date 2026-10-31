from __future__ import annotations

import json
from typing import Any

from ..db import (
    _search_terms,
    _specific_terms,
    db,
    get_documents_by_ids,
    search_documents,
    upsert_document,
    vector_search,
)
from ..vault import iter_note_documents, scan_notes
from .embeddings import semantic_search


def rebuild_search_index() -> int:
    with db() as conn:
        existing = {
            row["doc_id"] for row in conn.execute("SELECT doc_id FROM documents")
        }
        seen: set[str] = set()
        count = 0
        for doc in iter_note_documents():
            upsert_document(conn, **doc)
            seen.add(doc["doc_id"])
            count += 1
        rows = conn.execute("SELECT * FROM feed_items").fetchall()
        for row in rows:
            doc_id = f"feed:{row['id']}"
            upsert_document(
                conn,
                doc_id=doc_id,
                kind="feed",
                title=row["title"],
                content=row["summary_zh"] or row["summary"] or row["content"],
                source_url=row["url"],
                metadata={
                    "source_type": row["source_type"],
                    "tags": json.loads(row["tags"] or "[]"),
                    "feed_id": row["id"],
                },
            )
            seen.add(doc_id)
            count += 1
        for doc_id in existing - seen:
            conn.execute("DELETE FROM documents WHERE doc_id=?", (doc_id,))
    return count


def reindex_note(rel_path: str) -> None:
    target = next((n for n in scan_notes() if n["path"] == rel_path), None)
    if target is None:
        with db() as conn:
            conn.execute("DELETE FROM documents WHERE doc_id = ?", (f"note:{rel_path}",))
        return
    meta = target["meta"]
    with db() as conn:
        upsert_document(
            conn,
            doc_id=f"note:{rel_path}",
            kind="note",
            title=target["title"],
            content=target["body"],
            path=rel_path,
            source_url=str(meta.get("source_url") or ""),
            metadata={
                "type": meta.get("type", "note"),
                "tags": meta.get("tags", []),
                "status": meta.get("status", "published"),
            },
        )


def search(query: str, limit: int = 8) -> list[dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return search_documents(query, limit=limit)

    pool = max(limit * 2, 8)
    lexical = search_documents(query, limit=pool)
    semantic = vector_search(query, limit=pool)
    if not semantic:
        return lexical[:limit]

    docs: dict[str, dict[str, Any]] = {doc["doc_id"]: doc for doc in lexical}
    specific = _specific_terms(_search_terms(query))
    missing = [hit["doc_id"] for hit in semantic if hit["doc_id"] not in docs]
    for doc in get_documents_by_ids(missing):
        if specific:
            haystack = f"{doc.get('title', '')} {doc.get('content', '')}".lower()
            if not any(term.lower() in haystack for term in specific):
                continue
        docs[doc["doc_id"]] = doc

    scores: dict[str, float] = {}
    for index, doc in enumerate(lexical):
        scores[doc["doc_id"]] = 0.65 * (1.0 - index / max(len(lexical), 1))
    for hit in semantic:
        scores[hit["doc_id"]] = scores.get(hit["doc_id"], 0.0) + 0.35 * hit["score"]

    ordered = sorted(scores, key=lambda doc_id: scores[doc_id], reverse=True)
    return [docs[doc_id] for doc_id in ordered[:limit] if doc_id in docs]


def _context_item(doc: dict[str, Any], index: int) -> dict[str, Any]:
    content = str(doc.get("content") or "")
    if len(content) > 2600:
        content = content[:2600] + "…"
    return {
        "index": index,
        "doc_id": doc.get("doc_id"),
        "kind": doc.get("kind"),
        "title": doc.get("title"),
        "path": doc.get("path"),
        "source_url": doc.get("source_url"),
        "snippet": doc.get("snippet") or content[:240],
        "content": content,
    }


def build_context(query: str, limit: int = 6) -> list[dict[str, Any]]:
    docs = search_documents(query, limit=limit)
    return [_context_item(doc, index) for index, doc in enumerate(docs, start=1)]


async def build_context_async(
    query: str,
    config: dict[str, Any],
    limit: int = 6,
) -> list[dict[str, Any]]:
    # Use the hybrid FTS + local n-gram path first, then add external
    # embedding hits when configured.
    context = [
        _context_item(doc, index)
        for index, doc in enumerate(search(query, limit=limit), start=1)
    ]
    try:
        semantic = await semantic_search(query, config, limit=limit)
    except Exception:
        semantic = []
    if not semantic:
        return context
    seen = {item["doc_id"] for item in context}
    for doc in semantic:
        if len(context) >= limit:
            break
        doc_id = doc.get("doc_id")
        if not doc_id or doc_id in seen:
            continue
        context.append(_context_item(doc, len(context) + 1))
        seen.add(doc_id)
    return context
