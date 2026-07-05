from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from .enums import ChunkType, RiskLevel
from .metadata import MedicalEntity


class ChunkMetadata(BaseModel):
    """
    Every chunk carries this metadata payload.
    It is stored verbatim in Qdrant as the point payload so the retriever
    can filter by org, role, risk level, etc. without an extra DB round-trip.
    """

    # Identity & tenancy
    chunk_id:          str
    document_id:       str
    organization_id:   str
    department_id:     str
    knowledge_base_id: str
    document_version:  str

    # Access control
    roles: list[str] = []

    # Content classification
    specialty:        str
    source:           str
    document_type:    str = ""
    approval_status:  str = "approved"
    risk_level:       RiskLevel = RiskLevel.LOW

    # Medical entities (subset of doc-level entities relevant to this chunk)
    entities: list[MedicalEntity] = []

    # Hierarchy (Document → Section → Subsection → Chunk)
    section:         str           = ""
    subsection:      str           = ""
    parent_chunk_id: Optional[str] = None

    # Position
    chunk_index:  int           = 0
    page_number:  Optional[int] = None

    def entity_codes_for(self, standard: str) -> list[str]:
        """Return all ontology codes of a given standard present in this chunk."""
        codes = []
        for entity in self.entities:
            for mapping in entity.ontology_mappings:
                if mapping.standard.value == standard:
                    codes.append(mapping.code)
        return codes


class Chunk(BaseModel):
    """
    A single retrievable unit of knowledge.
    Created by the ChunkingEngine and populated with embeddings later.
    Persisted to both Supabase (metadata row) and Qdrant (vector + payload).
    """

    chunk_id:        str      = Field(default_factory=lambda: str(uuid4()))
    document_id:     str
    content:         str
    chunk_type:      ChunkType
    metadata:        ChunkMetadata
    created_at:      datetime = Field(default_factory=datetime.utcnow)
    embedding:       Optional[list[float]] = None
    embedding_model: str = ""

    @field_validator("content")
    @classmethod
    def content_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("chunk content must not be empty")
        return v

    @property
    def token_count(self) -> int:
        """Rough token estimate (1 token ≈ 4 characters)."""
        return len(self.content) // 4

    @property
    def is_embedded(self) -> bool:
        return self.embedding is not None

    @property
    def is_high_risk(self) -> bool:
        return self.metadata.risk_level == RiskLevel.HIGH

    def to_qdrant_payload(self) -> dict:
        """
        Returns a flat dict for Qdrant point payload.
        Only scalar / list-of-scalar fields — no nested objects.
        """
        entity_texts = [e.text for e in self.metadata.entities]
        icd10_codes  = self.metadata.entity_codes_for("icd_10")
        rxnorm_codes = self.metadata.entity_codes_for("rxnorm")

        return {
            "chunk_id":          self.chunk_id,
            "document_id":       self.document_id,
            "organization_id":   self.metadata.organization_id,
            "department_id":     self.metadata.department_id,
            "knowledge_base_id": self.metadata.knowledge_base_id,
            "document_version":  self.metadata.document_version,
            "roles":             self.metadata.roles,
            "specialty":         self.metadata.specialty,
            "source":            self.metadata.source,
            "document_type":     self.metadata.document_type,
            "approval_status":   self.metadata.approval_status,
            "risk_level":        self.metadata.risk_level.value,
            "section":           self.metadata.section,
            "subsection":        self.metadata.subsection,
            "chunk_index":       self.metadata.chunk_index,
            "page_number":       self.metadata.page_number,
            "chunk_type":        self.chunk_type.value,
            "token_count":       self.token_count,
            "entities":          entity_texts,
            "icd10_codes":       icd10_codes,
            "rxnorm_codes":      rxnorm_codes,
            "content_preview":   self.content[:200],
        }


class QualityScores(BaseModel):
    """
    Quality scores computed by the ValidationPipeline for a single document.
    The index_readiness_score gates whether the document proceeds to indexing.
    """

    document_id:         str
    parse_score:         float = Field(default=0.0, ge=0.0, le=1.0)
    ocr_score:           float = Field(default=1.0, ge=0.0, le=1.0)
    metadata_score:      float = Field(default=0.0, ge=0.0, le=1.0)
    chunk_quality_score: float = Field(default=0.0, ge=0.0, le=1.0)

    # Weighted combination used to decide indexing readiness
    # Weights: parse=0.25, ocr=0.15, metadata=0.30, chunk=0.30
    @property
    def index_readiness_score(self) -> float:
        return (
            self.parse_score         * 0.25
            + self.ocr_score         * 0.15
            + self.metadata_score    * 0.30
            + self.chunk_quality_score * 0.30
        )

    def is_ready_for_index(self, threshold: float = 0.85) -> bool:
        return self.index_readiness_score >= threshold

    def summary(self) -> dict:
        return {
            "document_id":           self.document_id,
            "parse_score":           self.parse_score,
            "ocr_score":             self.ocr_score,
            "metadata_score":        self.metadata_score,
            "chunk_quality_score":   self.chunk_quality_score,
            "index_readiness_score": round(self.index_readiness_score, 4),
        }
