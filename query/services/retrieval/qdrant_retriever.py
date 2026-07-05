from __future__ import annotations

import asyncio
import time
from typing import Optional

from ingestion.storage.qdrant_client import QdrantVectorStore
from query.models.query import RetrievalQuery, RetrievalSource
from query.models.result import RetrievedChunk, RetrievalResult

from .base_retriever import BaseRetriever


class QdrantRetriever(BaseRetriever):
    """
    Dense vector retrieval over Qdrant (BGE-M3 COSINE, 1024-dim).

    Requires query.query_embedding to be pre-computed before calling retrieve().
    Enforces org / knowledge-base / approval filters via Qdrant payload filters.
    Scores returned by Qdrant COSINE are already in [0, 1]; no normalisation needed.
    """

    def __init__(self, store: Optional[QdrantVectorStore] = None) -> None:
        self._store = store or QdrantVectorStore()

    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        if query.query_embedding is None:
            return RetrievalResult(
                source=RetrievalSource.QDRANT,
                error="query_embedding is required for Qdrant retrieval — embed the query first",
            )

        start = time.monotonic()
        try:
            raw = await asyncio.to_thread(
                self._store.search,
                query_vector      = query.query_embedding,
                organization_id   = query.organization_id,
                knowledge_base_id = query.knowledge_base_id,
                limit             = query.top_k,
                role_filter       = None,   # roles not stored in ingest payload
                risk_levels       = None,   # risk_level not stored in ingest payload
            )
        except Exception as exc:
            return RetrievalResult(
                source     = RetrievalSource.QDRANT,
                latency_ms = (time.monotonic() - start) * 1000,
                error      = str(exc),
            )

        _skip = {"chunk_id", "document_id", "score", "text", "content_preview"}
        chunks = [
            RetrievedChunk(
                chunk_id    = r["chunk_id"],
                document_id = r["document_id"],
                content     = r.get("text") or r.get("content_preview", ""),
                score       = float(r["score"]),
                rank        = idx,
                source      = RetrievalSource.QDRANT,
                metadata    = {k: v for k, v in r.items() if k not in _skip},
            )
            for idx, r in enumerate(raw)
            if float(r.get("score", 0.0)) >= query.min_score
        ]

        return RetrievalResult(
            source     = RetrievalSource.QDRANT,
            chunks     = chunks,
            latency_ms = (time.monotonic() - start) * 1000,
        )

    def health_check(self) -> bool:
        try:
            self._store._client.get_collections()
            return True
        except Exception:
            return False
