"""
Async node functions for the Retriever Agent.

Graph:
    START → execute_retrieval → enrich_content → rerank → populate_cache → END
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Optional

from query.agents.state import RAGState
from query.models.query import RetrievalQuery, RetrievalSource
from query.models.result import FusedResult, RetrievedChunk
from query.services.cache import CachePipeline
from query.services.retrieval import HybridRetriever

# ── UUID pattern — only valid chunk IDs can be fetched from Qdrant ────────────
_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I
)

# ── Module-level singletons ───────────────────────────────────────────────────
_hybrid_retriever: Optional[HybridRetriever] = None
_cache_pipeline:   Optional[CachePipeline]   = None
_cross_encoder                               = "unavailable"   # disabled: model not pre-downloaded on EC2; RRF order is sufficient


def _get_retriever() -> HybridRetriever:
    global _hybrid_retriever
    if _hybrid_retriever is None:
        _hybrid_retriever = HybridRetriever()
    return _hybrid_retriever


def _get_cache() -> CachePipeline:
    global _cache_pipeline
    if _cache_pipeline is None:
        _cache_pipeline = CachePipeline()
    return _cache_pipeline


def _get_cross_encoder():
    """Lazy load cross-encoder; returns None when sentence-transformers is absent."""
    global _cross_encoder
    if _cross_encoder is not None:
        return None if _cross_encoder == "unavailable" else _cross_encoder
    try:
        from sentence_transformers import CrossEncoder
        _cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    except Exception:
        _cross_encoder = "unavailable"
    return None if _cross_encoder == "unavailable" else _cross_encoder


# ── Node 1: Execute multi-source retrieval ────────────────────────────────────

async def execute_retrieval_node(state: RAGState) -> dict:
    start      = time.monotonic()
    query_dict = state.get("retrieval_query")

    if not query_dict:
        return {
            "errors":        ["retrieval_query missing from state — PlannerAgent must run first"],
            "agent_timings": {"retriever.execute_ms": 0.0},
        }

    try:
        query    = RetrievalQuery(**query_dict)
        retriever = _get_retriever()
        fused    = await retriever.retrieve(query)
    except Exception as exc:
        return {
            "errors":        [f"HybridRetriever failed: {exc}"],
            "agent_timings": {"retriever.execute_ms": (time.monotonic() - start) * 1000},
        }

    source_errors = [
        f"{src}: {res.error}"
        for src, res in fused.source_results.items()
        if res.error
    ]

    return {
        "fused_result":     fused.model_dump(),
        "retrieved_chunks": [c.model_dump() for c in fused.chunks],
        "errors":           source_errors,
        "agent_timings":    {"retriever.execute_ms": (time.monotonic() - start) * 1000},
    }


# ── Node 2: Enrich Neo4j placeholder content from Qdrant ─────────────────────

async def enrich_content_node(state: RAGState) -> dict:
    start  = time.monotonic()
    raw    = state.get("retrieved_chunks", [])
    chunks = [RetrievedChunk(**c) for c in raw]

    neo4j_ids = [
        c.chunk_id
        for c in chunks
        if c.source == RetrievalSource.NEO4J
        and c.content.startswith("[Graph match]")
        and _UUID_RE.match(c.chunk_id)
    ]

    if not neo4j_ids:
        return {"agent_timings": {"retriever.enrich_ms": (time.monotonic() - start) * 1000}}

    try:
        content_map = await asyncio.to_thread(_fetch_qdrant_content, neo4j_ids)
    except Exception:
        content_map = {}

    enriched = [
        c.model_copy(update={"content": content_map[c.chunk_id]})
        if c.chunk_id in content_map and c.content.startswith("[Graph match]")
        else c
        for c in chunks
    ]

    return {
        "retrieved_chunks": [c.model_dump() for c in enriched],
        "agent_timings":    {"retriever.enrich_ms": (time.monotonic() - start) * 1000},
    }


def _fetch_qdrant_content(chunk_ids: list[str]) -> dict[str, str]:
    """Synchronous: fetch content_preview payloads from Qdrant by chunk IDs."""
    from ingestion.config import get_settings
    from ingestion.storage.qdrant_client import QdrantVectorStore

    cfg   = get_settings()
    store = QdrantVectorStore()
    result: dict[str, str] = {}

    for collection in (cfg.qdrant_text_collection, cfg.qdrant_table_collection):
        try:
            points = store._client.retrieve(
                collection_name = collection,
                ids             = chunk_ids,
                with_payload    = True,
            )
            for pt in points:
                if pt.payload:
                    cid     = pt.payload.get("chunk_id")
                    preview = pt.payload.get("text") or pt.payload.get("content_preview", "")
                    if cid and preview:
                        result[cid] = preview
        except Exception:
            pass

    return result


# ── Node 3: Cross-encoder re-ranking ─────────────────────────────────────────

async def rerank_node(state: RAGState) -> dict:
    start      = time.monotonic()
    query_text = state.get("raw_query", "")
    raw        = state.get("retrieved_chunks", [])

    if len(raw) <= 1:
        return {"agent_timings": {"retriever.rerank_ms": (time.monotonic() - start) * 1000}}

    chunks = [RetrievedChunk(**c) for c in raw]

    try:
        reranked = await asyncio.to_thread(_cross_encoder_rerank, query_text, chunks)
    except Exception as exc:
        return {
            "errors":        [f"Re-ranking failed, keeping RRF order: {exc}"],
            "agent_timings": {"retriever.rerank_ms": (time.monotonic() - start) * 1000},
        }

    return {
        "retrieved_chunks": [c.model_dump() for c in reranked],
        "agent_timings":    {"retriever.rerank_ms": (time.monotonic() - start) * 1000},
    }


def _cross_encoder_rerank(
    query_text: str, chunks: list[RetrievedChunk]
) -> list[RetrievedChunk]:
    """
    Score each (query, chunk_content) pair with a cross-encoder.
    Falls back to existing RRF order when sentence-transformers is unavailable.
    Scores are sigmoid-normalised to [0, 1] for consistency with other sources.
    """
    encoder = _get_cross_encoder()
    if encoder is None:
        return chunks   # graceful degradation: keep RRF order

    import numpy as np

    pairs  = [(query_text, c.content[:512]) for c in chunks]  # cap to avoid OOM
    raw_scores  = encoder.predict(pairs)
    norm_scores = (1.0 / (1.0 + np.exp(-raw_scores))).tolist()

    ranked = sorted(
        zip(chunks, norm_scores),
        key=lambda x: x[1],
        reverse=True,
    )
    return [
        chunk.model_copy(update={"rank": i, "score": float(score)})
        for i, (chunk, score) in enumerate(ranked)
    ]


# ── Node 4: Populate cache with final retrieved result ────────────────────────

async def populate_cache_node(state: RAGState) -> dict:
    start      = time.monotonic()
    query_dict = state.get("retrieval_query")
    raw_chunks = state.get("retrieved_chunks", [])

    if not query_dict or not raw_chunks:
        return {"agent_timings": {"retriever.cache_populate_ms": (time.monotonic() - start) * 1000}}

    try:
        query  = RetrievalQuery(**query_dict)
        chunks = [RetrievedChunk(**c) for c in raw_chunks]

        # Build a FusedResult from the (possibly re-ranked) chunks
        fused_dict = state.get("fused_result") or {}
        fused = FusedResult(
            query_text       = query.query_text,
            chunks           = chunks,
            source_results   = fused_dict.get("source_results", {}),
            total_latency_ms = fused_dict.get("total_latency_ms", 0.0),
            sources_used     = fused_dict.get("sources_used", []),
        )

        cache = _get_cache()
        await cache.set(query, fused)

        # Also persist the embedding if we have it and it wasn't cached before
        if query.query_embedding:
            await cache.set_embedding(query.query_text, query.query_embedding)

    except Exception as exc:
        return {
            "errors":        [f"Cache population failed (non-fatal): {exc}"],
            "agent_timings": {"retriever.cache_populate_ms": (time.monotonic() - start) * 1000},
        }

    return {
        "agent_timings": {"retriever.cache_populate_ms": (time.monotonic() - start) * 1000}
    }
