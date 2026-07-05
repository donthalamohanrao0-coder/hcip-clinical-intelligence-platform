from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import Optional
from uuid import uuid4

from ingestion.exceptions import ChunkingError
from ingestion.models import (
    Chunk,
    ChunkMetadata,
    ChunkType,
    DocumentMetadata,
    ParsedContent,
    RiskLevel,
)

logger = logging.getLogger(__name__)

# Rough token budget per chunk (1 token ≈ 4 chars)
DEFAULT_MAX_TOKENS   = 512
DEFAULT_OVERLAP_TOKENS = 50
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"])")


class BaseChunker(ABC):
    """
    Abstract base for all chunking strategies.

    Template method pattern:
        chunk()   — public entry point; handles timing, error wrapping, logging
        _do_chunk() — subclass implements the actual splitting logic
        _make_chunk() — shared helper to build a Chunk + ChunkMetadata
    """

    MAX_TOKENS     = DEFAULT_MAX_TOKENS
    OVERLAP_TOKENS = DEFAULT_OVERLAP_TOKENS

    @property
    @abstractmethod
    def chunk_type(self) -> ChunkType: ...

    @abstractmethod
    def _do_chunk(
        self,
        content:          ParsedContent,
        document_id:      str,
        document_version: str,
        doc_metadata:     DocumentMetadata,
        risk_level:       RiskLevel,
    ) -> list[Chunk]: ...

    def chunk(
        self,
        content:          ParsedContent,
        document_id:      str,
        document_version: str,
        doc_metadata:     DocumentMetadata,
        risk_level:       RiskLevel,
    ) -> list[Chunk]:
        try:
            chunks = self._do_chunk(
                content, document_id, document_version, doc_metadata, risk_level
            )
            logger.info(
                "%s | doc=%s chunks=%d",
                self.__class__.__name__, document_id, len(chunks),
            )
            return chunks
        except ChunkingError:
            raise
        except Exception as exc:
            raise ChunkingError(
                f"{self.__class__.__name__} failed for doc={document_id}: {exc}"
            ) from exc

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _make_chunk(
        self,
        text:             str,
        document_id:      str,
        document_version: str,
        doc_metadata:     DocumentMetadata,
        risk_level:       RiskLevel,
        chunk_index:      int,
        chunk_type:       Optional[ChunkType] = None,
        section:          str = "",
        subsection:       str = "",
        page_number:      Optional[int] = None,
    ) -> Chunk:
        """Build a Chunk with fully populated ChunkMetadata."""
        cid   = str(uuid4())
        ctype = chunk_type or self.chunk_type
        meta  = ChunkMetadata(
            chunk_id          = cid,
            document_id       = document_id,
            organization_id   = doc_metadata.organization_id,
            department_id     = doc_metadata.department_id,
            knowledge_base_id = doc_metadata.knowledge_base_id,
            document_version  = document_version,
            specialty         = doc_metadata.medical_specialty.value,
            source            = doc_metadata.source,
            document_type     = doc_metadata.document_type,
            approval_status   = doc_metadata.approval_status,
            risk_level        = risk_level,
            entities          = doc_metadata.medical.all_entities[:20],
            section           = section,
            subsection        = subsection,
            chunk_index       = chunk_index,
            page_number       = page_number,
        )
        return Chunk(
            chunk_id        = cid,
            document_id     = document_id,
            content         = text.strip(),
            chunk_type      = ctype,
            metadata        = meta,
        )

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text at sentence boundaries using punctuation regex."""
        sentences = _SENTENCE_SPLIT.split(text)
        return [s.strip() for s in sentences if s.strip()]

    @staticmethod
    def _group_by_tokens(
        segments: list[str],
        max_tokens: int,
        overlap_tokens: int = 0,
    ) -> list[str]:
        """
        Greedily group text segments into windows of at most max_tokens each.
        Overlap is implemented by re-including the last overlap_tokens worth of
        text from the previous window at the start of the next one.
        """
        max_chars     = max_tokens * 4
        overlap_chars = overlap_tokens * 4
        groups: list[str]  = []
        current_parts: list[str] = []
        current_len  = 0
        tail         = ""   # overlap carried from previous group

        for seg in segments:
            seg_len = len(seg)
            if current_len + seg_len > max_chars and current_parts:
                groups.append(tail + " ".join(current_parts))
                # Keep last overlap_chars as tail for next group
                tail          = (" ".join(current_parts))[-overlap_chars:] + " " if overlap_chars else ""
                current_parts = []
                current_len   = 0
            current_parts.append(seg)
            current_len += seg_len

        if current_parts:
            groups.append(tail + " ".join(current_parts))

        return [g.strip() for g in groups if g.strip()]
