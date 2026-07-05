from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from .enums import DocumentType, FileType, GovernanceState, ParserType, ProcessingStatus
from .metadata import DocumentMetadata


# ── Parsed element sub-models ─────────────────────────────────────────────────
# These travel between Celery workers so they must be Pydantic-serializable.

class HeadingElement(BaseModel):
    """A heading extracted from a document with its hierarchy level."""

    text:        str
    level:       int = Field(ge=1, le=6)    # H1–H6
    page_number: int = 0


class TableElement(BaseModel):
    """A structured table extracted from a document."""

    headers:     list[str]
    rows:        list[list[str]]
    caption:     str = ""
    page_number: int = 0

    def to_text(self) -> str:
        """Serialise the table as pipe-delimited text for embedding."""
        header_row = " | ".join(self.headers)
        data_rows  = "\n".join(" | ".join(cell for cell in row) for row in self.rows)
        parts = [p for p in [self.caption, header_row, data_rows] if p]
        return "\n".join(parts)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        return len(self.headers)


class FigureElement(BaseModel):
    """An image or chart extracted from a document."""

    caption:     str = ""
    s3_key:      str = ""           # set after the image is uploaded to S3
    page_number: int = 0
    has_chart:   bool = False       # triggers ColQwen multimodal processing
    has_form:    bool = False


class ParsedContent(BaseModel):
    """
    Full structured output from the parsing stage.
    Produced by one of the three parsers (Docling / PaddleOCR / ColQwen)
    and consumed by the ChunkingEngine.
    """

    text:           str
    headings:       list[HeadingElement] = []
    tables:         list[TableElement]   = []
    figures:        list[FigureElement]  = []
    citations:      list[str]            = []
    footnotes:      list[str]            = []
    is_scanned:     bool  = False
    ocr_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    language:       str   = "en"
    page_count:     int   = 0

    @field_validator("text")
    @classmethod
    def text_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("parsed content must contain text")
        return v

    @property
    def needs_multimodal(self) -> bool:
        """True when ColQwen processing should be triggered."""
        return any(f.has_chart or f.has_form for f in self.figures)

    @property
    def table_count(self) -> int:
        return len(self.tables)

    @property
    def figure_count(self) -> int:
        return len(self.figures)


# ── Core domain models ────────────────────────────────────────────────────────

class Document(BaseModel):
    """
    The primary document record.  Created at upload time and updated as it
    moves through the pipeline.  Persisted to Supabase.
    """

    document_id:        str          = Field(default_factory=lambda: str(uuid4()))
    organization_id:    str
    department_id:      str
    knowledge_base_id:  str
    file_name:          str
    file_type:          FileType
    s3_key:             str
    file_size_bytes:    int          = Field(ge=0)
    uploaded_by:        str
    created_at:         datetime     = Field(default_factory=datetime.utcnow)
    updated_at:         datetime     = Field(default_factory=datetime.utcnow)
    document_type:      Optional[DocumentType]     = None
    governance_state:   GovernanceState            = GovernanceState.DRAFT
    processing_status:  ProcessingStatus           = ProcessingStatus.PENDING
    metadata:           Optional[DocumentMetadata] = None
    version_number:     int          = Field(default=1, ge=1)
    parent_document_id: Optional[str] = None       # populated for re-uploads

    @field_validator("file_name")
    @classmethod
    def file_name_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("file_name must not be empty")
        return v.strip()

    def transition_to(self, new_status: ProcessingStatus) -> None:
        """Update processing status and refresh updated_at timestamp."""
        self.processing_status = new_status
        self.updated_at = datetime.utcnow()

    def request_review(self) -> None:
        """Move governance state from DRAFT → PENDING_REVIEW."""
        if not self.governance_state.can_transition_to(GovernanceState.PENDING_REVIEW):
            raise ValueError(
                f"Cannot move from {self.governance_state} to PENDING_REVIEW"
            )
        self.governance_state = GovernanceState.PENDING_REVIEW
        self.updated_at = datetime.utcnow()

    @property
    def is_searchable(self) -> bool:
        """Only APPROVED documents may be retrieved."""
        return self.governance_state == GovernanceState.APPROVED

    @property
    def is_versioned(self) -> bool:
        return self.parent_document_id is not None


class DocumentVersion(BaseModel):
    """
    Immutable record of each document version.
    Versions are never overwritten — only new records are added.
    """

    version_id:      str      = Field(default_factory=lambda: str(uuid4()))
    document_id:     str
    version_number:  int      = Field(ge=1)
    s3_key:          str
    is_active:       bool     = True
    created_at:      datetime = Field(default_factory=datetime.utcnow)
    created_by:      str
    change_summary:  str      = ""

    @model_validator(mode="after")
    def s3_key_must_not_be_empty(self) -> "DocumentVersion":
        if not self.s3_key.strip():
            raise ValueError("s3_key must not be empty")
        return self


class ParsedDocument(BaseModel):
    """
    Summary record of what the parser produced.
    The full ParsedContent is passed in-memory between pipeline stages
    (not persisted) to avoid large Supabase rows.
    """

    document_id:    str
    parser_used:    ParserType
    parse_score:    float    = Field(ge=0.0, le=1.0)
    parsed_at:      datetime = Field(default_factory=datetime.utcnow)
    text_length:    int      = Field(ge=0)
    table_count:    int      = Field(ge=0)
    figure_count:   int      = Field(ge=0)
    heading_count:  int      = Field(ge=0)
    is_scanned:     bool     = False
    ocr_confidence: float    = Field(default=1.0, ge=0.0, le=1.0)
    page_count:     int      = Field(ge=0)

    @classmethod
    def from_content(
        cls,
        document_id: str,
        parser_used: ParserType,
        content: ParsedContent,
        parse_score: float,
    ) -> "ParsedDocument":
        """Factory that builds the summary record from a ParsedContent object."""
        return cls(
            document_id   = document_id,
            parser_used   = parser_used,
            parse_score   = parse_score,
            text_length   = len(content.text),
            table_count   = content.table_count,
            figure_count  = content.figure_count,
            heading_count = len(content.headings),
            is_scanned    = content.is_scanned,
            ocr_confidence = content.ocr_confidence,
            page_count    = content.page_count,
        )
