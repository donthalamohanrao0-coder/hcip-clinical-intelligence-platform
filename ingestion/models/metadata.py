from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from .enums import MedicalEntityType, MedicalSpecialty, OntologyStandard, RiskLevel


class OntologyMapping(BaseModel):
    """A single ontology code mapping for a medical entity."""

    standard: OntologyStandard
    code: str
    display_name: str
    confidence: float = Field(ge=0.0, le=1.0)


class MedicalEntity(BaseModel):
    """
    A named medical concept extracted from document text.
    Carries its raw form, normalized form, type, and ontology codes.
    """

    text: str
    normalized_text: str
    entity_type: MedicalEntityType
    ontology_mappings: list[OntologyMapping] = []
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("text", "normalized_text")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("entity text must not be empty")
        return v.strip()

    def primary_code(self, standard: OntologyStandard) -> Optional[str]:
        """Return the highest-confidence code for a given ontology standard."""
        matches = [m for m in self.ontology_mappings if m.standard == standard]
        if not matches:
            return None
        return max(matches, key=lambda m: m.confidence).code


class MedicalMetadata(BaseModel):
    """All medical entities and risk classification extracted from a document."""

    diseases:   list[MedicalEntity] = []
    drugs:      list[MedicalEntity] = []
    procedures: list[MedicalEntity] = []
    symptoms:   list[MedicalEntity] = []
    treatments: list[MedicalEntity] = []
    guidelines: list[MedicalEntity] = []
    risk_level: RiskLevel = RiskLevel.LOW
    specialty:  MedicalSpecialty = MedicalSpecialty.GENERAL

    @property
    def all_entities(self) -> list[MedicalEntity]:
        return (
            self.diseases + self.drugs + self.procedures
            + self.symptoms + self.treatments + self.guidelines
        )

    @property
    def entity_count(self) -> int:
        return len(self.all_entities)


class DocumentMetadata(BaseModel):
    """
    Document-level metadata that every chunk inherits a subset of.
    Populated by the MetadataExtractor and OntologyMapper services.
    """

    # Tenant / access control
    organization_id:   str
    department_id:     str
    knowledge_base_id: str

    # Document identity
    document_type:    str
    medical_specialty: MedicalSpecialty = MedicalSpecialty.GENERAL
    audience:         list[str] = []
    source:           str
    version:          str = "1.0"
    approval_status:  str = "draft"
    publication_date: Optional[datetime] = None
    author:           str = ""
    tags:             list[str] = []

    # Enriched medical knowledge
    medical: MedicalMetadata = Field(default_factory=MedicalMetadata)

    @field_validator("organization_id", "department_id", "knowledge_base_id", "source")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("required metadata field must not be empty")
        return v.strip()

    @property
    def completeness_score(self) -> float:
        """
        Fraction of required fields that are filled.
        Used by the ValidationPipeline to gate indexing.
        """
        required = [
            self.organization_id,
            self.department_id,
            self.knowledge_base_id,
            self.document_type,
            self.source,
            self.version,
            self.author,
        ]
        filled = sum(1 for f in required if f and str(f).strip())
        return filled / len(required)
