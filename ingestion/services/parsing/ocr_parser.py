from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from ingestion.exceptions import OCRError, ParseError
from ingestion.models import FileType, HeadingElement, ParsedContent, ParserType

from .base_parser import BaseParser

if TYPE_CHECKING:
    import numpy as np
    from paddleocr import PaddleOCR

logger = logging.getLogger(__name__)

# Render scale for PDF pages — 2× gives ~150 DPI which PaddleOCR reads well
_PDF_RENDER_SCALE = 2.0


class OCRParser(BaseParser):
    """
    OCR-based parser using PaddleOCR.

    Used for  : scanned PDFs, PNG/JPG/TIFF images, medical forms
    Strategy  :
        PDF  → render each page via PyMuPDF (fitz) at 2× scale → OCR per page
        Image → open with PIL → OCR
    Skips lines below confidence_threshold (noisy OCR output filtered out).
    Heading detection: ALL-CAPS lines or lines shorter than 80 chars at the
    top of a page are promoted to HeadingElement.
    """

    _ocr_engine: Optional["PaddleOCR"] = None   # class-level lazy singleton

    def __init__(
        self,
        lang:                 str   = "en",
        confidence_threshold: float = 0.70,
    ) -> None:
        self._lang                 = lang
        self._confidence_threshold = confidence_threshold

    @property
    def parser_type(self) -> ParserType:
        return ParserType.PADDLE_OCR

    # ── Singleton OCR engine ──────────────────────────────────────────────────

    @classmethod
    def _get_ocr(cls, lang: str) -> "PaddleOCR":
        if cls._ocr_engine is None:
            try:
                from paddleocr import PaddleOCR
            except ImportError as exc:
                raise ParseError(
                    "PaddleOCR is not installed: pip install paddleocr paddlepaddle"
                ) from exc
            cls._ocr_engine = PaddleOCR(
                use_angle_cls=True,
                lang=lang,
                show_log=False,
                use_gpu=False,          # GPU flag toggled at Celery-worker level
            )
        return cls._ocr_engine

    # ── Core extraction ───────────────────────────────────────────────────────

    def _extract(self, file_bytes: bytes, filename: str) -> ParsedContent:
        ext       = Path(filename).suffix.lower().lstrip(".")
        file_type = FileType.from_extension(ext)

        if file_type == FileType.PDF:
            return self._extract_pdf(file_bytes)
        elif file_type in {FileType.PNG, FileType.JPG, FileType.JPEG, FileType.TIFF}:
            return self._extract_image(file_bytes)
        else:
            raise ParseError(
                f"OCRParser does not handle '{ext}' — use DoclingParser instead"
            )

    # ── PDF branch ────────────────────────────────────────────────────────────

    def _extract_pdf(self, file_bytes: bytes) -> ParsedContent:
        try:
            import fitz                         # PyMuPDF
        except ImportError as exc:
            raise ParseError(
                "PyMuPDF required for PDF OCR: pip install pymupdf"
            ) from exc

        pdf        = fitz.open(stream=file_bytes, filetype="pdf")
        page_count = len(pdf)
        matrix     = fitz.Matrix(_PDF_RENDER_SCALE, _PDF_RENDER_SCALE)

        page_texts:  list[str]           = []
        all_headings: list[HeadingElement] = []
        confidences: list[float]         = []

        for page_idx in range(page_count):
            page   = pdf[page_idx]
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            arr    = self._pixmap_to_array(pixmap)

            lines, headings, conf = self._run_ocr_on_array(arr, page_number=page_idx + 1)
            if lines:
                page_texts.append("\n".join(lines))
                confidences.append(conf)
            all_headings.extend(headings)

        avg_confidence = (sum(confidences) / len(confidences)) if confidences else 0.0

        return ParsedContent(
            text           = "\n\n".join(page_texts),
            headings       = all_headings,
            is_scanned     = True,
            ocr_confidence = round(avg_confidence, 4),
            page_count     = page_count,
        )

    # ── Image branch ──────────────────────────────────────────────────────────

    def _extract_image(self, file_bytes: bytes) -> ParsedContent:
        try:
            from PIL import Image
            import numpy as np
            img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
            arr = np.array(img)
        except ImportError as exc:
            raise ParseError("Pillow required: pip install Pillow") from exc
        except Exception as exc:
            raise ParseError(f"Cannot open image: {exc}") from exc

        lines, headings, confidence = self._run_ocr_on_array(arr, page_number=1)

        return ParsedContent(
            text           = "\n".join(lines),
            headings       = headings,
            is_scanned     = True,
            ocr_confidence = round(confidence, 4),
            page_count     = 1,
        )

    # ── OCR execution ─────────────────────────────────────────────────────────

    def _run_ocr_on_array(
        self, image_array: "np.ndarray", page_number: int
    ) -> tuple[list[str], list[HeadingElement], float]:
        """
        Run PaddleOCR on a numpy HWC RGB array.
        Returns (accepted_lines, detected_headings, avg_confidence).
        """
        ocr = self._get_ocr(self._lang)
        try:
            result = ocr.ocr(image_array, cls=True)
        except Exception as exc:
            logger.warning("OCR failed on page %d: %s — skipping page", page_number, exc)
            return [], [], 0.0

        if not result or result[0] is None:
            return [], [], 0.0

        lines:    list[str]           = []
        headings: list[HeadingElement] = []
        scores:   list[float]         = []

        for item in result[0]:
            text, conf = item[1]
            if conf < self._confidence_threshold:
                continue                         # discard low-confidence noise
            lines.append(text)
            scores.append(conf)

            # Heuristic heading detection: short ALL-CAPS or title-case lines
            stripped = text.strip()
            if stripped and (stripped.isupper() or stripped.istitle()) and len(stripped) < 80:
                headings.append(
                    HeadingElement(text=stripped, level=2, page_number=page_number)
                )

        avg_conf = sum(scores) / len(scores) if scores else 0.0
        return lines, headings, avg_conf

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def _pixmap_to_array(pixmap: "fitz.Pixmap") -> "np.ndarray":
        """Convert a PyMuPDF Pixmap to a numpy HWC array (RGB, uint8)."""
        import numpy as np
        samples = np.frombuffer(pixmap.samples, dtype=np.uint8)
        return samples.reshape(pixmap.height, pixmap.width, pixmap.n)
