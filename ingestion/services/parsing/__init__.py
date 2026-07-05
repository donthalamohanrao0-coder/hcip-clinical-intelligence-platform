from ingestion.models import FileType

from .base_parser import BaseParser
from .docling_parser import DoclingParser
from .multimodal_parser import MultimodalParser
from .ocr_parser import OCRParser

__all__ = [
    "BaseParser",
    "DoclingParser",
    "OCRParser",
    "MultimodalParser",
    "get_parser",
]


# ── Parser factory ────────────────────────────────────────────────────────────

def get_parser(file_type: FileType, is_scanned: bool = False) -> BaseParser:
    """
    Select the correct primary parser for a given file type.

    Rules (matching the spec):
        Images               → OCRParser   (always — no text layer)
        Scanned PDFs         → OCRParser   (detected by UploadService / caller)
        PDF / DOCX / PPTX
          / XLSX / TXT / CSV → DoclingParser
        Structured data      → DoclingParser (handles JSON/XML/FHIR as text)

    MultimodalParser is not returned here — it supplements an existing
    ParsedContent and is called explicitly by the pipeline after Docling.
    """
    if file_type.is_image or is_scanned:
        return OCRParser()
    return DoclingParser()
