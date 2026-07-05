from __future__ import annotations

import re

from ingestion.models import (
    Chunk,
    ChunkType,
    DocumentMetadata,
    HeadingElement,
    ParsedContent,
    RiskLevel,
)

from .base_chunker import BaseChunker


class MarkdownChunker(BaseChunker):
    """
    Splits documents along heading boundaries extracted by the parser.

    Strategy:
        1. Build a list of (heading_text, heading_level) boundaries
        2. Find each heading in the full text and record its position
        3. Slice the text between consecutive heading positions
        4. Sub-split any section larger than MAX_TOKENS with sentence grouping
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
        if not content.headings:
            # No headings → sentence-group the whole text
            return self._sentence_chunks(
                content.text, "", "", document_id, document_version,
                doc_metadata, risk_level, start_index=0,
            )

        sections = self._extract_sections(content.text, content.headings)
        chunks: list[Chunk] = []
        global_idx = 0
        for heading, section_text, parent_heading in sections:
            section_chunks = self._sentence_chunks(
                section_text,
                section=heading.text,
                subsection=parent_heading,
                document_id=document_id,
                document_version=document_version,
                doc_metadata=doc_metadata,
                risk_level=risk_level,
                start_index=global_idx,
            )
            chunks.extend(section_chunks)
            global_idx += len(section_chunks)

        return chunks

    # ── Private helpers ───────────────────────────────────────────────────────

    def _extract_sections(
        self,
        text: str,
        headings: list[HeadingElement],
    ) -> list[tuple[HeadingElement, str, str]]:
        """
        Returns list of (heading, section_text, parent_heading_text).
        Uses case-insensitive search to locate each heading in the full text.
        """
        # Find byte positions of each heading in the document text
        positions: list[tuple[int, HeadingElement]] = []
        for heading in headings:
            # Escape regex special chars in the heading text
            escaped = re.escape(heading.text.strip())
            match   = re.search(escaped, text, re.IGNORECASE)
            if match:
                positions.append((match.start(), heading))

        if not positions:
            # Headings not found in text (e.g., scanned doc) — return whole text
            return [(headings[0], text, "")]

        positions.sort(key=lambda x: x[0])

        sections = []
        parent   = ""
        for i, (pos, heading) in enumerate(positions):
            end          = positions[i + 1][0] if i + 1 < len(positions) else len(text)
            section_text = text[pos:end].strip()
            sections.append((heading, section_text, parent))
            if heading.level == 1:
                parent = heading.text

        return sections

    def _sentence_chunks(
        self,
        text:             str,
        section:          str,
        subsection:       str,
        document_id:      str,
        document_version: str,
        doc_metadata:     DocumentMetadata,
        risk_level:       RiskLevel,
        start_index:      int,
    ) -> list[Chunk]:
        sentences = self._split_sentences(text) or [text]
        windows   = self._group_by_tokens(sentences, self.MAX_TOKENS, self.OVERLAP_TOKENS)
        chunks    = []
        for i, window in enumerate(windows):
            chunks.append(self._make_chunk(
                text             = window,
                document_id      = document_id,
                document_version = document_version,
                doc_metadata     = doc_metadata,
                risk_level       = risk_level,
                chunk_index      = start_index + i,
                section          = section,
                subsection       = subsection,
            ))
        return chunks
