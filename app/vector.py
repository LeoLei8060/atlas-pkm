from __future__ import annotations

import hashlib
import math
import re
from typing import Any

import numpy as np

DIMENSION = 2048


def _tokens(text: str) -> list[str]:
    text = (text or "").lower()
    words = re.findall(r"[a-z0-9_+#.\-]{2,}", text)
    chinese = re.findall(r"[\u4e00-\u9fff]+", text)
    grams: list[str] = []
    for sequence in chinese:
        for size in (2, 3):
            grams.extend(
                sequence[index : index + size]
                for index in range(0, len(sequence) - size + 1)
            )
    return words + grams


def vectorize(text: str, dimension: int = DIMENSION) -> np.ndarray:
    vector = np.zeros(dimension, dtype=np.float32)
    counts: dict[int, int] = {}
    for token in _tokens(text):
        digest = hashlib.md5(token.encode("utf-8")).hexdigest()[:8]
        index = int(digest, 16) % dimension
        counts[index] = counts.get(index, 0) + 1
    for index, count in counts.items():
        vector[index] = 1.0 + math.log(count)
    norm = float(np.linalg.norm(vector))
    if norm > 0:
        vector /= norm
    return vector.astype(np.float32)


def to_blob(vector: np.ndarray) -> bytes:
    return vector.astype(np.float32).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def cosine(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.dot(left, right))
