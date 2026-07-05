"""
Verifier Agent — LangGraph compiled subgraph.

Takes the re-ranked retrieved_chunks from the Retriever Agent and produces
verified_chunks: a filtered, scored, contradiction-tagged list ready for
the Safety Agent and Response Agent.

Graph topology:
    START
      │
      ▼
  score_citations ─── heuristic score (source credibility × doc type × specialty match)
      │               + optional LLM batch verification for top-8 chunks
      │               → citation_scores dict  +  verifier_flags on chunk metadata
      ▼
  detect_contradictions ── entity-overlap grouping → dose discrepancy check
      │                    → negation conflict check (recommended vs contraindicated)
      │                    → contradictions list
      ▼
  filter_chunks ─── keep chunks ≥ 0.50 citation score
      │             always surface at least 3 chunks even if all are below threshold
      │             tag contradicted chunks with has_contradiction=True in metadata
      │             → verified_chunks (sorted by citation_score desc)
      ▼
     END

Usage (standalone):
    from query.agents.verifier import verifier_graph

    result = await verifier_graph.ainvoke(state)
    # result["verified_chunks"]  → citation-scored, contradiction-tagged chunks
    # result["contradictions"]   → list of conflict pairs with entity + detail
    # result["citation_scores"]  → {chunk_id: float} for all retrieved chunks
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from query.agents.state import RAGState

from .nodes import (
    detect_contradictions_node,
    filter_chunks_node,
    score_citations_node,
)


def build_verifier_graph():
    """Build and compile the Verifier Agent subgraph."""
    builder = StateGraph(RAGState)

    builder.add_node("score_citations",       score_citations_node)
    builder.add_node("detect_contradictions", detect_contradictions_node)
    builder.add_node("filter_chunks",         filter_chunks_node)

    builder.set_entry_point("score_citations")
    builder.add_edge("score_citations",       "detect_contradictions")
    builder.add_edge("detect_contradictions", "filter_chunks")
    builder.add_edge("filter_chunks",         END)

    return builder.compile()


# Module-level compiled graph
verifier_graph = build_verifier_graph()
