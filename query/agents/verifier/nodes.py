"""
Async node functions for the Verifier Agent.

Graph:
    START → score_citations → detect_contradictions → filter_chunks → END
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from query.agents.state import RAGState
from query.models.result import RetrievedChunk

# ── Citation scoring constants ────────────────────────────────────────────────

# Base citation confidence by retrieval source
_SOURCE_CREDIBILITY: dict[str, float] = {
    "qdrant":        0.90,   # dense semantic match on org-vetted content
    "elasticsearch": 0.80,   # BM25 keyword match on org-vetted content
    "neo4j":         0.75,   # graph structural match — less content quality signal
    "pubmed":        0.78,   # external peer-reviewed evidence, not org-vetted
}

# Document-type credibility multiplier (from chunk metadata)
_DOC_TYPE_MULT: dict[str, float] = {
    "clinical_guideline": 1.00,
    "drug_reference":     0.97,
    "research_paper":     0.92,
    "sop":                0.88,
    "lab_report":         0.83,
    "insurance_policy":   0.75,
    "general":            0.70,
    "":                   0.80,  # unknown type
}

_CITATION_THRESHOLD  = 0.50   # chunks below this are filtered (unless < MIN_CHUNKS remain)
_MIN_VERIFIED_CHUNKS = 3      # always surface at least this many chunks

# ── Number pattern for contradiction detection ────────────────────────────────
_DOSE_RE = re.compile(r'\b(\d+(?:\.\d+)?)\s*(mg|mcg|mg/kg|ml|g|iu|units?)\b', re.I)

# ── LLM batch verification (lazy, optional) ───────────────────────────────────
_llm_verifier = None


def _get_llm_verifier():
    """Returns a structured-output chain, or None when unavailable."""
    global _llm_verifier
    if _llm_verifier is not None:
        return None if _llm_verifier == "unavailable" else _llm_verifier

    from ingestion.config import get_settings
    cfg = get_settings()
    if not cfg.openai_api_key or cfg.openai_api_key.startswith("REPLACE"):
        _llm_verifier = "unavailable"
        return None

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI
        from pydantic import BaseModel, Field

        class _ChunkScore(BaseModel):
            chunk_id:   str
            relevance:  float = Field(ge=0.0, le=1.0)
            confidence: float = Field(ge=0.0, le=1.0)
            flags:      list[str] = []

        class _BatchVerification(BaseModel):
            scores: list[_ChunkScore]

        llm = ChatOpenAI(model=cfg.llm_model, temperature=0, api_key=cfg.openai_api_key)
        _llm_verifier = (llm.with_structured_output(_BatchVerification), _ChunkScore)
    except Exception:
        _llm_verifier = "unavailable"
        return None

    return _llm_verifier


_VERIFY_SYSTEM = """\
You are a clinical citation verifier for an enterprise healthcare knowledge platform.
For each chunk evaluate how well it supports the clinical query.

Return one score per chunk. chunk_id must match exactly.

relevance  : 0–1 — does this chunk directly address the query?
confidence : 0–1 — how reliable is this as a citable clinical source?
flags      : list of concerns, e.g. ["outdated", "speculative", "contradicts_guideline",
             "dose_mentioned", "off_label", "animal_study_only"]
"""


async def _llm_verify_batch(
    query_text: str, specialty: str, chunks: list[RetrievedChunk]
) -> dict[str, dict]:
    """Call LLM once for up to 8 chunks; returns {chunk_id: {relevance, confidence, flags}}."""
    verifier_tuple = _get_llm_verifier()
    if verifier_tuple is None:
        return {}

    verifier, _ = verifier_tuple

    # Compact chunk representations to keep prompt short
    chunks_data = [
        {
            "chunk_id":      c.chunk_id,
            "source":        c.source.value,
            "doc_type":      c.metadata.get("document_type", ""),
            "specialty":     c.metadata.get("specialty", ""),
            "content":       c.content[:400],
        }
        for c in chunks[:8]
    ]

    from langchain_core.messages import HumanMessage, SystemMessage
    messages = [
        SystemMessage(content=_VERIFY_SYSTEM),
        HumanMessage(content=(
            f"Clinical query: {query_text}\n"
            f"Query specialty: {specialty}\n\n"
            f"Chunks to verify:\n{json.dumps(chunks_data, indent=2)}"
        )),
    ]

    try:
        result = await verifier.ainvoke(messages)
        return {
            s.chunk_id: {"relevance": s.relevance, "confidence": s.confidence, "flags": s.flags}
            for s in result.scores
        }
    except Exception:
        return {}


# ── Node 1: Score citations ────────────────────────────────────────────────────

async def score_citations_node(state: RAGState) -> dict:
    start     = time.monotonic()
    raw       = state.get("retrieved_chunks", [])
    specialty = state.get("medical_specialty", "general")

    if not raw:
        return {
            "citation_scores": {},
            "agent_timings":   {"verifier.score_ms": 0.0},
        }

    chunks = [RetrievedChunk(**c) for c in raw]

    # Heuristic scoring only — LLM batch verification removed.
    # The LLM verifier added 700-1000ms + ~1800 tokens per query with marginal
    # quality gain over the source-credibility + doc-type heuristic below.
    citation_scores: dict[str, float] = {
        c.chunk_id: round(_heuristic_score(c, specialty), 4) for c in chunks
    }
    flagged_chunks = chunks  # no LLM flags to attach

    return {
        "citation_scores":  citation_scores,
        "retrieved_chunks": [c.model_dump() for c in flagged_chunks],
        "agent_timings":    {"verifier.score_ms": (time.monotonic() - start) * 1000},
    }


def _heuristic_score(chunk: RetrievedChunk, query_specialty: str) -> float:
    source_score  = _SOURCE_CREDIBILITY.get(chunk.source.value, 0.75)
    doc_type      = chunk.metadata.get("document_type", "")
    doc_mult      = _DOC_TYPE_MULT.get(doc_type, 0.80)
    chunk_spec    = chunk.metadata.get("specialty", "general")
    specialty_mult = 1.05 if (chunk_spec == query_specialty and query_specialty != "general") else 1.0
    rrf_component = min(chunk.rrf_score * 20, 0.15)  # RRF contributes up to +0.15
    return min(source_score * doc_mult * specialty_mult + rrf_component, 1.0)


# ── Node 2: Detect contradictions ─────────────────────────────────────────────

async def detect_contradictions_node(state: RAGState) -> dict:
    start  = time.monotonic()
    raw    = state.get("retrieved_chunks", [])
    scores = state.get("citation_scores", {})

    if len(raw) < 2:
        return {
            "contradictions": [],
            "agent_timings":  {"verifier.contradict_ms": (time.monotonic() - start) * 1000},
        }

    chunks = [RetrievedChunk(**c) for c in raw]
    # Only check high-confidence chunks (low-confidence chunks aren't worth comparing)
    candidates = [c for c in chunks if scores.get(c.chunk_id, 0) >= 0.5]

    contradictions: list[dict[str, Any]] = []

    for i, a in enumerate(candidates):
        for b in candidates[i + 1:]:
            shared = _shared_entities(a, b)
            if not shared:
                continue

            conflict = _find_dose_conflict(a.content, b.content)
            if conflict:
                contradictions.append({
                    "chunk_id_a":  a.chunk_id,
                    "chunk_id_b":  b.chunk_id,
                    "shared_entities": shared,
                    "conflict_type":   "dose_discrepancy",
                    "detail":          conflict,
                    "confidence":      0.80,
                })
                continue

            if _has_negation_conflict(a.content, b.content, shared):
                contradictions.append({
                    "chunk_id_a":  a.chunk_id,
                    "chunk_id_b":  b.chunk_id,
                    "shared_entities": shared,
                    "conflict_type":   "treatment_recommendation",
                    "detail":          "Chunks make opposing treatment recommendations",
                    "confidence":      0.65,
                })

    return {
        "contradictions": contradictions,
        "agent_timings":  {"verifier.contradict_ms": (time.monotonic() - start) * 1000},
    }


def _shared_entities(a: RetrievedChunk, b: RetrievedChunk) -> list[str]:
    def _entity_set(c: RetrievedChunk) -> set[str]:
        entities = (
            c.metadata.get("entities")
            or c.metadata.get("matched_entities")
            or []
        )
        return {str(e).lower() for e in entities if len(str(e)) >= 4}

    overlap = _entity_set(a) & _entity_set(b)
    return list(overlap)


def _find_dose_conflict(text_a: str, text_b: str) -> Optional[str]:
    doses_a = {unit: vals for vals, unit in [m.groups() for m in _DOSE_RE.finditer(text_a)]}
    doses_b = {unit: vals for vals, unit in [m.groups() for m in _DOSE_RE.finditer(text_b)]}

    for unit in set(doses_a) & set(doses_b):
        val_a = float(doses_a[unit])
        val_b = float(doses_b[unit])
        if val_a > 0 and abs(val_a - val_b) / val_a > 0.20:   # >20% difference
            return f"Dose conflict for {unit}: {val_a} vs {val_b}"

    return None


_RECOMMEND_RE     = re.compile(r'\b(recommend|indicated|first.?line|preferred|effective)\b', re.I)
_CONTRAINDICATE_RE = re.compile(r'\b(contraindicated|not recommended|avoid|unsafe|prohibited)\b', re.I)


def _has_negation_conflict(text_a: str, text_b: str, shared_entities: list[str]) -> bool:
    for entity in shared_entities:
        near_a = _text_near_entity(text_a, entity)
        near_b = _text_near_entity(text_b, entity)
        if not near_a or not near_b:
            continue
        a_recommends    = bool(_RECOMMEND_RE.search(near_a))
        a_contraindicates = bool(_CONTRAINDICATE_RE.search(near_a))
        b_recommends    = bool(_RECOMMEND_RE.search(near_b))
        b_contraindicates = bool(_CONTRAINDICATE_RE.search(near_b))
        if (a_recommends and b_contraindicates) or (a_contraindicates and b_recommends):
            return True
    return False


def _text_near_entity(text: str, entity: str, window: int = 150) -> str:
    """Return up to `window` chars around the first occurrence of entity in text."""
    idx = text.lower().find(entity.lower())
    if idx == -1:
        return ""
    return text[max(0, idx - window // 2): idx + window // 2]


# ── Node 3: Filter to verified chunks ─────────────────────────────────────────

async def filter_chunks_node(state: RAGState) -> dict:
    start  = time.monotonic()
    raw    = state.get("retrieved_chunks", [])
    scores = state.get("citation_scores", {})
    contrs = state.get("contradictions", [])

    if not raw:
        return {
            "verified_chunks": [],
            "agent_timings":   {"verifier.filter_ms": (time.monotonic() - start) * 1000},
        }

    # Build contradiction set for metadata tagging
    contradicted_ids: set[str] = set()
    for c in contrs:
        contradicted_ids.add(c["chunk_id_a"])
        contradicted_ids.add(c["chunk_id_b"])

    # Score + tag chunks
    chunks = [RetrievedChunk(**c) for c in raw]
    scored = sorted(
        [
            (c, scores.get(c.chunk_id, 0.5))
            for c in chunks
        ],
        key=lambda x: x[1],
        reverse=True,
    )

    # Apply threshold, but always surface at least MIN_VERIFIED_CHUNKS
    above_threshold = [(c, s) for c, s in scored if s >= _CITATION_THRESHOLD]
    final_pairs     = above_threshold if len(above_threshold) >= _MIN_VERIFIED_CHUNKS else scored[:_MIN_VERIFIED_CHUNKS]

    verified = []
    for rank, (chunk, score) in enumerate(final_pairs):
        extra_meta: dict[str, Any] = {
            "citation_score":  score,
            "verified_rank":   rank,
        }
        if chunk.chunk_id in contradicted_ids:
            extra_meta["has_contradiction"] = True
        chunk = chunk.model_copy(update={"metadata": {**chunk.metadata, **extra_meta}})
        verified.append(chunk)

    return {
        "verified_chunks": [c.model_dump() for c in verified],
        "agent_timings":   {"verifier.filter_ms": (time.monotonic() - start) * 1000},
    }
