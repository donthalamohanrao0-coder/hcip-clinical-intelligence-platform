from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from ingestion.exceptions import ParseError
from ingestion.models import (
    FigureElement,
    HeadingElement,
    ParsedContent,
    ParserType,
    TableElement,
)

from .base_parser import BaseParser

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter

logger = logging.getLogger(__name__)


class DoclingParser(BaseParser):
    """
    Primary parser for digital documents using IBM Docling.

    Handles  : PDF (text-layer), DOCX, PPTX, XLSX
    Extracts : full text, headings (H1-H2), tables with structure,
               figures with chart detection, citations, footnotes, page count.

    The DocumentConverter is created once (class-level singleton) because
    Docling loads ML pipeline components on first construction.
    """

    _converter: Optional["DocumentConverter"] = None  # lazy class-level singleton

    @property
    def parser_type(self) -> ParserType:
        return ParserType.DOCLING

    # ── Singleton converter ───────────────────────────────────────────────────

    @classmethod
    def _get_converter(cls) -> "DocumentConverter":
        if cls._converter is None:
            from docling.document_converter import DocumentConverter, PdfFormatOption
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions

            pipeline_opts = PdfPipelineOptions()
            pipeline_opts.do_ocr             = False   # OCRParser handles scanned docs
            pipeline_opts.do_table_structure = True    # structured table extraction

            cls._converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts),
                }
            )
        return cls._converter

    # ── Core extraction ───────────────────────────────────────────────────────

    def _extract(self, file_bytes: bytes, filename: str) -> ParsedContent:
        suffix = Path(filename).suffix.lower()

        # Docling requires a file path — write to a temp file
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = Path(tmp.name)

        try:
            return self._run_conversion(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _run_conversion(self, path: Path) -> ParsedContent:
        converter = self._get_converter()
        try:
            result = converter.convert(str(path))
        except Exception as exc:
            raise ParseError(f"Docling conversion failed: {exc}") from exc

        doc = result.document
        return ParsedContent(
            text       = self._get_text(doc),
            headings   = self._get_headings(doc),
            tables     = self._get_tables(doc),
            figures    = self._get_figures(doc),
            citations  = self._get_labeled_texts(doc, "REFERENCE"),
            footnotes  = self._get_labeled_texts(doc, "FOOTNOTE"),
            is_scanned = False,
            ocr_confidence = 1.0,
            page_count = self._get_page_count(result),
        )

    # ── Extraction helpers (each isolated so failures don't cascade) ──────────

    @staticmethod
    def _get_text(doc) -> str:
        try:
            return doc.export_to_markdown() or ""
        except Exception:
            try:
                return doc.export_to_text() or ""
            except Exception:
                return ""

    @staticmethod
    def _get_headings(doc) -> list[HeadingElement]:
        headings: list[HeadingElement] = []
        try:
            from docling.datamodel.base_models import DocItemLabel
            heading_labels = {DocItemLabel.TITLE: 1, DocItemLabel.SECTION_HEADER: 2}

            for item in doc.texts:
                label = getattr(item, "label", None)
                if label not in heading_labels:
                    continue
                text = getattr(item, "text", "").strip()
                if not text:
                    continue
                page = 0
                if getattr(item, "prov", None):
                    page = getattr(item.prov[0], "page_no", 0)
                headings.append(HeadingElement(
                    text=text, level=heading_labels[label], page_number=page
                ))
        except Exception as exc:
            logger.warning("Heading extraction skipped: %s", exc)
        return headings

    @staticmethod
    def _get_tables(doc) -> list[TableElement]:
        tables: list[TableElement] = []
        try:
            for table_item in doc.tables:
                headers: list[str]       = []
                rows:    list[list[str]] = []
                try:
                    df      = table_item.export_to_dataframe()
                    headers = [str(c) for c in df.columns.tolist()]
                    rows    = [[str(cell) for cell in row] for row in df.values.tolist()]
                except Exception:
                    pass  # malformed table — skip silently

                if not headers and not rows:
                    continue

                caption = ""
                try:
                    caption = table_item.caption_text(doc) or ""
                except Exception:
                    pass

                page = 0
                if getattr(table_item, "prov", None):
                    page = getattr(table_item.prov[0], "page_no", 0)

                tables.append(TableElement(
                    headers=headers, rows=rows, caption=caption, page_number=page
                ))
        except Exception as exc:
            logger.warning("Table extraction skipped: %s", exc)
        return tables

    @staticmethod
    def _get_figures(doc) -> list[FigureElement]:
        figures: list[FigureElement] = []
        # Keywords that indicate a figure contains a chart or diagram
        chart_kw = frozenset({
            "chart", "graph", "figure", "fig.", "plot", "diagram",
            "curve", "histogram", "scatter", "forest plot",
            "kaplan-meier", "roc curve", "survival curve",
        })
        try:
            for picture in doc.pictures:
                caption = ""
                try:
                    caption = picture.caption_text(doc) or ""
                except Exception:
                    pass

                page = 0
                if getattr(picture, "prov", None):
                    page = getattr(picture.prov[0], "page_no", 0)

                cap_lower = caption.lower()
                has_chart = any(kw in cap_lower for kw in chart_kw)

                figures.append(FigureElement(
                    caption=caption, page_number=page, has_chart=has_chart
                ))
        except Exception as exc:
            logger.warning("Figure extraction skipped: %s", exc)
        return figures

    @staticmethod
    def _get_labeled_texts(doc, label_name: str) -> list[str]:
        results: list[str] = []
        try:
            from docling.datamodel.base_models import DocItemLabel
            target_label = getattr(DocItemLabel, label_name, None)
            if target_label is None:
                return results
            for item in doc.texts:
                if getattr(item, "label", None) == target_label:
                    text = getattr(item, "text", "").strip()
                    if text:
                        results.append(text)
        except Exception:
            pass
        return results

    @staticmethod
    def _get_page_count(result) -> int:
        try:
            return len(result.document.pages)
        except Exception:
            return 0
