from __future__ import annotations

import time
from typing import Optional

from query.models.query import RetrievalQuery
from query.models.result import FusedResult

from .cache_config import CacheHit
from .embedding_cache import EmbeddingCache
from .exact_cache import ExactCache
from .retrieval_cache import RetrievalCache
from .semantic_cache import SemanticCache


class CachePipeline:
    """
    4-layer cache for the HCIP query pipeline.

    Check order on reads (fastest / cheapest first):
        L1 Exact     → O(1) Redis GET, no embedding required
        L4 Embedding → O(1) Redis GET, populates query_embedding for L2 + L3
        L2 Semantic  → Qdrant ANN search (cosine ≥ 0.95) + Redis GET
        L3 Retrieval → O(1) Redis GET keyed by embedding hash

    Write order on cache population (after successful retrieval):
        L4 → L1 → L2 → L3  (embedding first so semantic lookup is primed)

    Usage
    -----
    # In the Planner Agent (Phase 16):
    cache = CachePipeline()

    hit = await cache.get(query)
    if hit:
        return hit.fused_result   # served from cache

    embedding = await cache.get_embedding(query.query_text)
    if embedding is None:
        embedding = await embed(query.query_text)    # your embedding service
        await cache.set_embedding(query.query_text, embedding)

    query = query.model_copy(update={"query_embedding": embedding})

    hit = await cache.get_with_embedding(query)
    if hit:
        return hit.fused_result

    fused = await hybrid_retriever.retrieve(query)
    await cache.set(query, fused)
    return fused
    """

    def __init__(
        self,
        exact_cache:     Optional[ExactCache]     = None,
        semantic_cache:  Optional[SemanticCache]  = None,
        retrieval_cache: Optional[RetrievalCache] = None,
        embedding_cache: Optional[EmbeddingCache] = None,
    ) -> None:
        self._exact     = exact_cache     or ExactCache()
        self._semantic  = semantic_cache  or SemanticCache()
        self._retrieval = retrieval_cache or RetrievalCache()
        self._embedding = embedding_cache or EmbeddingCache()

    # ── Read helpers ──────────────────────────────────────────────────────────

    async def get(self, query: RetrievalQuery) -> Optional[CacheHit]:
        """
        Check L1 only (no embedding needed).
        Call get_with_embedding() after attaching the query embedding.
        """
        return await self._exact.get(query)

    async def get_with_embedding(self, query: RetrievalQuery) -> Optional[CacheHit]:
        """
        Check L2 + L3 (requires query.query_embedding to be set).
        Call get() first for the L1 check.
        """
        hit = await self._semantic.get(query)
        if hit:
            return hit

        return await self._retrieval.get(query)

    async def get_embedding(self, query_text: str) -> Optional[list[float]]:
        """Return a cached query embedding, or None on L4 miss."""
        return await self._embedding.get(query_text)

    # ── Write helpers ─────────────────────────────────────────────────────────

    async def set_embedding(self, query_text: str, embedding: list[float]) -> None:
        """Populate L4 after computing a fresh embedding."""
        await self._embedding.set(query_text, embedding)

    async def set(self, query: RetrievalQuery, result: FusedResult) -> None:
        """
        Populate L1, L2, L3 after a successful retrieval.
        query.query_embedding must be set before calling.
        All three writes run concurrently; any individual failure is silently
        ignored so a cache write error never breaks the query path.
        """
        import asyncio

        async def _safe(coro):
            try:
                await coro
            except Exception:
                pass

        await asyncio.gather(
            _safe(self._exact.set(query, result)),
            _safe(self._semantic.set(query, result)),
            _safe(self._retrieval.set(query, result)),
        )

    # ── Health ────────────────────────────────────────────────────────────────

    async def health_check(self) -> dict[str, bool]:
        from .cache_config import get_async_redis
        try:
            r   = await get_async_redis()
            ok  = await r.ping()
        except Exception:
            ok = False
        return {"redis": ok}
