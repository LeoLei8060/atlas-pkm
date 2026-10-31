from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
import numpy as np

from ..config import load_config
from ..db import _search_terms, _specific_terms, db, get_documents_by_ids
from ..vector import DIMENSION, vectorize


class EmbeddingError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


DEFAULTS = {
    "local": ("local-ngram", ""),
    "openai": ("text-embedding-3-small", "https://api.openai.com/v1"),
    "gemini": ("text-embedding-004", "https://generativelanguage.googleapis.com/v1beta"),
    "ollama": ("bge-m3", "http://127.0.0.1:11434"),
}


@asynccontextmanager
async def _http(client: httpx.AsyncClient | None) -> AsyncIterator[httpx.AsyncClient]:
    if client is not None:
        yield client
        return
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(120.0, connect=15.0), trust_env=False
    ) as owned:
        yield owned


def embedding_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_config()
    return dict(config.get("embedding") or {})


def provider_name(config: dict[str, Any]) -> str:
    return str(embedding_config(config).get("provider") or "local")


def model_name(config: dict[str, Any]) -> str:
    item = embedding_config(config)
    provider = provider_name(config)
    return str(item.get("model") or DEFAULTS.get(provider, ("", ""))[0])


def base_url(config: dict[str, Any]) -> str:
    item = embedding_config(config)
    provider = provider_name(config)
    return str(item.get("base_url") or DEFAULTS.get(provider, ("", ""))[1]).rstrip("/")


def is_external(config: dict[str, Any]) -> bool:
    return provider_name(config) != "local"


async def embed_texts(
    texts: list[str],
    config: dict[str, Any] | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[list[list[float]], str, int]:
    config = config or load_config()
    provider = provider_name(config)
    model = model_name(config)
    base = base_url(config)
    key = str(embedding_config(config).get("api_key") or "").strip()
    texts = [text or "" for text in texts]

    if provider == "local":
        vectors = [vectorize(text).tolist() for text in texts]
        return vectors, "local-ngram", DIMENSION

    if provider not in DEFAULTS:
        raise EmbeddingError(f"不支持的 embedding provider: {provider}", 400)
    if provider != "ollama" and not key:
        raise EmbeddingError("embedding API Key 未配置", 400)

    vectors: list[list[float]] = []
    async with _http(client) as http:
        if provider == "openai":
            response = await http.post(
                f"{base}/embeddings",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": model, "input": texts},
            )
            if response.status_code >= 400:
                raise EmbeddingError(_error_text(response), response.status_code)
            data = response.json().get("data") or []
            ordered = sorted(data, key=lambda item: item.get("index", 0))
            vectors = [list(item.get("embedding") or []) for item in ordered]
        elif provider == "gemini":
            for text in texts:
                response = await http.post(
                    f"{base}/models/{model}:embedContent",
                    params={"key": key},
                    json={"content": {"parts": [{"text": text}]}},
                )
                if response.status_code >= 400:
                    raise EmbeddingError(_error_text(response), response.status_code)
                values = (response.json().get("embedding") or {}).get("values") or []
                vectors.append(list(values))
        elif provider == "ollama":
            for text in texts:
                response = await http.post(
                    f"{base}/api/embeddings",
                    json={"model": model, "prompt": text},
                )
                if response.status_code >= 400:
                    raise EmbeddingError(_error_text(response), response.status_code)
                vectors.append(list(response.json().get("embedding") or []))

    if len(vectors) != len(texts) or not vectors or not vectors[0]:
        raise EmbeddingError("embedding 返回数量或维度为空")
    dimension = len(vectors[0])
    if any(len(vector) != dimension for vector in vectors):
        raise EmbeddingError("embedding 维度不一致")
    return vectors, model, dimension


def _error_text(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                return f"{response.status_code}: {error.get('message') or error}"
            return f"{response.status_code}: {payload.get('message') or payload}"
    except Exception:
        pass
    return f"{response.status_code}: {response.text[:300]}"


async def embed_query(
    text: str, config: dict[str, Any] | None = None
) -> tuple[list[float], str, int]:
    vectors, model, dimension = await embed_texts([text], config)
    return vectors[0], model, dimension


async def rebuild_embeddings(
    config: dict[str, Any] | None = None,
    *,
    batch_size: int = 8,
    max_docs: int = 500,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    provider = provider_name(config)
    if provider == "local":
        with db() as conn:
            total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        return {
            "provider": "local",
            "model": "local-ngram",
            "dimension": DIMENSION,
            "indexed": int(total),
            "skipped": 0,
        }

    with db() as conn:
        rows = conn.execute(
            "SELECT doc_id, title, content FROM documents ORDER BY updated_at DESC LIMIT ?",
            (max_docs,),
        ).fetchall()
    indexed = 0
    model = model_name(config)
    dimension = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        texts = [f"{row['title']}\n{row['content']}" for row in batch]
        vectors, model, dimension = await embed_texts(texts, config, client=client)
        with db() as conn:
            for row, vector in zip(batch, vectors):
                conn.execute(
                    """
                    UPDATE documents
                    SET embedding=?, embedding_model=?, embedding_dim=?
                    WHERE doc_id=?
                    """,
                    (
                        np.asarray(vector, dtype=np.float32).tobytes(),
                        model,
                        dimension,
                        row["doc_id"],
                    ),
                )
                indexed += 1
    return {
        "provider": provider,
        "model": model,
        "dimension": dimension,
        "indexed": indexed,
        "skipped": max(0, len(rows) - indexed),
    }


async def semantic_search(
    query: str,
    config: dict[str, Any] | None = None,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    config = config or load_config()
    if not is_external(config):
        return []
    try:
        query_vector, model, dimension = await embed_query(query, config)
    except Exception:
        return []
    query_array = np.asarray(query_vector, dtype=np.float32)
    norm = float(np.linalg.norm(query_array))
    if norm == 0:
        return []
    query_array /= norm

    with db() as conn:
        rows = conn.execute(
            """
            SELECT doc_id, embedding FROM documents
            WHERE embedding IS NOT NULL AND embedding_model=? AND embedding_dim=?
            """,
            (model, dimension),
        ).fetchall()
    scored: list[tuple[float, str]] = []
    for row in rows:
        blob = row["embedding"]
        if not blob or len(blob) != dimension * 4:
            continue
        vector = np.frombuffer(blob, dtype=np.float32)
        score = float(np.dot(vector, query_array))
        if score > 0.05:
            scored.append((score, row["doc_id"]))
    scored.sort(reverse=True)
    docs = {doc["doc_id"]: doc for doc in get_documents_by_ids([doc_id for _, doc_id in scored[: limit * 2]])}
    specific = _specific_terms(_search_terms(query))
    results = []
    for score, doc_id in scored:
        doc = docs.get(doc_id)
        if doc is None:
            continue
        if specific:
            haystack = f"{doc.get('title', '')} {doc.get('content', '')}".lower()
            if not any(term.lower() in haystack for term in specific):
                continue
        results.append({**doc, "score": score})
        if len(results) >= limit:
            break
    return results


async def embed_pending(
    config: dict[str, Any] | None = None,
    *,
    batch_size: int = 8,
    max_docs: int = 100,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    provider = provider_name(config)
    model = model_name(config)
    if provider == "local":
        return {"provider": "local", "model": "local-ngram", "indexed": 0, "pending": 0}
    with db() as conn:
        rows = conn.execute(
            """
            SELECT doc_id, title, content FROM documents
            WHERE embedding IS NULL OR embedding_model != ? OR embedding_dim=0
            ORDER BY updated_at DESC LIMIT ?
            """,
            (model, max(1, max_docs)),
        ).fetchall()
    indexed = 0
    dimension = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        texts = [f"{row['title']}\n{row['content']}" for row in batch]
        vectors, model, dimension = await embed_texts(texts, config, client=client)
        with db() as conn:
            for row, vector in zip(batch, vectors):
                conn.execute(
                    """
                    UPDATE documents
                    SET embedding=?, embedding_model=?, embedding_dim=?
                    WHERE doc_id=?
                    """,
                    (
                        np.asarray(vector, dtype=np.float32).tobytes(),
                        model,
                        dimension,
                        row["doc_id"],
                    ),
                )
                indexed += 1
    with db() as conn:
        pending = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM documents
                WHERE embedding IS NULL OR embedding_model != ? OR embedding_dim=0
                """,
                (model,),
            ).fetchone()[0]
        )
    return {
        "provider": provider,
        "model": model,
        "dimension": dimension,
        "indexed": indexed,
        "pending": pending,
    }


_incremental_task: asyncio.Task | None = None
_incremental_state: dict[str, Any] = {
    "running": False,
    "indexed": 0,
    "pending": 0,
    "started_at": "",
    "last_error": "",
}


def incremental_status() -> dict[str, Any]:
    result = dict(_incremental_state)
    try:
        result["pending"] = status().get("pending_documents", 0)
    except Exception:
        pass
    return result


async def _run_incremental(config: dict[str, Any], max_docs: int) -> None:
    global _incremental_task
    _incremental_state.update(
        {
            "running": True,
            "indexed": 0,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "last_error": "",
        }
    )
    try:
        result = await embed_pending(config, max_docs=max_docs)
        _incremental_state.update(
            {
                "running": False,
                "indexed": result.get("indexed", 0),
                "pending": result.get("pending", 0),
            }
        )
    except Exception as exc:
        _incremental_state.update({"running": False, "last_error": str(exc)[:400]})
    finally:
        _incremental_task = None


def start_incremental(
    config: dict[str, Any] | None = None, *, max_docs: int = 100
) -> dict[str, Any]:
    global _incremental_task
    config = config or load_config()
    if provider_name(config) == "local":
        return {**incremental_status(), "skipped": True, "reason": "local embedding"}
    if _incremental_task is not None and not _incremental_task.done():
        return incremental_status()
    _incremental_task = asyncio.create_task(
        _run_incremental(config, max(1, min(max_docs, 500))),
        name="pkm-embedding-incremental",
    )
    return incremental_status()


def status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_config()
    provider = provider_name(config)
    model = model_name(config)
    with db() as conn:
        total = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        indexed = int(
            conn.execute(
                "SELECT COUNT(*) FROM documents WHERE embedding_model=? AND embedding IS NOT NULL",
                (model,),
            ).fetchone()[0]
        )
        pending = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM documents
                WHERE embedding IS NULL OR embedding_model != ? OR embedding_dim=0
                """,
                (model,),
            ).fetchone()[0]
        )
    return {
        "provider": provider,
        "model": model,
        "base_url": base_url(config),
        "external": provider != "local",
        "total_documents": total,
        "indexed_documents": total if provider == "local" else indexed,
        "pending_documents": 0 if provider == "local" else pending,
        "dimension": DIMENSION if provider == "local" else None,
    }

