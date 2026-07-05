"""
Response Agent — LangGraph compiled subgraph.

Final agent in the HCIP RAG pipeline. Synthesizes a clinically precise,
citation-backed answer from the verified, safety-reviewed chunks.

Graph topology:
    START
      │
      ▼
  synthesize_response ── builds numbered context from verified_chunks (top 10)
      │                  GPT-4o-mini structured output:
      │                    answer (with inline [N] citations)
      │                    used_chunk_indices
      │                    uncertainty_note
      │                  Escalated path: opens with mandatory safety disclaimer
      │                  No-LLM fallback: formatted chunk list + notice
      ▼
  format_citations ────── parses [N] references from the answer text
      │                   maps each N → chunk metadata
      │                   PubMed → title, authors, journal, year, doi, URL
      │                   Internal → document_type, specialty, section, approval_status
      │                   → citations list
      ▼
  compute_confidence ──── confidence_score ∈ [0, 1]
      │                   base  = mean citation_score of cited chunks
      │                   +0.05 per additional independent source (max +0.15)
      │                   −0.15 if contradictions detected
      │                   −0.10 if escalated
      │                   −0.10 if LLM flagged insufficient evidence
      ▼
     END

Output state fields:
    final_response   — complete answer text (with inline [N] citations and disclaimer)
    citations        — list of structured citation objects
    confidence_score — float 0–1 representing answer reliability

Usage (standalone):
    from query.agents.response import response_graph

    result = await response_graph.ainvoke(state)
    # result["final_response"]   → answer ready to deliver
    # result["citations"]        → structured citation list
    # result["confidence_score"] → 0.0–1.0
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from query.agents.state import RAGState

from .nodes import (
    compute_confidence_node,
    format_citations_node,
    synthesize_response_node,
)


def build_response_graph():
    """Build and compile the Response Agent subgraph."""
    builder = StateGraph(RAGState)

    builder.add_node("synthesize_response", synthesize_response_node)
    builder.add_node("format_citations",    format_citations_node)
    builder.add_node("compute_confidence",  compute_confidence_node)

    builder.set_entry_point("synthesize_response")
    builder.add_edge("synthesize_response", "format_citations")
    builder.add_edge("format_citations",    "compute_confidence")
    builder.add_edge("compute_confidence",  END)

    return builder.compile()


# Module-level compiled graph
response_graph = build_response_graph()
