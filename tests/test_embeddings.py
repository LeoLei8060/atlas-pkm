from __future__ import annotations

from app.services import embeddings
from app.services.demo import seed_demo


def test_incremental_local_skips(isolated):
    seed_demo()
    result = embeddings.start_incremental({"embedding": {"provider": "local"}})
    assert result["skipped"] is True
    assert result["reason"] == "local embedding"


def test_local_embedding_status(isolated):
    seed_demo()
    status = embeddings.status({"embedding": {"provider": "local"}})
    assert status["provider"] == "local"
    assert status["model"] == "local-ngram"
    assert status["indexed_documents"] == status["total_documents"]
    assert status["dimension"] == 2048
