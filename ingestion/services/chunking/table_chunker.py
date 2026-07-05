from __future__ import annotations

from ingestion.models import Chunk, ChunkType, DocumentMetadata, ParsedContent, RiskLevel

from .base_chunker import BaseChunker


class TableChunker(BaseChunker):
    """
    Produces one Chunk per TableElement using pipe-delimited serialization.

    Tables are never merged with adjacent text — they live in the TABLE
    collection in Qdrant and are embedded separately from prose chunks.
    """

    @property
    def chunk_type(self) -> ChunkType:
        return ChunkType.TABLE

    def _do_chunk(
        self,
        content:          ParsedContent,
        document_id:      str,
        document_version: str,
        doc_metadata:     DocumentMetadata,
        risk_level:       RiskLevel,
    ) -> list[Chunk]:
        chunks = []
        for idx, table in enumerate(content.tables):
            text = table.to_text().strip()
            if not text:
                continue
            chunks.append(self._make_chunk(
                text             = text,
                document_id      = document_id,
                document_version = document_version,
                doc_metadata     = doc_metadata,
                risk_level       = risk_level,
                chunk_index      = idx,
                chunk_type       = ChunkType.TABLE,
                section          = table.caption or f"Table {idx + 1}",
                page_number      = table.page_number or None,
            ))
        return chunks
