"""
Shared LangGraph state for the five-agent HCIP RAG pipeline.

All nodes read from and write to this TypedDict.
Fields annotated with a reducer are accumulated across nodes;
all other fields use last-write-wins semantics.
"""

from __future__ import annotations

import operator
from typing import Annotated, Optional

from typing_extensions import TypedDict


class RAGState(TypedDict, total=False):
    """
    Pipeline-wide state.  total=False means every key is optional so nodes
    can return partial dicts with only the fields they compute.

    Reducers:
        errors        — appended by every node that encounters an error
        agent_timings — merged dict; each node adds its own key(s)
    """

    # ── Input (set by the caller before graph.ainvoke) ────────────────────────
    raw_query:         str
    organization_id:   str
    knowledge_base_id: str
    role:              Optional[str]
    user_id:           Optional[str]

    # ── Planner Agent outputs (Phase 16) ──────────────────────────────────────
    query_intent:       str              # QueryIntent value
    medical_specialty:  str              # MedicalSpecialty value
    query_risk_signals: list[str]        # detected high-risk terms in the query
    risk_levels:        Optional[list[str]]  # chunk risk-level filter (None = no filter)
    query_embedding:    Optional[list[float]]
    retrieval_strategy: str              # RetrievalStrategy value
    selected_sources:   list[str]        # RetrievalSource values
    include_pubmed:     bool
    retrieval_query:    Optional[dict]   # serialized RetrievalQuery

    # ── Cache state ───────────────────────────────────────────────────────────
    cache_hit:   bool
    cache_layer: Optional[str]           # "exact" | "semantic" | "retrieval" | None

    # ── Retriever Agent outputs (Phase 17) ────────────────────────────────────
    fused_result:     Optional[dict]     # serialized FusedResult
    retrieved_chunks: list[dict]         # serialized RetrievedChunk list

    # ── Verifier Agent outputs (Phase 18) ─────────────────────────────────────
    verified_chunks:  list[dict]
    contradictions:   list[dict]
    citation_scores:  dict[str, float]   # chunk_id → citation confidence

    # ── Safety Agent outputs (Phase 19) ───────────────────────────────────────
    safety_flags:        list[dict]
    requires_escalation: bool
    escalation_reason:   Optional[str]

    # ── Response Agent outputs (Phase 20) ─────────────────────────────────────
    final_response:   Optional[str]
    citations:        list[dict]
    confidence_score: float

    # ── Pipeline metadata ─────────────────────────────────────────────────────
    trace_id:    str
    start_time:  float
    errors:      Annotated[list[str], operator.add]
    agent_timings: Annotated[dict[str, float], lambda a, b: {**a, **b}]

    # ── Response Agent internal scratch fields (not part of the public API) ───
    _ref_map:          Optional[dict]   # chunk ref-number → serialised RetrievedChunk
    _used_indices:     Optional[list]   # 1-based chunk indices cited by the LLM
    _uncertainty_note: Optional[str]    # LLM's own assessment of evidence gaps
