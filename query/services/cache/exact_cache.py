from __future__ import annotations

import time
from typing import Optional

from ingestion.config import get_settings
from query.models.query import RetrievalQuery
from query.models.result import FusedResult

from .cache_config import CacheHit, CacheKeys, get_async_redis


class ExactCache:
    """
    Layer 1 — Exact match cache.

    Fastest possible hit: the byte-identical query string (normalised to
    lowercase + stripped) was seen before for the same org + knowledge base.
    No embedding needed — pure Redis GET/SET on a SHA-256 key.

    Key:  sha256(query_text.lower().strip())  scoped to org + KB
    TTL:  1 hour
    """

    def __init__(self) -> None:
        self._ttl = get_settings().cache_exact_ttl_seconds

    async def get(self, query: RetrievalQuery) -> Optional[CacheHit]:
        start = time.monotonic()
        r     = await get_async_redis()
        key   = CacheKeys.exact(
            query.organization_id,
            query.knowledge_base_id,
            query.query_text,
        )
        raw = await r.get(key)
        if raw is None:
            return None

        return CacheHit(
            fused_result = FusedResult.model_validate_json(raw),
            layer        = "exact",
            latency_ms   = (time.monotonic() - start) * 1000,
        )

    async def set(self, query: RetrievalQuery, result: FusedResult) -> None:
        r   = await get_async_redis()
        key = CacheKeys.exact(
            query.organization_id,
            query.knowledge_base_id,
            query.query_text,
        )
        await r.setex(key, self._ttl, result.model_dump_json())
