from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from ingestion.exceptions import ParseError
from ingestion.models import FigureElement, ParsedContent, ParserType
from ingestion.storage import S3Storage

from .base_parser import BaseParser

logger = logging.getLogger(__name__)

# Caption keywords that flag a figure as a chart / clinical diagram
_CHART_KEYWORDS: frozenset[str] = frozenset({
    "chart", "graph", "figure", "fig.", "plot", "diagram", "curve",
    "histogram", "scatter", "bar chart", "pie chart", "heat map", "heatmap",
    "kaplan-meier", "forest plot", "roc curve", "survival curve",
    "bland-altman", "receiver operating", "funnel plot",
})

# Caption keywords that flag a figure as a medical form / structured layout
_FORM_KEYWORDS: frozenset[str] = frozenset({
    "form", "checklist", "questionnaire", "checkbox",
    "intake", "consent", "assessment", "scale", "score sheet",
})


class MultimodalParser(BaseParser):
    """
    Supplementary processor for visual elements (charts, forms, complex figures).

    Role in the pipeline
    ────────────────────
    This parser does NOT replace DoclingParser. It runs AFTER Docling and:
        1. Classifies each FigureElement (has_chart / has_form)
        2. Extracts figure images from the source PDF via PyMuPDF
        3. Uploads figure images to S3 so EmbeddingPipeline can embed them
           with ColQwen (image collection in Qdrant, Phase 8)

    Embedding is intentionally NOT done here — this keeps parsing and
    embedding concerns separate (cost-optimisation principle: avoid GPU
    usage during the CPU-bound parsing stage).

    Trigger conditions (any one is sufficient)
    ──────────────────────────────────────────
    • ParsedContent.needs_multimodal is True   (chart/form flags already set)
    • Document type is MEDICAL_IMAGE
    • Caller explicitly requests it
    """

    def __init__(self, s3: Optional[S3Storage] = None) -> None:
        self._s3 = s3

    @property
    def parser_type(self) -> ParserType:
        return ParserType.COL_QWEN

    def _extract(self, file_bytes: bytes, filename: str) -> ParsedContent:
        raise ParseError(
            "MultimodalParser is not called via parse(). "
            "Use process_figures(content, file_bytes, ...) instead."
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def process_figures(
        self,
        content:     ParsedContent,
        file_bytes:  bytes,
        filename:    str,
        document_id: str,
        org_id:      str,
    ) -> ParsedContent:
        """
        Classify figures, extract images, and upload to S3.
        Mutates the FigureElement list inside `content` and returns it.

        Call this after DoclingParser.parse() when content.needs_multimodal is True.
        """
        if not content.figures:
            return content

        suffix = Path(filename).suffix.lower().lstrip(".")
        extracted_images = (
            self._extract_pdf_images(file_bytes)
            if suffix == "pdf"
            else {}
        )

        updated: list[FigureElement] = []
        for idx, figure in enumerate(content.figures):
            classified = self._classify_figure(figure)
            stored     = self._store_figure(
                classified,
                image_bytes=extracted_images.get(idx),
                document_id=document_id,
                org_id=org_id,
                figure_index=idx,
            )
            updated.append(stored)

        content.figures = updated
        multimodal_count = sum(1 for f in updated if f.has_chart or f.has_form)
        logger.info(
            "MultimodalParser | doc=%s figures=%d flagged_for_colqwen=%d",
            document_id, len(updated), multimodal_count,
        )
        return content

    # ── Classification ────────────────────────────────────────────────────────

    @staticmethod
    def _classify_figure(figure: FigureElement) -> FigureElement:
        """
        Update has_chart and has_form flags based on caption text.
        Returns a new FigureElement (immutable update).
        """
        cap = figure.caption.lower()
        return FigureElement(
            caption     = figure.caption,
            s3_key      = figure.s3_key,
            page_number = figure.page_number,
            has_chart   = figure.has_chart or any(kw in cap for kw in _CHART_KEYWORDS),
            has_form    = figure.has_form  or any(kw in cap for kw in _FORM_KEYWORDS),
        )

    # ── Storage ───────────────────────────────────────────────────────────────

    def _store_figure(
        self,
        figure:       FigureElement,
        image_bytes:  Optional[bytes],
        document_id:  str,
        org_id:       str,
        figure_index: int,
    ) -> FigureElement:
        """
        Upload figure image to S3 if it needs ColQwen processing and we have
        both image bytes and an S3 client available.
        """
        needs_embedding = figure.has_chart or figure.has_form
        if not (needs_embedding and image_bytes and self._s3):
            return figure

        s3_key = f"parsed/{org_id}/{document_id}/figures/figure_{figure_index:04d}.png"
        try:
            self._s3.upload_bytes(image_bytes, s3_key, content_type="image/png")
            return FigureElement(
                caption     = figure.caption,
                s3_key      = s3_key,
                page_number = figure.page_number,
                has_chart   = figure.has_chart,
                has_form    = figure.has_form,
            )
        except Exception as exc:
            logger.warning(
                "Figure %d upload failed for doc=%s: %s — continuing without S3 key",
                figure_index, document_id, exc,
            )
            return figure

    # ── Image extraction ──────────────────────────────────────────────────────

    @staticmethod
    def _extract_pdf_images(file_bytes: bytes) -> dict[int, bytes]:
        """
        Extract embedded images from a PDF page-by-page using PyMuPDF.
        Returns {figure_index: png_bytes}.  Order matches document reading order.
        """
        try:
            import fitz
        except ImportError:
            logger.warning(
                "PyMuPDF not installed — PDF figure extraction skipped. "
                "pip install pymupdf"
            )
            return {}

        figure_images: dict[int, bytes] = {}
        figure_idx = 0

        try:
            pdf = fitz.open(stream=file_bytes, filetype="pdf")
            for page in pdf:
                for img_info in page.get_images(full=True):
                    xref = img_info[0]
                    try:
                        base_image = pdf.extract_image(xref)
                        img_bytes  = base_image.get("image")
                        if img_bytes:
                            # Convert to PNG for uniform downstream handling
                            png_bytes = _to_png(img_bytes, base_image.get("ext", ""))
                            figure_images[figure_idx] = png_bytes
                            figure_idx += 1
                    except Exception as exc:
                        logger.debug("Skipping image xref=%d: %s", xref, exc)
        except Exception as exc:
            logger.warning("PDF image extraction failed: %s", exc)

        return figure_images


# ── Module-level helper ───────────────────────────────────────────────────────

def _to_png(image_bytes: bytes, ext: str) -> bytes:
    """Convert image bytes to PNG. Returns original bytes if conversion fails."""
    if ext.lower() == "png":
        return image_bytes
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return image_bytes   # return original on failure — still usable
