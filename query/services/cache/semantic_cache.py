from __future__ import annotations

import asyncio
import time
import uuid
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from ingestion.config import get_settings
from query.models.query import RetrievalQuery
from query.models.result import FusedResult

from .cache_config import CacheHit, CacheKeys, get_async_redis


class SemanticCache:
    """
    Layer 2 — Semantic similarity cache.

    Stores past query embeddings in a dedicated Qdrant collection
    (hcip_query_cache).  On every new query, searches for a similar past query
    above the cosine threshold (default 0.95).  If found, fetches the cached
    FusedResult from Redis using the key stored in the Qdrant point payload.

    When the Redis TTL has expired the Qdrant entry is stale but harmless —
    the Redis GET returns None and the lookup falls through as a cache miss.

    Requires query.query_embedding to be set.
    Key:  hcip:q:semantic:{uuid4}  (stored as Qdrant point payload → redis_key)
    TTL:  1 hour (Redis side)
    """

    def __init__(self, qdrant: Optional[QdrantClient] = None) -> None:
        cfg                = get_settings()
        self._qdrant       = qdrant or QdrantClient(
            host    = cfg.qdrant_host,
            port    = cfg.qdrant_port,
            api_key = cfg.qdrant_api_key or None,
        )
        self._collection   = cfg.qdrant_query_cache_collection
        self._threshold    = cfg.cache_semantic_threshold
        self._ttl          = cfg.cache_semantic_ttl_seconds
        self._vector_dim   = cfg.embedding_vector_dim

    # ── Collection bootstrap ──────────────────────────────────────────────────

    def _ensure_collection(self) -> None:
        if not self._qdrant.collection_exists(self._collection):
            self._qdrant.create_collection(
                collection_name = self._collection,
                vectors_config  = VectorParams(
                    size     = self._vector_dim,
                    distance = Distance.COSINE,
                ),
            )

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get(self, query: RetrievalQuery) -> Optional[CacheHit]:
        if query.query_embedding is None:
            return None

        start = time.monotonic()
        try:
            hits = await asyncio.to_thread(
                self._qdrant.search,
                collection_name  = self._collection,
                query_vector     = query.query_embedding,
                query_filter     = Filter(must=[
                    FieldCondition(key="org_id", match=MatchValue(value=query.organization_id)),
                    FieldCondition(key="kb_id",  match=MatchValue(value=query.knowledge_base_id)),
                ]),
                limit            = 1,
                with_payload     = True,
                score_threshold  = self._threshold,
            )
        except Exception:
            return None

        if not hits:
            return None

        redis_key: Optional[str] = hits[0].payload.get("redis_key")
        if not redis_key:
            return None

        r   = await get_async_redis()
        raw = await r.get(redis_key)
        if raw is None:
            return None   # TTL expired in Redis — graceful miss

        return CacheHit(
            fused_result = FusedResult.model_validate_json(raw),
            layer        = "semantic",
            latency_ms   = (time.monotonic() - start) * 1000,
        )

    # ── Write ─────────────────────────────────────────────────────────────────

    async def set(self, query: RetrievalQuery, result: FusedResult) -> None:
        if query.query_embedding is None:
            return

        cache_id  = str(uuid.uuid4())
        redis_key = CacheKeys.semantic(cache_id)

        # Redis first so the key exists before Qdrant indexes it
        r = await get_async_redis()
        await r.setex(redis_key, self._ttl, result.model_dump_json())

        await asyncio.to_thread(self._ensure_collection)
        await asyncio.to_thread(
            self._qdrant.upsert,
            collection_name = self._collection,
            points          = [
                PointStruct(
                    id      = cache_id,
                    vector  = query.query_embedding,
                    payload = {
                        "redis_key":  redis_key,
                        "query_text": query.query_text,
                        "org_id":     query.organization_id,
                        "kb_id":      query.knowledge_base_id,
                    },
                )
            ],
        )
