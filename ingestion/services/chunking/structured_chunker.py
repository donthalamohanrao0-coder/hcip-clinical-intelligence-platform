from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET

from ingestion.models import Chunk, ChunkType, DocumentMetadata, FileType, ParsedContent, RiskLevel

from .base_chunker import BaseChunker

logger = logging.getLogger(__name__)


class StructuredChunker(BaseChunker):
    """
    Splits structured data files (JSON, XML, FHIR) into meaningful chunks.

    Strategy:
        JSON   — one chunk per top-level key (or per item in a top-level array)
        XML    — one chunk per direct child of the root element
        FHIR   — treated as JSON; one chunk per resource entry
        Other  — falls back to SentenceChunker behaviour on the raw text

    This prevents the entire structured document from becoming one massive chunk
    while keeping semantically related fields together.
    """

    @property
    def chunk_type(self) -> ChunkType:
        return ChunkType.TEXT

    def __init__(
        self,
        file_type:    FileType = FileType.JSON,
        max_tokens:   int      = 512,
        overlap_tokens: int    = 50,
    ) -> None:
        self._file_type     = file_type
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
        if self._file_type in (FileType.JSON, FileType.FHIR):
            segments = self._split_json(content.text)
        elif self._file_type == FileType.XML:
            segments = self._split_xml(content.text)
        else:
            segments = None

        if not segments:
            # Fall back to sentence grouping on the raw text
            sentences = self._split_sentences(content.text) or [content.text]
            segments  = self._group_by_tokens(sentences, self.MAX_TOKENS)

        chunks = []
        for idx, seg in enumerate(segments):
            if not seg.strip():
                continue
            chunks.append(self._make_chunk(
                text             = seg,
                document_id      = document_id,
                document_version = document_version,
                doc_metadata     = doc_metadata,
                risk_level       = risk_level,
                chunk_index      = idx,
            ))
        return chunks

    # ── JSON / FHIR ───────────────────────────────────────────────────────────

    @staticmethod
    def _split_json(raw: str) -> list[str] | None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None

        segments: list[str] = []

        # FHIR Bundle / top-level array
        if isinstance(data, list):
            for item in data:
                segments.append(json.dumps(item, indent=2))
            return segments or None

        # FHIR Bundle with entry array
        if isinstance(data, dict):
            entries = data.get("entry") or data.get("Entry")
            if isinstance(entries, list):
                for entry in entries:
                    segments.append(json.dumps(entry, indent=2))
                return segments or None

            # Generic JSON object — one chunk per top-level key
            for key, value in data.items():
                segments.append(f"{key}:\n{json.dumps(value, indent=2)}")
            return segments or None

        return None

    # ── XML ───────────────────────────────────────────────────────────────────

    @staticmethod
    def _split_xml(raw: str) -> list[str] | None:
        try:
            root     = ET.fromstring(raw)
            segments = []
            for child in root:
                segments.append(ET.tostring(child, encoding="unicode"))
            return segments or None
        except ET.ParseError as exc:
            logger.debug("XML parse failed: %s", exc)
            return None
