from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import numpy as np

from .config import settings
from .vector import DIMENSION, from_blob, to_blob, vectorize

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_fetch_at TEXT NOT NULL DEFAULT '',
    last_status TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feed_items (
    id TEXT PRIMARY KEY,
    source_id TEXT,
    source_type TEXT NOT NULL,
    source_name TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL DEFAULT '',
    retrieved_at TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    value_score REAL NOT NULL DEFAULT 0,
    raw_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'unread',
    repo_full_name TEXT NOT NULL DEFAULT '',
    stars INTEGER NOT NULL DEFAULT 0,
    forks INTEGER NOT NULL DEFAULT 0,
    license TEXT NOT NULL DEFAULT '',
    primary_language TEXT NOT NULL DEFAULT '',
    summary_zh TEXT NOT NULL DEFAULT '',
    translation_zh TEXT NOT NULL DEFAULT '',
    translated INTEGER NOT NULL DEFAULT 0,
    relevance_score REAL NOT NULL DEFAULT 0,
    relevance_reason TEXT NOT NULL DEFAULT '',
    knowledge_gaps TEXT NOT NULL DEFAULT '[]',
    feedback INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feed_status ON feed_items(status, retrieved_at DESC);

CREATE TABLE IF NOT EXISTS github_rankings (
    stack TEXT NOT NULL,
    metric TEXT NOT NULL,
    items TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY(stack, metric)
);

CREATE TABLE IF NOT EXISTS github_star_snapshots (
    stack TEXT NOT NULL,
    repo_full_name TEXT NOT NULL,
    stars INTEGER NOT NULL,
    captured_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY(stack, repo_full_name, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_github_snapshots_lookup
ON github_star_snapshots(stack, captured_at);

CREATE TABLE IF NOT EXISTS patches (
    id TEXT PRIMARY KEY,
    target_path TEXT NOT NULL,
    patch_type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source_refs TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'proposed',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_patches_status ON patches(status, created_at DESC);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    meta TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS documents (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    vector BLOB,
    embedding BLOB,
    embedding_model TEXT NOT NULL DEFAULT '',
    embedding_dim INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_documents_kind ON documents(kind);

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    title,
    content,
    content='documents',
    content_rowid='rowid',
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
    INSERT INTO documents_fts(rowid, title, content)
    VALUES (new.rowid, new.title, new.content);
END;

CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title, content)
    VALUES ('delete', old.rowid, old.title, old.content);
END;

CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title, content)
    VALUES ('delete', old.rowid, old.title, old.content);
    INSERT INTO documents_fts(rowid, title, content)
    VALUES (new.rowid, new.title, new.content);
END;
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    settings.ensure()
    conn = sqlite3.connect(settings.db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
        for name, definition in {
            "vector": "BLOB",
            "embedding": "BLOB",
            "embedding_model": "TEXT NOT NULL DEFAULT ''",
            "embedding_dim": "INTEGER NOT NULL DEFAULT 0",
        }.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {name} {definition}")
        source_columns = {row[1] for row in conn.execute("PRAGMA table_info(sources)")}
        for name, definition in {
            "last_fetch_at": "TEXT NOT NULL DEFAULT ''",
            "last_status": "TEXT NOT NULL DEFAULT ''",
            "last_error": "TEXT NOT NULL DEFAULT ''",
            "source_group": "TEXT NOT NULL DEFAULT 'other'",
            "adapter": "TEXT NOT NULL DEFAULT ''",
            "config_json": "TEXT NOT NULL DEFAULT '{}'",
        }.items():
            if name not in source_columns:
                conn.execute(f"ALTER TABLE sources ADD COLUMN {name} {definition}")
        legacy = {
            "rss": ("other", "rss"),
            "github": ("github", "github_trending"),
            "arxiv": ("other", "arxiv"),
            "devto": ("other", "devto"),
        }
        for kind, (group, adapter) in legacy.items():
            conn.execute(
                "UPDATE sources SET source_group=?, adapter=? "
                "WHERE kind=? AND (adapter='' OR adapter IS NULL)",
                (group, adapter, kind),
            )
        conn.execute(
            "UPDATE sources SET source_group='other', adapter='rss' "
            "WHERE adapter='' OR adapter IS NULL"
        )
        feed_columns = {row[1] for row in conn.execute("PRAGMA table_info(feed_items)")}
        for name, definition in {
            "translation_zh": "TEXT NOT NULL DEFAULT ''",
            "relevance_score": "REAL NOT NULL DEFAULT 0",
            "relevance_reason": "TEXT NOT NULL DEFAULT ''",
            "knowledge_gaps": "TEXT NOT NULL DEFAULT '[]'",
            "feedback": "INTEGER NOT NULL DEFAULT 0",
        }.items():
            if name not in feed_columns:
                conn.execute(f"ALTER TABLE feed_items ADD COLUMN {name} {definition}")
        conn.execute("PRAGMA user_version=1")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _clean_document(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item.pop("vector", None)
    item.pop("embedding", None)
    return item


def upsert_document(
    conn: sqlite3.Connection,
    *,
    doc_id: str,
    kind: str,
    title: str,
    content: str,
    path: str = "",
    source_url: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO documents(doc_id, kind, title, content, path, source_url, updated_at, metadata, vector)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(doc_id) DO UPDATE SET
            kind=excluded.kind,
            title=excluded.title,
            content=excluded.content,
            path=excluded.path,
            source_url=excluded.source_url,
            updated_at=excluded.updated_at,
            metadata=excluded.metadata,
            vector=excluded.vector,
            embedding=CASE
                WHEN documents.title IS NOT excluded.title
                  OR documents.content IS NOT excluded.content
                THEN NULL ELSE documents.embedding END,
            embedding_model=CASE
                WHEN documents.title IS NOT excluded.title
                  OR documents.content IS NOT excluded.content
                THEN '' ELSE documents.embedding_model END,
            embedding_dim=CASE
                WHEN documents.title IS NOT excluded.title
                  OR documents.content IS NOT excluded.content
                THEN 0 ELSE documents.embedding_dim END
        """,
        (
            doc_id,
            kind,
            title,
            content,
            path,
            source_url,
            now_iso(),
            json.dumps(metadata or {}, ensure_ascii=False),
            to_blob(vectorize(f"{title}\n{content}")),
        ),
    )


def delete_document(conn: sqlite3.Connection, doc_id: str) -> None:
    conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))


def _search_terms(text: str) -> list[str]:
    text = text or ""
    latin = re.findall(r"[A-Za-z0-9_+#.\-]{2,}", text)
    chinese = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    stop = {
        "什么", "怎么", "如何", "为什么", "这个", "那个", "可以", "需要",
        "一个", "哪些", "以及", "然后", "还是", "就是", "的是", "了吗",
    }
    specific: list[str] = []
    general: list[str] = []
    for token in latin:
        token = token.strip(".-").lower()
        if len(token) >= 2:
            (specific if any(char.isdigit() for char in token) else general).append(token)
    for sequence in chinese:
        for size in (4, 3, 2):
            for index in range(0, len(sequence) - size + 1):
                term = sequence[index : index + size]
                if term in stop:
                    continue
                (specific if size >= 3 else general).append(term)
    deduped: list[str] = []
    for term in specific + general:
        if term not in deduped:
            deduped.append(term)
    return deduped[:32]


def _fts_query(text: str) -> str:
    terms = _search_terms(text)
    if not terms:
        return ""
    specific = _specific_terms(terms)
    general = [term for term in terms if term not in specific]
    selected = (specific[:4] + general[:4])[:8]
    return " OR ".join(f'"{term}"' for term in selected)


def _like_fallback(conn: sqlite3.Connection, query: str, limit: int) -> list[sqlite3.Row]:
    terms = _search_terms(query)[:6]
    if not terms:
        terms = [query]
    clauses = []
    params: list[Any] = []
    for term in terms:
        clauses.append("(title LIKE ? OR content LIKE ?)")
        like = f"%{term}%"
        params.extend([like, like])
    sql = f"""
        SELECT *, substr(content, 1, 220) AS snippet
        FROM documents
        WHERE {' OR '.join(clauses)}
        ORDER BY updated_at DESC
        LIMIT ?
    """
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def _specific_terms(terms: list[str]) -> list[str]:
    specific = []
    for term in terms:
        has_chinese = any("\u4e00" <= char <= "\u9fff" for char in term)
        has_digit = any(char.isdigit() for char in term)
        if (has_chinese and len(term) >= 3) or has_digit:
            specific.append(term)
    return specific


def _rerank(rows: list[sqlite3.Row], query: str, limit: int) -> list[dict[str, Any]]:
    terms = _search_terms(query)
    if not terms:
        return [_clean_document(row) for row in rows[:limit]]
    specific = _specific_terms(terms)
    if specific:
        filtered = [
            row for row in rows
            if any(
                term.lower() in f"{row['title']} {row['content']}".lower()
                for term in specific
            )
        ]
        if filtered:
            rows = filtered
    scored = []
    for index, row in enumerate(rows):
        title = str(row["title"] or "").lower()
        content = str(row["content"] or "").lower()
        score = 0
        for term in terms:
            term = term.lower()
            weight = 2 if term in specific else 1
            if term in title:
                score += 6 * weight
            score += min(content.count(term), 4) * weight
        scored.append((score, -index, row))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [_clean_document(row) for _, _, row in scored[:limit]]


def search_documents(query: str, limit: int = 8) -> list[dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM documents ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_clean_document(row) for row in rows]

    escaped = _fts_query(query)
    pool = max(limit * 4, 16)
    rows: list[sqlite3.Row] = []
    if escaped:
        with db() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT d.*, snippet(documents_fts, 1, '<mark>', '</mark>', '…', 18) AS snippet
                    FROM documents_fts
                    JOIN documents d ON d.rowid = documents_fts.rowid
                    WHERE documents_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (escaped, pool),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []

    if not rows:
        with db() as conn:
            rows = _like_fallback(conn, query, pool)
    return _rerank(rows, query, limit)


def vector_search(query: str, limit: int = 8) -> list[dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return []
    query_vector = vectorize(query)
    with db() as conn:
        rows = conn.execute(
            "SELECT doc_id, vector FROM documents WHERE vector IS NOT NULL"
        ).fetchall()
    vectors = []
    ids = []
    for row in rows:
        blob = row["vector"]
        if not blob or len(blob) != DIMENSION * 4:
            continue
        vectors.append(from_blob(blob))
        ids.append(row["doc_id"])
    if not vectors:
        return []
    matrix = np.stack(vectors)
    scores = matrix @ query_vector
    order = np.argsort(-scores)[: max(limit, 1)]
    results = []
    for index in order:
        score = float(scores[index])
        if score <= 0.03:
            continue
        results.append({"doc_id": ids[index], "score": score})
    return results


def get_documents_by_ids(doc_ids: list[str]) -> list[dict[str, Any]]:
    if not doc_ids:
        return []
    placeholders = ",".join("?" for _ in doc_ids)
    with db() as conn:
        rows = conn.execute(
            f"SELECT * FROM documents WHERE doc_id IN ({placeholders})", doc_ids
        ).fetchall()
    by_id = {row["doc_id"]: _clean_document(row) for row in rows}
    return [by_id[doc_id] for doc_id in doc_ids if doc_id in by_id]


def record_run(
    *,
    run_id: str,
    task_type: str,
    provider: str,
    model: str,
    status: str,
    error: str = "",
    started_at: str | None = None,
    finished_at: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO runs(id, task_type, provider, model, status, error, started_at, finished_at, meta)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,
                error=excluded.error,
                finished_at=excluded.finished_at,
                meta=excluded.meta
            """,
            (
                run_id,
                task_type,
                provider,
                model,
                status,
                error,
                started_at or now_iso(),
                finished_at or "",
                json.dumps(meta or {}, ensure_ascii=False),
            ),
        )


def stats() -> dict[str, int]:
    with db() as conn:
        def count(sql: str, params: tuple = ()) -> int:
            row = conn.execute(sql, params).fetchone()
            return int(row[0]) if row else 0

        return {
            "feed": count("SELECT COUNT(*) FROM feed_items"),
            "saved": count("SELECT COUNT(*) FROM feed_items WHERE status='saved'"),
            "notes": count("SELECT COUNT(*) FROM documents WHERE kind='note'"),
            "patches": count("SELECT COUNT(*) FROM patches WHERE status='proposed'"),
            "runs": count("SELECT COUNT(*) FROM runs"),
        }


def expire_patches() -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    with db() as conn:
        conn.execute(
            """
            UPDATE patches
            SET status='expired'
            WHERE status='proposed'
              AND patch_type != 'conflict'
              AND created_at < ?
            """,
            (cutoff,),
        )
