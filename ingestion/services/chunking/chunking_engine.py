from __future__ import annotations

import logging
from typing import Optional

from ingestion.config import Settings, get_settings
from ingestion.exceptions import ChunkingError
from ingestion.models import (
    Chunk,
    DocumentMetadata,
    DocumentType,
    FileType,
    ParsedContent,
    RiskLevel,
)

from .figure_chunker import FigureChunker
from .markdown_chunker import MarkdownChunker
from .semantic_chunker import SemanticChunker
from .sentence_chunker import SentenceChunker
from .sliding_window_chunker import SlidingWindowChunker
from .structured_chunker import StructuredChunker
from .table_chunker import TableChunker

logger = logging.getLogger(__name__)

# Text length (chars) threshold that triggers SemanticChunker for research papers
_SEMANTIC_MIN_CHARS = 8_000


class ChunkingEngine:
    """
    Orchestrates the full chunking pipeline for a single document.

    Selection logic (text chunker):
        1. FileType.is_structured       → StructuredChunker
        2. Research paper + long text   → SemanticChunker (expensive; GPU)
        3. Document has headings        → MarkdownChunker
        4. Default                      → SentenceChunker
        5. Fallback (no sentences)      → SlidingWindowChunker

    Structural elements always run in parallel with the text chunker:
        • Tables  → TableChunker  (ChunkType.TABLE)
        • Figures → FigureChunker (ChunkType.FIGURE)

    Chunk indices are re-assigned globally after combining all chunker outputs.
    """

    def __init__(
        self,
        settings:              Optional[Settings] = None,
        enable_semantic:       bool = False,   # opt-in — expensive
        max_tokens:            int  = 512,
        overlap_tokens:        int  = 50,
    ) -> None:
        self._cfg             = settings or get_settings()
        self._enable_semantic = enable_semantic

        # One instance per engine; all share the same token budget
        self._sentence    = SentenceChunker(max_tokens, overlap_tokens)
        self._sliding     = SlidingWindowChunker(max_tokens, overlap_tokens)
        self._markdown    = MarkdownChunker(max_tokens, overlap_tokens)
        self._semantic    = SemanticChunker(max_tokens) if enable_semantic else None
        self._table       = TableChunker()
        self._figure      = FigureChunker()

    def chunk(
        self,
        content:          ParsedContent,
        document_id:      str,
        document_version: str,
        doc_metadata:     DocumentMetadata,
        file_type:        FileType,
        doc_type:         DocumentType,
        risk_level:       RiskLevel = RiskLevel.LOW,
    ) -> list[Chunk]:
        """
        Produce a complete list of Chunk objects for the given document.
        Raises ChunkingError if no chunks could be produced.
        """
        all_chunks: list[Chunk] = []

        # ── Text chunks ───────────────────────────────────────────────────────
        text_chunker = self._select_text_chunker(content, file_type, doc_type)

        if file_type.is_structured:
            # Pass file_type awareness to StructuredChunker
            text_chunker = StructuredChunker(
                file_type     = file_type,
                max_tokens    = self._sentence.MAX_TOKENS,
                overlap_tokens= self._sentence.OVERLAP_TOKENS,
            )

        all_chunks.extend(
            text_chunker.chunk(content, document_id, document_version, doc_metadata, risk_level)
        )

        # ── Table chunks ──────────────────────────────────────────────────────
        if content.tables:
            all_chunks.extend(
                self._table.chunk(content, document_id, document_version, doc_metadata, risk_level)
            )

        # ── Figure chunks ─────────────────────────────────────────────────────
        if content.figures:
            all_chunks.extend(
                self._figure.chunk(content, document_id, document_version, doc_metadata, risk_level)
            )

        if not all_chunks:
            raise ChunkingError(f"No chunks produced for document={document_id}")

        # Re-assign sequential chunk_index across all chunk types
        for idx, chunk in enumerate(all_chunks):
            chunk.metadata.chunk_index = idx

        logger.info(
            "ChunkingEngine | doc=%s total_chunks=%d (text=%d tables=%d figures=%d)",
            document_id,
            len(all_chunks),
            sum(1 for c in all_chunks if c.chunk_type.value == "text"),
            sum(1 for c in all_chunks if c.chunk_type.value == "table"),
            sum(1 for c in all_chunks if c.chunk_type.value == "figure"),
        )
        return all_chunks

    # ── Private ───────────────────────────────────────────────────────────────

    def _select_text_chunker(
        self,
        content:   ParsedContent,
        file_type: FileType,
        doc_type:  DocumentType,
    ):
        # Structured data → StructuredChunker (re-instantiated in chunk() with file_type)
        if file_type.is_structured:
            return self._sentence  # placeholder — overridden in chunk()

        # Research papers with substantial text → semantic grouping (if enabled)
        if (
            self._enable_semantic
            and self._semantic is not None
            and doc_type == DocumentType.RESEARCH_PAPER
            and len(content.text) >= _SEMANTIC_MIN_CHARS
        ):
            return self._semantic

        # Documents with heading structure → section-based chunks
        if content.headings:
            return self._markdown

        # Prose text without structure → sentence-boundary grouping
        sentences = self._sentence._split_sentences(content.text)
        if sentences:
            return self._sentence

        # Last resort — pure sliding window on any text
        return self._sliding
