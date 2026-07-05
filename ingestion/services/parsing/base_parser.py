from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

from ingestion.exceptions import ParseError
from ingestion.models import ParsedContent, ParsedDocument, ParserType

logger = logging.getLogger(__name__)


class BaseParser(ABC):
    """
    Abstract base for all document parsers.

    Uses the Template Method pattern:
        parse()    → public entry point (timing, logging, scoring, error wrapping)
        _extract() → implemented by each concrete parser
    """

    # ── Interface ─────────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def parser_type(self) -> ParserType:
        """Which tool this parser uses (shown in logs and ParsedDocument records)."""

    @abstractmethod
    def _extract(self, file_bytes: bytes, filename: str) -> ParsedContent:
        """
        Extract structured content from raw file bytes.
        Raises ParseError (or any Exception — wrapped by parse()) on failure.
        """

    # ── Template method ───────────────────────────────────────────────────────

    def parse(
        self,
        file_bytes:  bytes,
        filename:    str,
        document_id: str,
    ) -> tuple[ParsedContent, ParsedDocument]:
        """
        Parse a document and return (ParsedContent, ParsedDocument summary).
        ParsedContent travels in-memory through the pipeline.
        ParsedDocument is persisted to Supabase as a lightweight record.
        """
        logger.info(
            "Parse start | doc=%s parser=%s file=%s size=%d B",
            document_id, self.parser_type.value, filename, len(file_bytes),
        )
        t0 = time.monotonic()

        try:
            content = self._extract(file_bytes, filename)
        except ParseError:
            raise
        except Exception as exc:
            raise ParseError(
                f"[{self.parser_type.value}] '{filename}' failed: {exc}"
            ) from exc

        elapsed_ms  = int((time.monotonic() - t0) * 1_000)
        parse_score = self._compute_parse_score(content)

        logger.info(
            "Parse done  | doc=%s parser=%s elapsed=%dms score=%.3f "
            "text=%d chars tables=%d figures=%d pages=%d",
            document_id, self.parser_type.value, elapsed_ms, parse_score,
            len(content.text), content.table_count, content.figure_count, content.page_count,
        )

        parsed_doc = ParsedDocument.from_content(
            document_id=document_id,
            parser_used=self.parser_type,
            content=content,
            parse_score=parse_score,
        )
        return content, parsed_doc

    # ── Parse quality score ───────────────────────────────────────────────────

    def _compute_parse_score(self, content: ParsedContent) -> float:
        """
        Heuristic quality score in [0.0, 1.0].

        Component weights:
            text richness     0.40  (caps at 2000 chars for full weight)
            heading structure 0.20  (≥3 headings = full weight)
            table presence    0.10  (any table = full weight)
            OCR confidence    0.30  (non-scanned docs always get 0.30)
        """
        text_score    = min(len(content.text) / 2_000, 1.0) * 0.40
        heading_score = min(len(content.headings) / 3, 1.0) * 0.20
        table_score   = 0.10 if content.tables else 0.0
        ocr_score     = (content.ocr_confidence if content.is_scanned else 1.0) * 0.30

        return round(text_score + heading_score + table_score + ocr_score, 4)
