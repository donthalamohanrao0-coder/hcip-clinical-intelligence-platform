"""
Retriever Agent — LangGraph compiled subgraph.

Picks up the RetrievalQuery built by the Planner Agent and returns
a de-duplicated, re-ranked list of chunks ready for the Verifier Agent.

Graph topology:
    START
      │
      ▼
  execute_retrieval ── HybridRetriever: Qdrant + ES + Neo4j + PubMed (parallel)
      │                → fused_result, retrieved_chunks (RRF-ranked)
      ▼
  enrich_content ───── fetch real text for Neo4j "[Graph match]" placeholders
      │                via Qdrant .retrieve() by chunk ID
      ▼
  rerank ───────────── cross-encoder/ms-marco-MiniLM-L-6-v2 re-scores pairs
      │                falls back to RRF order if sentence-transformers absent
      ▼
  populate_cache ───── writes re-ranked FusedResult to L1 + L2 + L3 cache
      │                (non-fatal: cache errors are logged, not raised)
      ▼
     END

Usage (standalone):
    from query.agents.retriever import retriever_graph

    # state must already contain retrieval_query (set by planner_graph)
    result = await retriever_graph.ainvoke(state)
    # result["retrieved_chunks"] → list of re-ranked, enriched chunk dicts
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from query.agents.state import RAGState

from .nodes import (
    enrich_content_node,
    execute_retrieval_node,
    populate_cache_node,
    rerank_node,
)


def build_retriever_graph():
    """Build and compile the Retriever Agent subgraph."""
    builder = StateGraph(RAGState)

    builder.add_node("execute_retrieval", execute_retrieval_node)
    builder.add_node("enrich_content",    enrich_content_node)
    builder.add_node("rerank",            rerank_node)
    builder.add_node("populate_cache",    populate_cache_node)

    builder.set_entry_point("execute_retrieval")
    builder.add_edge("execute_retrieval", "enrich_content")
    builder.add_edge("enrich_content",    "rerank")
    builder.add_edge("rerank",            "populate_cache")
    builder.add_edge("populate_cache",    END)

    return builder.compile()


# Module-level compiled graph
retriever_graph = build_retriever_graph()
