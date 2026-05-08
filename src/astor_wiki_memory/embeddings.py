from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from .text import tokenize


@dataclass(frozen=True)
class HashingEmbedder:
    """Local deterministic vector backend.

    This is not a replacement for a frontier embedding model, but it gives the
    memory core a quota-free vector path and keeps the backend pluggable.
    """

    dimensions: int = 384

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        terms = tokenize(text)
        for term in terms:
            digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            idx = value % self.dimensions
            sign = 1.0 if (value >> 1) & 1 else -1.0
            vec[idx] += sign

        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return vec
        return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def create_embedder(backend: str = "hashing", dimensions: int = 384) -> HashingEmbedder:
    if backend != "hashing":
        raise ValueError(f"Unsupported embedding backend for MVP: {backend}")
    return HashingEmbedder(dimensions=dimensions)

