from __future__ import annotations

import logging

from ingestion.models import ParsedContent

logger = logging.getLogger(__name__)

# Thresholds for full-score awards
_FULL_SCORE_TEXT_CHARS = 4_000    # docs with ≥ 4000 chars earn max text score
_FULL_SCORE_HEADINGS   = 3        # docs with ≥ 3 headings earn max structure score


class ParseValidator:
    """
    Scores the quality of a parsing result.

    Returns a float in [0.0, 1.0].

    Scoring model:
        Non-scanned documents
            text richness   60%  — chars / 4000, capped at 1.0
            heading structure 30%  — headings / 3, capped at 1.0
            table presence  10%  — flat bonus when ≥ 1 table extracted
        Scanned documents
            OCR confidence  70%  — from PaddleOCR confidence scores
            text richness   30%  — still checks extracted text length
    """

    def validate(self, content: ParsedContent) -> float:
        if not content.text.strip():
            logger.warning("ParseValidator: empty text — score=0.0")
            return 0.0

        text_score    = min(len(content.text) / _FULL_SCORE_TEXT_CHARS, 1.0)
        heading_score = min(len(content.headings) / _FULL_SCORE_HEADINGS, 1.0)
        table_bonus   = 0.10 if content.tables else 0.0

        if content.is_scanned:
            score = content.ocr_confidence * 0.70 + text_score * 0.30
        else:
            score = text_score * 0.60 + heading_score * 0.30 + table_bonus

        score = min(score, 1.0)
        logger.debug(
            "ParseValidator | scanned=%s text_score=%.2f heading_score=%.2f score=%.3f",
            content.is_scanned, text_score, heading_score, score,
        )
        return round(score, 4)
