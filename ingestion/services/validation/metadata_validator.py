from __future__ import annotations

import logging

from ingestion.models import DocumentMetadata

logger = logging.getLogger(__name__)

# How many entities before the entity bonus plateaus
_ENTITY_PLATEAU = 10


class MetadataValidator:
    """
    Scores metadata completeness and medical enrichment quality.

    Returns a float in [0.0, 1.0].

    Scoring model:
        Base completeness    80%  — DocumentMetadata.completeness_score
                                    (fraction of required fields filled)
        Entity coverage      15%  — entity_count / 10, capped at 1.0
        Ontology coverage     5%  — fraction of entities that have at least one
                                    ontology mapping (ICD-10, RxNorm, or LOINC)
    """

    def validate(self, doc_metadata: DocumentMetadata) -> float:
        base_score = doc_metadata.completeness_score  # 0.0–1.0

        medical = doc_metadata.medical
        total   = medical.entity_count

        entity_bonus = min(total / _ENTITY_PLATEAU, 1.0) * 0.15 if total > 0 else 0.0

        mapped        = sum(1 for e in medical.all_entities if e.ontology_mappings)
        ontology_bonus = (mapped / total) * 0.05 if total > 0 else 0.0

        score = min(base_score * 0.80 + entity_bonus + ontology_bonus, 1.0)

        logger.debug(
            "MetadataValidator | base=%.2f entities=%d mapped=%d score=%.3f",
            base_score, total, mapped, score,
        )
        return round(score, 4)
