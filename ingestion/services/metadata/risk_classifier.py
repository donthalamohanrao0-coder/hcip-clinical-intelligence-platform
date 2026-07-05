from __future__ import annotations

import logging

from ingestion.models import DocumentMetadata, MedicalMetadata, ParsedContent, RiskLevel

logger = logging.getLogger(__name__)

# ── Keyword sets — pure heuristics, no network, no LLM ───────────────────────

_HIGH_RISK_KEYWORDS: frozenset[str] = frozenset({
    # Chemotherapy / oncology
    "chemotherapy", "cytotoxic", "antineoplastic", "immunosuppressant",
    # Anticoagulation / bleeding risk
    "anticoagulant", "warfarin", "heparin", "thrombolytic", "tpa",
    # Narcotics / controlled substances
    "opioid", "morphine", "fentanyl", "oxycodone", "controlled substance",
    # High-alert medications
    "insulin", "methotrexate", "lithium", "digoxin", "phenytoin",
    # Procedures with serious risk
    "intubation", "ventilator", "resuscitation", "code blue", "defibrillation",
    "transfusion", "bone marrow", "organ transplant",
    # Dosage danger signals
    "overdose", "toxicity", "lethal dose", "ld50", "maximum dose",
    # Legal / regulatory risk
    "do not resuscitate", "dnr", "end of life", "palliative", "euthanasia",
    # Infection / transmission risk
    "isolation", "ebola", "anthrax", "smallpox", "bioterrorism",
})

_MEDIUM_RISK_KEYWORDS: frozenset[str] = frozenset({
    # Prescription-only drugs (broad)
    "antibiotic", "antifungal", "antiviral", "antihypertensive",
    "statin", "beta-blocker", "ace inhibitor", "diuretic",
    # Common but watch-for interactions
    "drug interaction", "contraindication", "adverse event",
    "allergy", "anaphylaxis", "side effect",
    # Minor procedures
    "biopsy", "lumbar puncture", "catheter", "injection", "infusion",
    # Chronic disease management
    "diabetes management", "blood pressure control", "insulin dose",
    # Diagnostic risk
    "false positive", "missed diagnosis", "differential diagnosis",
    # Moderate regulatory flag
    "prior authorization", "formulary restriction", "off-label",
})

# If neither high nor medium keywords appear → LOW risk


class RiskClassifier:
    """
    Assign a RiskLevel (HIGH / MEDIUM / LOW) to a document.

    Implementation: pure keyword matching — no network call, no LLM, no cost.
    HIGH takes precedence over MEDIUM; any keyword match is enough.

    Called by MetadataEnrichmentService after entities are extracted so
    entity text is available for additional signal.
    """

    def classify(
        self,
        content:  ParsedContent,
        metadata: DocumentMetadata,
    ) -> RiskLevel:
        """
        Return the risk level for the document.
        Checks document text + entity normalized_text for risk keywords.
        """
        text_lower = self._build_corpus(content, metadata.medical)

        if self._matches(text_lower, _HIGH_RISK_KEYWORDS):
            level = RiskLevel.HIGH
        elif self._matches(text_lower, _MEDIUM_RISK_KEYWORDS):
            level = RiskLevel.MEDIUM
        else:
            level = RiskLevel.LOW

        logger.info(
            "RiskClassifier | specialty=%s doc_type=%s risk=%s",
            metadata.medical_specialty,
            metadata.document_type,
            level.value,
        )
        return level

    # ── Private ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_corpus(content: ParsedContent, medical: MedicalMetadata) -> str:
        """
        Combine document text (first 8000 chars) + all entity normalized_text
        into a single lowercase corpus for keyword matching.
        """
        parts: list[str] = [content.text[:8_000].lower()]
        if medical:
            for entity in medical.all_entities:
                parts.append(entity.normalized_text)
        return " ".join(parts)

    @staticmethod
    def _matches(corpus: str, keyword_set: frozenset[str]) -> bool:
        return any(kw in corpus for kw in keyword_set)
