from __future__ import annotations

from ingestion.models import Chunk, ChunkType, DocumentMetadata, ParsedContent, RiskLevel

from .base_chunker import BaseChunker


class SlidingWindowChunker(BaseChunker):
    """
    Splits text into fixed-size token windows with configurable overlap.

    This is the universal fallback chunker — it works on any plain text
    with no structure assumptions. Used when no headings are present and
    semantic / sentence chunking is not viable.
    """

    @property
    def chunk_type(self) -> ChunkType:
        return ChunkType.TEXT

    def __init__(self, max_tokens: int = 512, overlap_tokens: int = 50) -> None:
        self.MAX_TOKENS     = max_tokens
        self.OVERLAP_TOKENS = overlap_tokens

    def _do_chunk(
        self,
        content:          ParsedContent,
        document_id:      str,
        document_version: str,
        doc_metadata:     DocumentMetadata,
        risk_level:       RiskLevel,
    ) -> list[Chunk]:
        # Split at word boundaries for cleaner windows
        words    = content.text.split()
        windows  = self._make_windows(words)
        chunks   = []
        for idx, window_text in enumerate(windows):
            chunks.append(self._make_chunk(
                text             = window_text,
                document_id      = document_id,
                document_version = document_version,
                doc_metadata     = doc_metadata,
                risk_level       = risk_level,
                chunk_index      = idx,
            ))
        return chunks

    def _make_windows(self, words: list[str]) -> list[str]:
        """Create overlapping word-level windows."""
        step       = max(1, self.MAX_TOKENS - self.OVERLAP_TOKENS)
        # Convert token budget to word budget (rough: 1 token ≈ 1.3 words)
        max_words  = int(self.MAX_TOKENS * 1.3)
        step_words = int(step * 1.3)

        windows = []
        start   = 0
        while start < len(words):
            end = min(start + max_words, len(words))
            windows.append(" ".join(words[start:end]))
            if end == len(words):
                break
            start += step_words
        return windows
