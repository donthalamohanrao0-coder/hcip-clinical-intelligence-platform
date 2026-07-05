"""
Async node functions for the Response Agent.

Graph:
    START → synthesize_response → format_citations → compute_confidence → END
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from query.agents.state import RAGState
from query.models.result import RetrievedChunk

# ── Inline citation parser  [N] ───────────────────────────────────────────────
_CITE_RE = re.compile(r'\[(\d+)\]')

# ── Response-level Redis cache (L0) ──────────────────────────────────────────
_RESPONSE_CACHE_TTL = 3600   # 1 hour

def _response_cache_key(query_text: str, org_id: str, kb_id: str) -> str:
    h = hashlib.sha256(f"{org_id}:{kb_id}:{query_text.strip().lower()}".encode()).hexdigest()
    return f"resp:{h}"

async def _get_cached_response(key: str):
    try:
        from query.services.cache.cache_config import get_async_redis
        r = await get_async_redis()
        data = await r.get(key)
        return json.loads(data.decode()) if data else None
    except Exception:
        return None

async def _set_cached_response(key: str, payload: dict) -> None:
    try:
        from query.services.cache.cache_config import get_async_redis
        r = await get_async_redis()
        await r.setex(key, _RESPONSE_CACHE_TTL, json.dumps(payload).encode())
    except Exception:
        pass

# ── LLM response synthesizer (lazy) ──────────────────────────────────────────
_llm_synth = None


def _get_llm():
    global _llm_synth
    if _llm_synth is not None:
        return None if _llm_synth == "unavailable" else _llm_synth

    from ingestion.config import get_settings
    cfg = get_settings()
    if not cfg.openai_api_key or cfg.openai_api_key.startswith("REPLACE"):
        _llm_synth = "unavailable"
        return None

    try:
        from langchain_openai import ChatOpenAI
        from pydantic import BaseModel, Field

        class _ClinicalResponse(BaseModel):
            answer:             str
            used_chunk_indices: list[int] = Field(
                description="1-based indices of context chunks actually cited in the answer"
            )
            uncertainty_note:   str = Field(
                default="",
                description="Leave empty if context is sufficient; otherwise state what evidence is missing",
            )

        llm        = ChatOpenAI(model=cfg.llm_model, temperature=0, api_key=cfg.openai_api_key)
        _llm_synth = llm.with_structured_output(_ClinicalResponse)
    except Exception:
        _llm_synth = "unavailable"
        return None

    return _llm_synth


# ── Plain streaming LLM (no structured output — needed for token-by-token SSE) ─
_llm_stream = None


def _get_llm_stream():
    global _llm_stream
    if _llm_stream is not None:
        return None if _llm_stream == "unavailable" else _llm_stream

    from ingestion.config import get_settings
    cfg = get_settings()
    if not cfg.openai_api_key or cfg.openai_api_key.startswith("REPLACE"):
        _llm_stream = "unavailable"
        return None

    try:
        from langchain_openai import ChatOpenAI

        _llm_stream = ChatOpenAI(
            model=cfg.llm_model, temperature=0, api_key=cfg.openai_api_key, streaming=True,
        )
    except Exception:
        _llm_stream = "unavailable"
        return None

    return _llm_stream


# ── Uncertainty heuristic (replaces the structured-output uncertainty_note
#    field, which isn't available once we stream plain text instead of JSON) ──
_UNCERTAINTY_MARKERS = (
    "does not provide", "does not contain", "does not address", "insufficient",
    "not enough information", "no relevant", "cannot determine", "unable to determine",
    "not addressed in the", "context does not", "no information", "not available in the provided",
)


def _heuristic_uncertainty(answer: str) -> str:
    low = answer.lower()
    if any(marker in low for marker in _UNCERTAINTY_MARKERS):
        return "Model flagged potential evidence gaps in its answer text."
    return ""


# ── Prompt templates ──────────────────────────────────────────────────────────

_SYSTEM_STANDARD = """\
You are a clinical knowledge assistant for an enterprise healthcare platform.
Your audience is licensed healthcare professionals (physicians, nurses, pharmacists).

Synthesize a precise, evidence-based answer from the numbered context chunks below.

Rules:
1. Use ONLY information present in the provided context — never add outside knowledge.
2. Cite every factual claim inline with [N] referencing the chunk number.
3. If the context is insufficient to answer fully, state this explicitly rather than speculating.
4. Use standard clinical terminology; be concise and actionable.
5. This is a decision-support tool — present evidence, not directives.
"""

_SYSTEM_ESCALATED = """\
You are a clinical knowledge assistant for an enterprise healthcare platform.
⚠️  This query has been flagged as HIGH-RISK (escalated for human clinical review).

Synthesize a precise answer from the numbered context chunks below.
Begin your answer with the safety disclaimer on its own line.
After the disclaimer, provide the evidence-based answer with inline [N] citations.
Explicitly flag any steps that require clinical validation before application.

Rules:
1. Use ONLY information present in the context — never add outside knowledge.
2. Cite every factual claim inline with [N].
3. State uncertainty explicitly rather than speculating.
"""

_HUMAN_TMPL = """\
Clinical query: {query}

Context chunks:
{context}

{uncertainty_prompt}
"""

_UNCERTAINTY_HINT = (
    "If the provided context does not fully address the query, acknowledge the gap "
    "in your uncertainty_note field."
)

# Streaming has no structured-output field to carry the uncertainty note in, so the
# hint must tell the model to fold it into the prose instead of naming a fake field
# (otherwise it literally writes "Uncertainty note: ..." into the visible answer).
_UNCERTAINTY_HINT_STREAM = (
    "If the provided context does not fully address the query, say so naturally as "
    "part of your answer — do not label it as a separate field or write \"Uncertainty note\"."
)


def _build_context(chunks: list[RetrievedChunk]) -> tuple[str, dict[int, RetrievedChunk]]:
    """Format chunks as numbered context; return the text and a ref-number→chunk map."""
    parts: list[str]                = []
    ref_map: dict[int, RetrievedChunk] = {}

    for i, chunk in enumerate(chunks, 1):
        label   = _source_label(chunk)
        content = chunk.content[:350].strip()
        parts.append(f"[{i}] {label}\n{content}")
        ref_map[i] = chunk

    return "\n\n".join(parts), ref_map


def _source_label(chunk: RetrievedChunk) -> str:
    if chunk.source.value == "pubmed":
        title   = chunk.metadata.get("title",   "Unknown Article")[:80]
        journal = chunk.metadata.get("journal", "")
        year    = chunk.metadata.get("year",    "")
        pmid    = chunk.metadata.get("pmid",    "")
        return f"SOURCE: PubMed — \"{title}\" ({journal}, {year}) PMID:{pmid}"

    doc_type  = chunk.metadata.get("document_type", "document").replace("_", " ").title()
    specialty = chunk.metadata.get("specialty", "")
    section   = chunk.metadata.get("section",   "")
    parts     = [f"SOURCE: {doc_type}"]
    if specialty and specialty != "general":
        parts.append(f"({specialty})")
    if section:
        parts.append(f"— \"{section[:60]}\"")
    return " ".join(parts)


def _fallback_response(
    query_text: str,
    chunks: list[RetrievedChunk],
    disclaimer: str,
) -> tuple[str, list[int]]:
    """No-LLM fallback: format top chunks as a structured list."""
    lines = [
        disclaimer,
        "",
        f"Retrieved clinical knowledge for: {query_text}",
        "",
    ]
    for i, chunk in enumerate(chunks, 1):
        lines.append(f"[{i}] {_source_label(chunk)}")
        lines.append(chunk.content[:400].strip())
        lines.append("")

    lines.append(
        "Note: Full answer synthesis requires LLM configuration (OPENAI_API_KEY)."
    )
    return "\n".join(lines), list(range(1, len(chunks) + 1))


# ── Node 1: Synthesize the response ──────────────────────────────────────────

async def synthesize_response_node(state: RAGState) -> dict:
    start      = time.monotonic()
    query_text = state.get("raw_query", "")
    org_id     = state.get("organization_id", "")
    kb_id      = state.get("knowledge_base_id", "")
    raw        = state.get("verified_chunks", []) or state.get("retrieved_chunks", [])
    escalated  = state.get("requires_escalation", False)

    # ── L0: response cache — skip LLM entirely on repeated queries ────────────
    resp_key = _response_cache_key(query_text, org_id, kb_id)
    cached   = await _get_cached_response(resp_key)
    if cached:
        return {
            "final_response":    cached["answer"],
            "_ref_map":          cached.get("ref_map", {}),
            "_used_indices":     cached.get("used_indices", []),
            "_uncertainty_note": cached.get("uncertainty_note", ""),
            "agent_timings":     {"response.synthesize_ms": (time.monotonic() - start) * 1000},
        }

    chunks = [RetrievedChunk(**c) for c in raw[:5]]

    # Grab disclaimer from safety flags
    safety_flags = state.get("safety_flags", [])
    disclaimer   = next(
        (f["description"] for f in safety_flags if f.get("flag_type") == "clinical_disclaimer"),
        "This information is for educational purposes only. Consult a licensed clinician.",
    )

    context_text, ref_map = _build_context(chunks)

    # ── LLM synthesis ─────────────────────────────────────────────────────────
    llm = _get_llm()
    used_indices: list[int] = []
    uncertainty_note        = ""

    if llm is not None:
        from langchain_core.messages import HumanMessage, SystemMessage

        system_prompt = _SYSTEM_ESCALATED if escalated else _SYSTEM_STANDARD
        if escalated:
            system_prompt = system_prompt.replace(
                "Begin your answer with the safety disclaimer on its own line.",
                f"Begin your answer with this exact disclaimer on its own line:\n\"{disclaimer}\"",
            )

        effective_context = context_text if chunks else (
            "[No documents have been ingested into this knowledge base yet. "
            "Answer from general clinical knowledge and clearly state that no "
            "platform-specific guidelines were found.]"
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=_HUMAN_TMPL.format(
                query              = query_text,
                context            = effective_context,
                uncertainty_prompt = _UNCERTAINTY_HINT,
            )),
        ]

        try:
            # Wrap the LLM call with a Langfuse generation observation.
            # start_as_current_observation() is sync (Langfuse v4 _AgnosticContextManager)
            # and nests automatically under the root span opened in pipeline.py via OTEL context.
            from observability.langfuse_handler import log_llm_generation_ctx
            from ingestion.config import get_settings as _gs
            _lf_client, _lf_tid = log_llm_generation_ctx()

            if _lf_client is not None:
                _prompt_text = messages[0].content[:2000] + "\n---\n" + messages[1].content[:2000]
                with _lf_client.start_as_current_observation(
                    name    = "response-synthesis",
                    as_type = "generation",
                    model   = _gs().llm_model,
                    input   = _prompt_text,
                ) as _gen:
                    llm_t0           = time.monotonic()
                    result           = await llm.ainvoke(messages)
                    llm_ms           = (time.monotonic() - llm_t0) * 1000
                    answer           = result.answer
                    used_indices     = result.used_chunk_indices
                    uncertainty_note = result.uncertainty_note or ""
                    _gen.update(
                        output   = answer,
                        metadata = {"latency_ms": str(round(llm_ms, 1))},
                    )
            else:
                llm_t0           = time.monotonic()
                result           = await llm.ainvoke(messages)
                llm_ms           = (time.monotonic() - llm_t0) * 1000
                answer           = result.answer
                used_indices     = result.used_chunk_indices
                uncertainty_note = result.uncertainty_note or ""

            if not chunks:
                uncertainty_note = (
                    "No documents are ingested yet. Answer is from model training knowledge only — "
                    "ingest clinical guidelines to enable evidence-based responses with citations."
                )
        except Exception as exc:
            answer, used_indices = _fallback_response(query_text, chunks, disclaimer)
            uncertainty_note     = f"LLM synthesis failed ({exc}); showing raw retrieved chunks."
    else:
        answer, used_indices = _fallback_response(query_text, chunks, disclaimer)
        if not chunks:
            uncertainty_note = "No verified chunks were retrieved for this query."

    # Store ref_map as serialisable data for format_citations_node
    ref_map_serial = {
        str(n): c.model_dump() for n, c in ref_map.items()
    }

    # Persist to L0 response cache so repeated queries skip LLM entirely
    if chunks and answer:
        await _set_cached_response(resp_key, {
            "answer":           answer,
            "ref_map":          ref_map_serial,
            "used_indices":     used_indices,
            "uncertainty_note": uncertainty_note,
        })

    return {
        "final_response":      answer,
        "_ref_map":            ref_map_serial,
        "_used_indices":       used_indices,
        "_uncertainty_note":   uncertainty_note,
        "agent_timings":       {"response.synthesize_ms": (time.monotonic() - start) * 1000},
    }


# ── Streaming variant — yields answer text as it's generated instead of ──────
# ── waiting for the full structured-output response.                     ─────
#
# `sink` is a plain dict the caller passes in; this generator writes its
# side-channel results (ref_map, used_indices, uncertainty_note, cache flag)
# into it since an async generator can only `yield` one channel of data.

async def stream_synthesize_response(state: RAGState, sink: dict):
    query_text = state.get("raw_query", "")
    org_id     = state.get("organization_id", "")
    kb_id      = state.get("knowledge_base_id", "")
    raw        = state.get("verified_chunks", []) or state.get("retrieved_chunks", [])
    escalated  = state.get("requires_escalation", False)

    # ── L0: response cache — skip the LLM entirely on repeated queries ────────
    resp_key = _response_cache_key(query_text, org_id, kb_id)
    cached   = await _get_cached_response(resp_key)
    if cached:
        sink["ref_map"]          = cached.get("ref_map", {})
        sink["used_indices"]     = cached.get("used_indices", [])
        sink["uncertainty_note"] = cached.get("uncertainty_note", "")
        sink["from_l0_cache"]    = True
        yield cached["answer"]
        return

    chunks = [RetrievedChunk(**c) for c in raw[:5]]

    safety_flags = state.get("safety_flags", [])
    disclaimer   = next(
        (f["description"] for f in safety_flags if f.get("flag_type") == "clinical_disclaimer"),
        "This information is for educational purposes only. Consult a licensed clinician.",
    )

    context_text, ref_map  = _build_context(chunks)
    ref_map_serial         = {str(n): c.model_dump() for n, c in ref_map.items()}
    sink["ref_map"]        = ref_map_serial

    llm = _get_llm_stream()
    if llm is None:
        answer, used_indices     = _fallback_response(query_text, chunks, disclaimer)
        sink["used_indices"]     = used_indices
        sink["uncertainty_note"] = "No verified chunks were retrieved for this query." if not chunks else ""
        yield answer
        return

    from langchain_core.messages import HumanMessage, SystemMessage

    system_prompt = _SYSTEM_ESCALATED if escalated else _SYSTEM_STANDARD
    if escalated:
        system_prompt = system_prompt.replace(
            "Begin your answer with the safety disclaimer on its own line.",
            f"Begin your answer with this exact disclaimer on its own line:\n\"{disclaimer}\"",
        )

    effective_context = context_text if chunks else (
        "[No documents have been ingested into this knowledge base yet. "
        "Answer from general clinical knowledge and clearly state that no "
        "platform-specific guidelines were found.]"
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=_HUMAN_TMPL.format(
            query              = query_text,
            context            = effective_context,
            uncertainty_prompt = _UNCERTAINTY_HINT_STREAM,
        )),
    ]

    from observability.langfuse_handler import log_llm_generation_ctx
    from ingestion.config import get_settings as _gs
    _lf_client, _lf_tid = log_llm_generation_ctx()

    full_text = ""
    try:
        if _lf_client is not None:
            with _lf_client.start_as_current_observation(
                name    = "response-synthesis-stream",
                as_type = "generation",
                model   = _gs().llm_model,
                input   = messages[0].content[:2000] + "\n---\n" + messages[1].content[:2000],
            ) as _gen:
                async for chunk in llm.astream(messages):
                    piece = chunk.content or ""
                    if piece:
                        full_text += piece
                        yield piece
                _gen.update(output=full_text)
        else:
            async for chunk in llm.astream(messages):
                piece = chunk.content or ""
                if piece:
                    full_text += piece
                    yield piece
    except Exception as exc:
        answer, used_indices     = _fallback_response(query_text, chunks, disclaimer)
        sink["used_indices"]     = used_indices
        sink["uncertainty_note"] = f"LLM synthesis failed ({exc}); showing raw retrieved chunks."
        yield answer
        return

    uncertainty_note = _heuristic_uncertainty(full_text)
    if not chunks:
        uncertainty_note = (
            "No documents are ingested yet. Answer is from model training knowledge only — "
            "ingest clinical guidelines to enable evidence-based responses with citations."
        )

    sink["used_indices"]     = []
    sink["uncertainty_note"] = uncertainty_note

    if chunks and full_text:
        await _set_cached_response(resp_key, {
            "answer":           full_text,
            "ref_map":          ref_map_serial,
            "used_indices":     [],
            "uncertainty_note": uncertainty_note,
        })


# ── Node 2: Build structured citations list ───────────────────────────────────

async def format_citations_node(state: RAGState) -> dict:
    start        = time.monotonic()
    answer       = state.get("final_response", "")
    ref_map_raw  = state.get("_ref_map", {})
    used_indices = state.get("_used_indices", [])

    # Parse [N] from the answer text in case LLM cited differently
    cited_from_text = {int(m) for m in _CITE_RE.findall(answer)}
    all_cited       = sorted(cited_from_text | set(used_indices))

    citations: list[dict[str, Any]] = []
    for ref_num in all_cited:
        chunk_data = ref_map_raw.get(str(ref_num))
        if not chunk_data:
            continue

        chunk  = RetrievedChunk(**chunk_data)
        source = chunk.source.value
        meta   = chunk.metadata

        base: dict[str, Any] = {
            "ref_number":  ref_num,
            "chunk_id":    chunk.chunk_id,
            "document_id": chunk.document_id,
            "source":      source,
            "is_external": bool(meta.get("is_external", source == "pubmed")),
        }

        if source == "pubmed":
            pmid = meta.get("pmid", "")
            base.update({
                "title":   meta.get("title", ""),
                "authors": meta.get("authors", []),
                "journal": meta.get("journal", ""),
                "year":    meta.get("year", ""),
                "doi":     meta.get("doi", ""),
                "pmid":    pmid,
                "url":     f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
            })
        else:
            base.update({
                "document_type":   meta.get("document_type", ""),
                "specialty":       meta.get("specialty", ""),
                "section":         meta.get("section", ""),
                "approval_status": meta.get("approval_status", "approved"),
                "citation_score":  meta.get("citation_score", chunk.score),
            })

        citations.append(base)

    return {
        "citations":     citations,
        "agent_timings": {"response.citations_ms": (time.monotonic() - start) * 1000},
    }


# ── Node 3: Compute confidence score ─────────────────────────────────────────

async def compute_confidence_node(state: RAGState) -> dict:
    start        = time.monotonic()
    citations    = state.get("citations", [])
    cit_scores   = state.get("citation_scores", {})
    contradicts  = state.get("contradictions", [])
    escalated    = state.get("requires_escalation", False)
    uncertainty  = state.get("_uncertainty_note", "")
    raw_chunks   = state.get("verified_chunks", [])

    if not raw_chunks:
        return {
            "confidence_score": 0.0,
            "agent_timings":    {"response.confidence_ms": (time.monotonic() - start) * 1000},
        }

    chunks = [RetrievedChunk(**c) for c in raw_chunks[:5]]

    # Base: mean citation score of chunks that were actually cited
    cited_ids  = {c["chunk_id"] for c in citations}
    used_scores = [
        cit_scores.get(ch.chunk_id, ch.score)
        for ch in chunks
        if ch.chunk_id in cited_ids
    ] or [cit_scores.get(ch.chunk_id, ch.score) for ch in chunks[:3]]
    base = sum(used_scores) / len(used_scores)

    # Source diversity: multiple independent sources agreeing → +confidence
    unique_sources    = len({c["source"] for c in citations})
    diversity_bonus   = min((unique_sources - 1) * 0.05, 0.15)

    # Penalties
    contradiction_pen = -0.15 if contradicts else 0.0
    escalation_pen    = -0.10 if escalated else 0.0
    uncertainty_pen   = -0.10 if uncertainty else 0.0

    score = base + diversity_bonus + contradiction_pen + escalation_pen + uncertainty_pen
    score = round(max(0.0, min(score, 1.0)), 3)

    return {
        "confidence_score": score,
        "agent_timings":    {"response.confidence_ms": (time.monotonic() - start) * 1000},
    }
