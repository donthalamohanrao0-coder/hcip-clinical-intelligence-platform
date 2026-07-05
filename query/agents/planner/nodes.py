"""
Async node functions for the Planner Agent LangGraph graph.

Graph shape:
    classify_query → embed_query → check_cache
                                        ├─ (cache hit)  → END
                                        └─ (cache miss) → plan_retrieval → build_query → END
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from query.agents.state import RAGState
from query.models.query import QueryIntent, RetrievalQuery, RetrievalSource, RetrievalStrategy
from query.services.cache import CachePipeline

from .prompts import QueryClassification, classify_rule_based

# ── Module-level singletons ────────────────────────────────────────────────────

_cache_pipeline: Optional[CachePipeline] = None
_query_embedder = None   # TextEmbedder singleton for query path


def _get_cache() -> CachePipeline:
    global _cache_pipeline
    if _cache_pipeline is None:
        _cache_pipeline = CachePipeline()
    return _cache_pipeline


def _get_embedder():
    """Singleton BGE embedder for query embedding — shared with ingest path via class-level _model."""
    global _query_embedder
    if _query_embedder is not None:
        return _query_embedder
    try:
        from ingestion.services.embedding.text_embedder import TextEmbedder
        _query_embedder = TextEmbedder()
    except Exception:
        _query_embedder = None
    return _query_embedder


# ── Strategy selection rules ──────────────────────────────────────────────────

_STRATEGY_MAP: dict[str, tuple[list[str], bool]] = {
    # intent → (sources, include_pubmed)
    # PubMed disabled across all intents — enable when PUBMED_API_KEY is set
    "diagnosis":  (["qdrant", "elasticsearch", "neo4j"], False),
    "treatment":  (["qdrant", "elasticsearch", "neo4j"], False),
    "drug_info":  (["qdrant", "elasticsearch", "neo4j"], False),
    "protocol":   (["qdrant", "elasticsearch", "neo4j"], False),
    "research":   (["qdrant", "elasticsearch", "neo4j"], False),
    "general":    (["qdrant", "elasticsearch", "neo4j"], False),
}


# ── Node 1: Classify query intent + specialty ─────────────────────────────────

async def classify_query_node(state: RAGState) -> dict:
    """
    Rule-based intent classifier — zero latency, zero cost, no LLM dependency.
    The LLM classifier added 500-800ms per query with no meaningful quality gain
    for the intent classes we use downstream.
    """
    start      = time.monotonic()
    query_text = state["raw_query"]

    classification = classify_rule_based(query_text)

    return {
        **_from_classification(classification),
        "agent_timings": {"planner.classify_ms": (time.monotonic() - start) * 1000},
    }


def _from_classification(c: QueryClassification) -> dict:
    return {
        "query_intent":       c.intent,
        "medical_specialty":  c.specialty,
        "query_risk_signals": c.risk_signals,
        "include_pubmed":     False,   # always off until valid PUBMED_API_KEY is set
    }


# ── Node 2: Embed the query ────────────────────────────────────────────────────

async def embed_query_node(state: RAGState) -> dict:
    start      = time.monotonic()
    query_text = state["raw_query"]
    cache      = _get_cache()

    # L4 cache first — avoids model inference on repeated queries
    embedding = await cache.get_embedding(query_text)

    if embedding is None:
        embedder = _get_embedder()
        if embedder is None:
            return {
                "errors":        ["Query embedding unavailable: TextEmbedder failed to load"],
                "agent_timings": {"planner.embed_ms": (time.monotonic() - start) * 1000},
            }
        try:
            embedding = await asyncio.to_thread(embedder.embed, query_text)
            await cache.set_embedding(query_text, embedding)
        except Exception as exc:
            return {
                "errors":        [f"Query embedding failed: {exc}"],
                "agent_timings": {"planner.embed_ms": (time.monotonic() - start) * 1000},
            }

    return {
        "query_embedding": embedding,
        "agent_timings":   {"planner.embed_ms": (time.monotonic() - start) * 1000},
    }


# ── Node 3: Check 4-layer cache ────────────────────────────────────────────────

async def check_cache_node(state: RAGState) -> dict:
    start = time.monotonic()

    query = RetrievalQuery(
        query_text        = state["raw_query"],
        query_embedding   = state.get("query_embedding"),
        organization_id   = state["organization_id"],
        knowledge_base_id = state["knowledge_base_id"],
        role              = state.get("role"),
    )
    cache = _get_cache()

    # L1: exact match (no embedding required)
    hit = await cache.get(query)

    # L2 + L3: semantic / retrieval (require embedding)
    if hit is None and query.query_embedding is not None:
        hit = await cache.get_with_embedding(query)

    timing = {"planner.cache_check_ms": (time.monotonic() - start) * 1000}

    if hit:
        return {
            "cache_hit":     True,
            "cache_layer":   hit.layer,
            "fused_result":  hit.fused_result.model_dump(),
            "agent_timings": timing,
        }

    return {
        "cache_hit":     False,
        "cache_layer":   None,
        "agent_timings": timing,
    }


# ── Conditional router after cache check ──────────────────────────────────────

def route_after_cache(state: RAGState) -> str:
    from langgraph.graph import END
    return END if state.get("cache_hit") else "plan_retrieval"


# ── Node 4: Select retrieval strategy + sources ────────────────────────────────

async def plan_retrieval_node(state: RAGState) -> dict:
    start  = time.monotonic()
    intent = state.get("query_intent", "general")

    sources, include_pubmed = _STRATEGY_MAP.get(
        intent, (["qdrant", "elasticsearch", "neo4j"], False)
    )

    return {
        "retrieval_strategy": "hybrid",
        "selected_sources":   sources,
        "include_pubmed":     include_pubmed,
        "agent_timings":      {"planner.plan_ms": (time.monotonic() - start) * 1000},
    }


# ── Node 5: Assemble final RetrievalQuery ─────────────────────────────────────

async def build_query_node(state: RAGState) -> dict:
    start = time.monotonic()

    raw_sources = state.get("selected_sources") or [s.value for s in RetrievalSource]
    sources     = [RetrievalSource(s) for s in raw_sources]

    strategy_val = state.get("retrieval_strategy", "hybrid")
    intent_val   = state.get("query_intent", "general")

    query = RetrievalQuery(
        query_text        = state["raw_query"],
        query_embedding   = state.get("query_embedding"),
        organization_id   = state["organization_id"],
        knowledge_base_id = state["knowledge_base_id"],
        role              = state.get("role"),
        risk_levels       = None,          # not stored in ingest payload
        top_k             = 6,             # 6 is plenty for RRF + LLM synthesis
        sources           = sources,
        strategy          = RetrievalStrategy(strategy_val),
        intent            = QueryIntent(intent_val),
        include_pubmed    = False,
    )

    return {
        "retrieval_query": query.model_dump(),
        "agent_timings":   {"planner.build_query_ms": (time.monotonic() - start) * 1000},
    }
