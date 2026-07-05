from __future__ import annotations

import logging
from typing import Optional

from ingestion.config import Settings, get_settings
from ingestion.models import Document, DocumentMetadata, DocumentType, FileType, ParsedContent, RiskLevel
from ingestion.storage.redis_client import RedisCache

from .medical_entity_extractor import MedicalEntityExtractor
from .metadata_extractor import MetadataExtractor
from .ontology_mapper import OntologyMapper
from .risk_classifier import RiskClassifier

logger = logging.getLogger(__name__)


class MetadataEnrichmentService:
    """
    Orchestrates the full metadata enrichment pipeline for a single document.

    Execution order:
        1. MetadataExtractor     — doc-level fields (specialty, author, date, audience)
        2. MedicalEntityExtractor — NER (diseases, medications, procedures …)
        3. OntologyMapper        — map entities to ICD-10 / RxNorm / LOINC codes
        4. RiskClassifier        — assign HIGH / MEDIUM / LOW risk level

    All components are injected via constructor (testable, replaceable).
    When dependencies are None, sensible defaults are auto-constructed.
    """

    def __init__(
        self,
        metadata_extractor: Optional[MetadataExtractor]       = None,
        entity_extractor:   Optional[MedicalEntityExtractor]  = None,
        ontology_mapper:    Optional[OntologyMapper]           = None,
        risk_classifier:    Optional[RiskClassifier]           = None,
        cache:              Optional[RedisCache]               = None,
        settings:           Optional[Settings]                 = None,
    ) -> None:
        cfg = settings or get_settings()
        self._metadata_extractor = metadata_extractor or MetadataExtractor(cache=cache, settings=cfg)
        self._entity_extractor   = entity_extractor   or MedicalEntityExtractor(cache=cache, settings=cfg)
        self._ontology_mapper    = ontology_mapper    or OntologyMapper(cache=cache)
        self._risk_classifier    = risk_classifier    or RiskClassifier()

    def enrich(
        self,
        content:           ParsedContent,
        document_id:       str,
        organization_id:   str,
        department_id:     str,
        knowledge_base_id: str,
        doc_type:          DocumentType,
        file_type:         FileType,
        source:            str = "",
    ) -> tuple[DocumentMetadata, RiskLevel]:
        """
        Run the full enrichment pipeline. Returns (DocumentMetadata, RiskLevel).

        The returned DocumentMetadata has a fully populated `medical` field
        with entities, ontology codes, and confidence scores.
        """
        # 1. Extract doc-level metadata (specialty, author, date, version, audience)
        doc_metadata = self._metadata_extractor.extract(
            content           = content,
            doc_type          = doc_type,
            organization_id   = organization_id,
            department_id     = department_id,
            knowledge_base_id = knowledge_base_id,
            document_id       = document_id,
            source            = source,
        )

        # 2. Extract medical entities (NER)
        medical = self._entity_extractor.extract(content, document_id)

        # 3. Map entities to ontology codes (ICD-10, RxNorm, LOINC)
        medical = self._ontology_mapper.map(medical)

        # 4. Attach enriched medical metadata
        doc_metadata.medical = medical

        # 5. Classify document risk level
        risk_level = self._risk_classifier.classify(content, doc_metadata)

        logger.info(
            "Enrichment complete | doc=%s specialty=%s entities=%d risk=%s completeness=%.2f",
            document_id,
            doc_metadata.medical_specialty,
            medical.entity_count,
            risk_level.value,
            doc_metadata.completeness_score,
        )
        return doc_metadata, risk_level
