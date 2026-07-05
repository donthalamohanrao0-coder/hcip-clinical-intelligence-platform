from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from .query import RetrievalSource


class RetrievedChunk(BaseModel):
    """A single chunk returned by any retriever, normalised to a common schema."""

    chunk_id:    str
    document_id: str
    content:     str
    score:       float            # normalised 0–1 within its source
    rank:        int              # 0-based rank within its source
    source:      RetrievalSource
    metadata:    dict[str, Any]  = {}
    rrf_score:   float           = 0.0   # set by HybridRetriever after RRF fusion


class RetrievalResult(BaseModel):
    """Output from a single retriever."""

    source:     RetrievalSource
    chunks:     list[RetrievedChunk] = []
    latency_ms: float               = 0.0
    error:      Optional[str]       = None

    @property
    def success(self) -> bool:
        return self.error is None


class FusedResult(BaseModel):
    """Final output from HybridRetriever after RRF fusion across all sources."""

    query_text:       str
    chunks:           list[RetrievedChunk]       = []
    source_results:   dict[str, RetrievalResult] = {}
    total_latency_ms: float                      = 0.0
    sources_used:     list[RetrievalSource]      = []

    @property
    def top_chunk(self) -> Optional[RetrievedChunk]:
        return self.chunks[0] if self.chunks else None

    @property
    def source_breakdown(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for chunk in self.chunks:
            counts[chunk.source.value] = counts.get(chunk.source.value, 0) + 1
        return counts
