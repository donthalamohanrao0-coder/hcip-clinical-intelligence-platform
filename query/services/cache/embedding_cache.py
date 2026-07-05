from __future__ import annotations

import json
from typing import Optional

from ingestion.config import get_settings

from .cache_config import CacheKeys, get_async_redis


class EmbeddingCache:
    """
    Layer 4 — Query embedding cache.

    Avoids re-running BGE-M3 inference for the same query text.
    Key:  sha256(query_text.lower())
    TTL:  24 hours  (embedding_cache_ttl_seconds — shared with ingestion embedding cache)

    On hit: returns list[float] ready to attach to RetrievalQuery.query_embedding.
    """

    def __init__(self) -> None:
        self._ttl = get_settings().embedding_cache_ttl_seconds

    async def get(self, query_text: str) -> Optional[list[float]]:
        r   = await get_async_redis()
        raw = await r.get(CacheKeys.embedding(query_text))
        if raw is None:
            return None
        return json.loads(raw)

    async def set(self, query_text: str, embedding: list[float]) -> None:
        r = await get_async_redis()
        await r.setex(
            CacheKeys.embedding(query_text),
            self._ttl,
            json.dumps(embedding),
        )
