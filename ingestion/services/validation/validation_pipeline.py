from __future__ import annotations

import logging
from typing import Optional

from ingestion.models import Chunk, DocumentMetadata, ParsedContent, QualityScores

from .chunk_validator import ChunkValidator
from .metadata_validator import MetadataValidator
from .parse_validator import ParseValidator

logger = logging.getLogger(__name__)

# Gate: documents below this score are held back from indexing
_INDEX_READINESS_THRESHOLD = 0.85


class ValidationPipeline:
    """
    Aggregates parse, metadata, and chunk quality into a single QualityScores record.

    Weighted formula (matches QualityScores.index_readiness_score):
        parse_score          × 0.25
        ocr_score            × 0.15   (taken directly from ParsedContent.ocr_confidence)
        metadata_score       × 0.30
        chunk_quality_score  × 0.30
                             ──────
                               1.00

    Usage:
        pipeline = ValidationPipeline()
        scores   = pipeline.validate(content, doc_metadata, chunks, document_id)
        if scores.is_ready_for_index():
            ...proceed to indexing...
    """

    def __init__(
        self,
        parse_validator:    Optional[ParseValidator]    = None,
        metadata_validator: Optional[MetadataValidator] = None,
        chunk_validator:    Optional[ChunkValidator]    = None,
    ) -> None:
        self._parse    = parse_validator    or ParseValidator()
        self._metadata = metadata_validator or MetadataValidator()
        self._chunk    = chunk_validator    or ChunkValidator()

    def validate(
        self,
        content:      ParsedContent,
        doc_metadata: DocumentMetadata,
        chunks:       list[Chunk],
        document_id:  str,
    ) -> QualityScores:
        """
        Run all three validators and return a populated QualityScores object.
        Each sub-score is logged so failures are easy to diagnose.
        """
        parse_score         = self._parse.validate(content)
        ocr_score           = round(content.ocr_confidence, 4)
        metadata_score      = self._metadata.validate(doc_metadata)
        chunk_quality_score = self._chunk.validate(chunks)

        scores = QualityScores(
            document_id         = document_id,
            parse_score         = parse_score,
            ocr_score           = ocr_score,
            metadata_score      = metadata_score,
            chunk_quality_score = chunk_quality_score,
        )

        ready = scores.is_ready_for_index(_INDEX_READINESS_THRESHOLD)
        logger.info(
            "ValidationPipeline | doc=%s parse=%.3f ocr=%.3f meta=%.3f chunk=%.3f "
            "readiness=%.3f ready=%s",
            document_id,
            parse_score, ocr_score, metadata_score, chunk_quality_score,
            scores.index_readiness_score, ready,
        )
        return scores
