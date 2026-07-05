"""
Planner Agent — LangGraph compiled subgraph.

Graph topology:
    START
      │
      ▼
  classify_query ─── LLM (or rule-based fallback) intent + specialty + risk signals
      │
      ▼
  embed_query ─────── BGE-M3 via cache (L4) or fresh inference
      │
      ▼
  check_cache ─────── L1 exact → L2 semantic → L3 retrieval
      │
      ├─ cache hit ──────────────────────────────────────────────────► END
      │                          (fused_result already in state)
      │ cache miss
      ▼
  plan_retrieval ──── rule-based source + strategy selection
      │
      ▼
  build_query ─────── assembles final RetrievalQuery in state
      │
      ▼
     END

Usage:
    from query.agents.planner import planner_graph

    result = await planner_graph.ainvoke({
        "raw_query":         "What is the first-line treatment for type 2 diabetes?",
        "organization_id":   "org-123",
        "knowledge_base_id": "kb-clinical",
        "role":              "physician",
        "trace_id":          "trace-abc",
        "start_time":        time.monotonic(),
        "errors":            [],
        "agent_timings":     {},
    })
    # result["retrieval_query"] → RetrievalQuery dict ready for RetrieverAgent
    # result["cache_hit"] → True if answered from cache
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from query.agents.state import RAGState

from .nodes import (
    build_query_node,
    check_cache_node,
    classify_query_node,
    embed_query_node,
    plan_retrieval_node,
    route_after_cache,
)


def build_planner_graph():
    """Build and compile the Planner Agent subgraph."""
    builder = StateGraph(RAGState)

    builder.add_node("classify_query",  classify_query_node)
    builder.add_node("embed_query",     embed_query_node)
    builder.add_node("check_cache",     check_cache_node)
    builder.add_node("plan_retrieval",  plan_retrieval_node)
    builder.add_node("build_query",     build_query_node)

    builder.set_entry_point("classify_query")
    builder.add_edge("classify_query", "embed_query")
    builder.add_edge("embed_query",    "check_cache")

    builder.add_conditional_edges(
        "check_cache",
        route_after_cache,
        {END: END, "plan_retrieval": "plan_retrieval"},
    )

    builder.add_edge("plan_retrieval", "build_query")
    builder.add_edge("build_query",    END)

    return builder.compile()


# Module-level compiled graph — import and call .ainvoke()
planner_graph = build_planner_graph()
