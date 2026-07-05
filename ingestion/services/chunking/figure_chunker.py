from __future__ import annotations

from ingestion.models import Chunk, ChunkType, DocumentMetadata, ParsedContent, RiskLevel

from .base_chunker import BaseChunker


class FigureChunker(BaseChunker):
    """
    Produces one Chunk per FigureElement.

    Content = caption text prefixed with a type tag ([CHART] or [FORM]).
    The chunk's section field stores the S3 key so the EmbeddingPipeline
    can locate the image bytes for ColQwen embedding without an extra DB lookup.
    """

    @property
    def chunk_type(self) -> ChunkType:
        return ChunkType.FIGURE

    def _do_chunk(
        self,
        content:          ParsedContent,
        document_id:      str,
        document_version: str,
        doc_metadata:     DocumentMetadata,
        risk_level:       RiskLevel,
    ) -> list[Chunk]:
        chunks = []
        for idx, figure in enumerate(content.figures):
            caption = figure.caption.strip() or f"Figure {idx + 1}"
            if figure.has_chart:
                text = f"[CHART] {caption}"
            elif figure.has_form:
                text = f"[FORM] {caption}"
            else:
                text = caption

            chunk = self._make_chunk(
                text             = text,
                document_id      = document_id,
                document_version = document_version,
                doc_metadata     = doc_metadata,
                risk_level       = risk_level,
                chunk_index      = idx,
                chunk_type       = ChunkType.FIGURE,
                section          = figure.s3_key,   # EmbeddingPipeline reads this for ColQwen
                page_number      = figure.page_number or None,
            )
            chunks.append(chunk)
        return chunks
