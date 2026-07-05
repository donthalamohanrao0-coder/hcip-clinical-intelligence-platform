from __future__ import annotations

import time
from typing import Optional

from ingestion.config import get_settings
from query.models.query import RetrievalQuery
from query.models.result import FusedResult

from .cache_config import CacheHit, CacheKeys, get_async_redis


class RetrievalCache:
    """
    Layer 3 — Retrieval results cache.

    Caches the full FusedResult from HybridRetriever, keyed by a hash of the
    query embedding bytes + org/KB.  When the same (or identical) query embedding
    is seen again within 30 minutes, the 4-source retrieval is skipped entirely.

    Requires query.query_embedding to be set.
    Key:  sha256(embedding_float32_bytes)  scoped to org + KB
    TTL:  30 minutes
    """

    def __init__(self) -> None:
        self._ttl = get_settings().cache_retrieval_ttl_seconds

    async def get(self, query: RetrievalQuery) -> Optional[CacheHit]:
        if query.query_embedding is None:
            return None

        start = time.monotonic()
        r     = await get_async_redis()
        key   = CacheKeys.retrieval(
            query.organization_id,
            query.knowledge_base_id,
            query.query_embedding,
        )
        raw = await r.get(key)
        if raw is None:
            return None

        return CacheHit(
            fused_result = FusedResult.model_validate_json(raw),
            layer        = "retrieval",
            latency_ms   = (time.monotonic() - start) * 1000,
        )

    async def set(self, query: RetrievalQuery, result: FusedResult) -> None:
        if query.query_embedding is None:
            return
        r   = await get_async_redis()
        key = CacheKeys.retrieval(
            query.organization_id,
            query.knowledge_base_id,
            query.query_embedding,
        )
        await r.setex(key, self._ttl, result.model_dump_json())
