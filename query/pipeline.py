"""
HCIP RAG Pipeline — Phase 21: Full LangGraph workflow.

Wires the five agents into a single compiled StateGraph with conditional routing.

Graph topology:
    START
      │
      ▼
    planner ──────────────────────────────────────────────────────────
      │  classify_query → embed_query → check_cache →                │
      │  plan_retrieval → build_query                                 │
      │                                                               │
      ├─ cache_hit = True ────────────────────► prepare_cache ─────► │
      │                                              (copies cached   │
      │                                               chunks into     │
      │                                               retrieved_chunks)│
      │                                                               ▼
      └─ cache_hit = False ────────────────────► retriever ──────────►
                                                     │                │
                                         execute_retrieval             │
                                         enrich_content               │
                                         rerank                       │
                                         populate_cache               │
                                                     │                │
                                                     └────────────────►
                                                                      │
                                                                      ▼
                                                                  verifier
                                                             score_citations
                                                           detect_contradictions
                                                             filter_chunks
                                                                      │
                                                                      ▼
                                                                    safety
                                                               detect_risks
                                                            evaluate_escalation
                                                                      │
                                                                      ▼
                                                                   response
                                                            synthesize_response
                                                             format_citations
                                                            compute_confidence
                                                                      │
                                                                      ▼
                                                                     END

Cache hit path (fast):  Planner → prepare_cache → Verifier → Safety → Response
  Skips the expensive multi-source retrieval; Verifier + Safety always run for safety.

Full path (first query): Planner → Retriever → Verifier → Safety → Response

Typical latencies (with warm embedding cache, no cold LLM):
  Cache hit  : ~300 ms  (no vector DB round-trips)
  Cache miss : ~1–3 s   (4 parallel retrieval sources + re-ranking + LLM synthesis)
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from langgraph.graph import END, StateGraph
from pydantic import BaseModel

from query.agents.planner import planner_graph
from query.agents.response import response_graph
from query.agents.response.nodes import (
    compute_confidence_node,
    format_citations_node,
    stream_synthesize_response,
)
from query.agents.retriever import retriever_graph
from query.agents.safety import safety_graph
from query.agents.state import RAGState
from query.agents.verifier import verifier_graph
from observability import get_tracer, record_query_metrics
from observability.langfuse_handler import pipeline_trace


# ── QueryResult — clean output model returned to callers ─────────────────────

class QueryResult(BaseModel):
    """Structured output of the full RAG pipeline."""

    query_text:          str
    final_response:      str
    citations:           list[dict[str, Any]] = []
    confidence_score:    float                = 0.0
    safety_flags:        list[dict[str, Any]] = []
    requires_escalation: bool                 = False
    escalation_reason:   Optional[str]        = None
    cache_hit:           bool                 = False
    cache_layer:         Optional[str]        = None
    total_latency_ms:    float                = 0.0
    errors:              list[str]            = []
    trace_id:            str                  = ""
    agent_timings:       dict[str, float]     = {}


# ── Bridge node: cache hit → hand cached chunks to Verifier ──────────────────

async def _prepare_cache_node(state: RAGState) -> dict:
    """
    On cache hit the fused_result is already in state.
    Copy its chunks into retrieved_chunks with pre-filled citation scores
    so the Verifier Agent can run its citation scoring and contradiction checks.
    """
    fused_dict = state.get("fused_result") or {}
    chunks     = fused_dict.get("chunks", [])

    citation_scores = {
        c["chunk_id"]: c.get("score", 0.75)
        for c in chunks
        if c.get("chunk_id")
    }

    return {
        "retrieved_chunks": chunks,
        "citation_scores":  citation_scores,
    }


# ── Conditional router after Planner ─────────────────────────────────────────

def _route_after_planner(state: RAGState) -> str:
    return "prepare_cache" if state.get("cache_hit") else "retriever"


# ── Graph assembly ────────────────────────────────────────────────────────────

def _add_core_nodes(builder: StateGraph) -> None:
    """
    Shared by both compiled graphs: Planner → [prepare_cache | Retriever] → Verifier → Safety.
    The full pipeline appends Response after this; the streaming pipeline stops
    here and hands off to `stream_synthesize_response()` outside the graph so the
    LLM call can be streamed token-by-token instead of awaited as one blocking call.
    """
    builder.add_node("planner",       planner_graph)
    builder.add_node("prepare_cache", _prepare_cache_node)
    builder.add_node("retriever",     retriever_graph)
    builder.add_node("verifier",      verifier_graph)
    builder.add_node("safety",        safety_graph)

    builder.set_entry_point("planner")

    builder.add_conditional_edges(
        "planner",
        _route_after_planner,
        {
            "prepare_cache": "prepare_cache",
            "retriever":     "retriever",
        },
    )

    builder.add_edge("prepare_cache", "verifier")
    builder.add_edge("retriever",     "verifier")
    builder.add_edge("verifier",      "safety")


def build_rag_pipeline():
    """Compile the full 5-agent RAG pipeline graph (blocking response synthesis)."""
    builder = StateGraph(RAGState)
    _add_core_nodes(builder)

    builder.add_node("response", response_graph)
    builder.add_edge("safety",   "response")
    builder.add_edge("response", END)

    return builder.compile()


def build_pre_response_pipeline():
    """
    Compile Planner → Retriever → Verifier → Safety only.
    Used by run_query_stream(), which takes over after Safety to stream the
    Response agent's LLM call token-by-token instead of running it as a graph node.
    """
    builder = StateGraph(RAGState)
    _add_core_nodes(builder)
    builder.add_edge("safety", END)

    return builder.compile()


# Module-level compiled pipelines
rag_pipeline          = build_rag_pipeline()
pre_response_pipeline = build_pre_response_pipeline()


# ── Public API ────────────────────────────────────────────────────────────────

async def run_query(
    query_text:        str,
    organization_id:   str,
    knowledge_base_id: str,
    role:              Optional[str] = None,
    user_id:           Optional[str] = None,
) -> QueryResult:
    """
    Execute the full HCIP RAG pipeline for a clinical query.

    Parameters
    ----------
    query_text        : The clinical question (free text).
    organization_id   : Tenant identifier — scopes retrieval to this org's knowledge.
    knowledge_base_id : Which knowledge base to query within the org.
    role              : Optional RBAC role for access-controlled chunk filtering.
    user_id           : Optional user identifier for audit logging.

    Returns
    -------
    QueryResult with final_response, citations, confidence_score,
    safety_flags, requires_escalation, and pipeline timing breakdown.

    Example
    -------
    result = await run_query(
        query_text        = "First-line treatment for type 2 diabetes in CKD stage 3?",
        organization_id   = "org-abc",
        knowledge_base_id = "kb-clinical-2024",
        role              = "physician",
    )
    print(result.final_response)
    """
    trace_id   = str(uuid.uuid4())
    start_time = time.monotonic()

    initial_state: dict = {
        "raw_query":         query_text,
        "organization_id":   organization_id,
        "knowledge_base_id": knowledge_base_id,
        "role":              role,
        "user_id":           user_id,
        "trace_id":          trace_id,
        "start_time":        start_time,
        "errors":            [],
        "agent_timings":     {},
    }

    tracer = get_tracer()

    # pipeline_trace() opens a Langfuse root span for this request and propagates
    # OTEL context so response/nodes.py can attach nested observations automatically.
    # Uses sync 'with' (Langfuse v4 _AgnosticContextManager is sync-only).
    with pipeline_trace(
        query_text = query_text,
        user_id    = user_id or "anonymous",
        org_id     = organization_id,
        kb_id      = knowledge_base_id,
        role       = role,
        trace_id   = trace_id,
    ) as lf_root:

        with tracer.start_as_current_span("hcip.run_query") as span:
            span.set_attribute("hcip.org_id",   organization_id)
            span.set_attribute("hcip.kb_id",    knowledge_base_id)
            span.set_attribute("hcip.trace_id", trace_id)
            if role:
                span.set_attribute("hcip.role", role)

            try:
                final_state = await rag_pipeline.ainvoke(initial_state)

            except Exception as exc:
                span.record_exception(exc)
                result = QueryResult(
                    query_text        = query_text,
                    final_response    = (
                        "A critical error occurred while processing your query. "
                        "Please contact support or try again."
                    ),
                    errors            = [f"Pipeline error: {exc}"],
                    trace_id          = trace_id,
                    total_latency_ms  = (time.monotonic() - start_time) * 1000,
                )
                record_query_metrics(result)
                return result

            timings  = final_state.get("agent_timings", {})
            total_ms = (time.monotonic() - start_time) * 1000

            result = QueryResult(
                query_text          = query_text,
                final_response      = final_state.get("final_response") or _no_answer_fallback(query_text),
                citations           = final_state.get("citations", []),
                confidence_score    = final_state.get("confidence_score", 0.0),
                safety_flags        = [
                    f for f in final_state.get("safety_flags", [])
                    if f.get("flag_type") != "clinical_disclaimer"
                ],
                requires_escalation = final_state.get("requires_escalation", False),
                escalation_reason   = final_state.get("escalation_reason"),
                cache_hit           = final_state.get("cache_hit", False),
                cache_layer         = final_state.get("cache_layer"),
                total_latency_ms    = total_ms,
                errors              = final_state.get("errors", []),
                trace_id            = trace_id,
                agent_timings       = timings,
            )

            span.set_attribute("hcip.cache_hit",   result.cache_hit)
            span.set_attribute("hcip.confidence",  result.confidence_score)
            span.set_attribute("hcip.escalated",   result.requires_escalation)
            span.set_attribute("hcip.latency_ms",  result.total_latency_ms)

            # Update Langfuse root span with final outcome
            if lf_root is not None:
                err_count = len(result.errors)
                lf_root.update(
                    output   = result.final_response[:500],
                    metadata = {
                        "confidence_score": str(round(result.confidence_score, 3)),
                        "total_latency_ms": str(round(total_ms, 1)),
                        "error_count":      str(err_count),
                        "cache_hit":        str(result.cache_hit),
                        "citations":        str(len(result.citations)),
                    },
                    level = "WARNING" if result.errors else "DEFAULT",
                )

            record_query_metrics(result)
            return result


# ── Streaming variant — Server-Sent-Events-friendly generator ────────────────
#
# Event shapes yielded (each is a plain dict the HTTP layer JSON-encodes):
#   {"type": "stage", "stage": "planner"|"retriever"|"verifier"|"safety"|"response", "label": str}
#   {"type": "token", "text": str}                     — one chunk of the answer, in order
#   {"type": "meta", ...QueryResult fields except final_response/query_text...}
#   {"type": "error", "message": str}
#   {"type": "done"}
#
# The Planner/Retriever/Verifier/Safety agents still run as one compiled graph
# (pre_response_pipeline); only the Response agent's LLM call is streamed,
# since that's the only part with meaningful token-level output.

_STAGE_LABELS: dict[str, str] = {
    "planner":   "Understanding your question",
    "retriever": "Searching clinical evidence",
    "verifier":  "Verifying citations",
    "safety":    "Checking safety flags",
    "response":  "Generating response",
}


async def run_query_stream(
    query_text:        str,
    organization_id:   str,
    knowledge_base_id: str,
    role:              Optional[str] = None,
    user_id:           Optional[str] = None,
):
    """
    Streaming counterpart to run_query(). Yields SSE-ready event dicts as the
    pipeline progresses, then a final "meta" event with the full QueryResult
    fields (minus final_response, which the caller reconstructs by
    concatenating the "token" events it already received).
    """
    trace_id   = str(uuid.uuid4())
    start_time = time.monotonic()

    initial_state: dict = {
        "raw_query":         query_text,
        "organization_id":   organization_id,
        "knowledge_base_id": knowledge_base_id,
        "role":              role,
        "user_id":           user_id,
        "trace_id":          trace_id,
        "start_time":        start_time,
        "errors":            [],
        "agent_timings":     {},
    }

    tracer = get_tracer()

    with pipeline_trace(
        query_text = query_text,
        user_id    = user_id or "anonymous",
        org_id     = organization_id,
        kb_id      = knowledge_base_id,
        role       = role,
        trace_id   = trace_id,
    ) as lf_root:

        with tracer.start_as_current_span("hcip.run_query_stream") as span:
            span.set_attribute("hcip.org_id",   organization_id)
            span.set_attribute("hcip.kb_id",    knowledge_base_id)
            span.set_attribute("hcip.trace_id", trace_id)
            if role:
                span.set_attribute("hcip.role", role)

            try:
                state: dict            = dict(initial_state)
                stages_emitted: set[str] = set()

                async for snapshot in pre_response_pipeline.astream(
                    initial_state, stream_mode="values",
                ):
                    state = snapshot

                    if "query_intent" in state and "planner" not in stages_emitted:
                        stages_emitted.add("planner")
                        yield {"type": "stage", "stage": "planner", "label": _STAGE_LABELS["planner"]}

                    if "retrieved_chunks" in state and "retriever" not in stages_emitted:
                        stages_emitted.add("retriever")
                        label = "Instant cache match" if state.get("cache_hit") else _STAGE_LABELS["retriever"]
                        yield {"type": "stage", "stage": "retriever", "label": label}

                    if "verified_chunks" in state and "verifier" not in stages_emitted:
                        stages_emitted.add("verifier")
                        yield {"type": "stage", "stage": "verifier", "label": _STAGE_LABELS["verifier"]}

                    if "safety_flags" in state and "safety" not in stages_emitted:
                        stages_emitted.add("safety")
                        yield {"type": "stage", "stage": "safety", "label": _STAGE_LABELS["safety"]}

                yield {"type": "stage", "stage": "response", "label": _STAGE_LABELS["response"]}

                sink: dict = {}
                full_text  = ""
                async for piece in stream_synthesize_response(state, sink):
                    full_text += piece
                    yield {"type": "token", "text": piece}

                response_state = {
                    **state,
                    "final_response":    full_text,
                    "_ref_map":          sink.get("ref_map", {}),
                    "_used_indices":     sink.get("used_indices", []),
                    "_uncertainty_note": sink.get("uncertainty_note", ""),
                }
                response_state.update(await format_citations_node(response_state))
                response_state.update(await compute_confidence_node(response_state))

                total_ms = (time.monotonic() - start_time) * 1000

                result = QueryResult(
                    query_text          = query_text,
                    final_response      = full_text or _no_answer_fallback(query_text),
                    citations           = response_state.get("citations", []),
                    confidence_score    = response_state.get("confidence_score", 0.0),
                    safety_flags        = [
                        f for f in state.get("safety_flags", [])
                        if f.get("flag_type") != "clinical_disclaimer"
                    ],
                    requires_escalation = state.get("requires_escalation", False),
                    escalation_reason   = state.get("escalation_reason"),
                    cache_hit           = bool(state.get("cache_hit") or sink.get("from_l0_cache")),
                    cache_layer         = state.get("cache_layer") or (
                        "L0-response" if sink.get("from_l0_cache") else None
                    ),
                    total_latency_ms    = total_ms,
                    errors              = state.get("errors", []),
                    trace_id            = trace_id,
                    agent_timings       = state.get("agent_timings", {}),
                )

                span.set_attribute("hcip.cache_hit",  result.cache_hit)
                span.set_attribute("hcip.confidence", result.confidence_score)
                span.set_attribute("hcip.escalated",  result.requires_escalation)
                span.set_attribute("hcip.latency_ms", result.total_latency_ms)

                if lf_root is not None:
                    lf_root.update(
                        output   = result.final_response[:500],
                        metadata = {
                            "confidence_score": str(round(result.confidence_score, 3)),
                            "total_latency_ms": str(round(total_ms, 1)),
                            "error_count":      str(len(result.errors)),
                            "cache_hit":        str(result.cache_hit),
                            "citations":        str(len(result.citations)),
                        },
                        level = "WARNING" if result.errors else "DEFAULT",
                    )

                record_query_metrics(result)

                meta = result.model_dump(exclude={"final_response", "query_text"})
                yield {"type": "meta", **meta}
                yield {"type": "done"}

            except Exception as exc:
                span.record_exception(exc)
                yield {"type": "error", "message": str(exc)}
                yield {"type": "done"}


def _no_answer_fallback(query_text: str) -> str:
    return (
        f"No relevant clinical information was found for: \"{query_text}\". "
        "Please verify the query or consult a clinical specialist."
    )
