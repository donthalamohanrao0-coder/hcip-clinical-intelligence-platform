from __future__ import annotations

from ingestion.models import Chunk, ChunkType, DocumentMetadata, ParsedContent, RiskLevel

from .base_chunker import BaseChunker


class SentenceChunker(BaseChunker):
    """
    Splits text at sentence boundaries, then groups sentences into token-budget chunks.

    Preferred over SlidingWindowChunker for most prose-heavy documents because
    it never cuts mid-sentence, producing more coherent chunks for embedding.
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
        sentences = self._split_sentences(content.text)
        if not sentences:
            sentences = [content.text]

        windows = self._group_by_tokens(sentences, self.MAX_TOKENS, self.OVERLAP_TOKENS)
        chunks  = []
        for idx, window in enumerate(windows):
            chunks.append(self._make_chunk(
                text             = window,
                document_id      = document_id,
                document_version = document_version,
                doc_metadata     = doc_metadata,
                risk_level       = risk_level,
                chunk_index      = idx,
            ))
        return chunks
