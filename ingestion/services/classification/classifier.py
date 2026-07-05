from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from ingestion.config import Settings, get_settings
from ingestion.exceptions import ClassificationError
from ingestion.models import DocumentType, FileType, ParsedContent

logger = logging.getLogger(__name__)

# ── Keyword sets per document type ────────────────────────────────────────────
# Heuristics-first principle: no LLM needed for clear-cut cases.

_KEYWORDS: dict[DocumentType, frozenset[str]] = {
    DocumentType.RESEARCH_PAPER: frozenset({
        "abstract", "introduction", "methods", "results", "discussion",
        "conclusion", "references", "doi", "pubmed", "cohort", "randomized",
        "controlled trial", "meta-analysis", "systematic review", "p-value",
        "confidence interval", "study design", "participants", "journal",
    }),
    DocumentType.CLINICAL_GUIDELINE: frozenset({
        "guideline", "recommendation", "evidence", "grade", "level of evidence",
        "who guideline", "cdc", "nice", "clinical practice", "consensus",
        "strong recommendation", "weak recommendation", "should be considered",
    }),
    DocumentType.SOP: frozenset({
        "standard operating procedure", "sop", "procedure number",
        "effective date", "revision date", "approved by", "scope",
        "responsible party", "step-by-step", "flowchart", "checklist",
    }),
    DocumentType.DRUG_REFERENCE: frozenset({
        "pharmacology", "dosage", "contraindication", "side effect",
        "adverse reaction", "drug interaction", "mechanism of action",
        "pharmacokinetics", "brand name", "generic name", "rxnorm",
        "maximum dose", "maintenance dose", "loading dose",
    }),
    DocumentType.INSURANCE_POLICY: frozenset({
        "coverage", "benefit", "premium", "deductible", "claim",
        "policy number", "copay", "prior authorization", "network",
        "out-of-pocket", "formulary", "insured member",
    }),
    DocumentType.LAB_REPORT: frozenset({
        "reference range", "specimen", "lab result", "normal range",
        "collected", "received", "reported by", "laboratory", "assay",
        "serum", "plasma", "whole blood", "urinalysis", "culture",
    }),
    DocumentType.MEDICAL_IMAGE: frozenset({
        "radiology report", "impression", "findings", "modality",
        "projection", "view", "contrast", "scout image", "mri", "ct scan",
    }),
}

# Minimum score fraction to declare a winner without LLM fallback
_CONFIDENCE_THRESHOLD = 0.10


class DocumentClassifier:
    """
    Classifies a document into one of the DocumentType categories.

    Strategy (cost-first):
        1. File-type shortcut  — images are always MEDICAL_IMAGE
        2. Keyword scoring     — count weighted keyword hits in first 3000 chars
        3. LLM fallback        — Claude Haiku when no category clears the threshold
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._cfg = settings or get_settings()

    def classify(
        self,
        content:   ParsedContent,
        filename:  str,
        file_type: FileType,
    ) -> DocumentType:
        """Return the most likely DocumentType for the given document."""

        # Shortcut: images are always MEDICAL_IMAGE
        if file_type.is_image:
            return DocumentType.MEDICAL_IMAGE

        # Keyword-based scoring on first 3000 chars (cheap, no network)
        probe_text = content.text[:3_000].lower()
        winner, score = self._score_keywords(probe_text)

        if score >= _CONFIDENCE_THRESHOLD:
            logger.info(
                "Classification | file=%s type=%s score=%.3f (heuristic)",
                filename, winner.value, score,
            )
            return winner

        # LLM fallback when content is ambiguous
        if self._cfg.anthropic_api_key:
            llm_type = self._classify_with_llm(probe_text, filename)
            if llm_type:
                logger.info(
                    "Classification | file=%s type=%s (llm fallback)",
                    filename, llm_type.value,
                )
                return llm_type

        logger.info("Classification | file=%s type=general (no match)", filename)
        return DocumentType.GENERAL

    # ── Private ───────────────────────────────────────────────────────────────

    @staticmethod
    def _score_keywords(text: str) -> tuple[DocumentType, float]:
        """
        Score every document type and return the best match + normalised score.
        Score = matched_keywords / total_keywords_in_category.
        """
        best_type  = DocumentType.GENERAL
        best_score = 0.0

        for doc_type, keywords in _KEYWORDS.items():
            if not keywords:
                continue
            hits  = sum(1 for kw in keywords if kw in text)
            score = hits / len(keywords)
            if score > best_score:
                best_score = score
                best_type  = doc_type

        return best_type, best_score

    def _classify_with_llm(self, text: str, filename: str) -> Optional[DocumentType]:
        """Call Claude Haiku to classify the document when heuristics are inconclusive."""
        valid_types = ", ".join(dt.value for dt in DocumentType)
        prompt = (
            f"Classify this healthcare document. Return one of: {valid_types}\n"
            f"Return ONLY the type value, no explanation.\n\n"
            f"Filename: {filename}\n"
            f"Content:\n{text[:2_000]}"
        )
        try:
            import anthropic
            client   = anthropic.Anthropic(api_key=self._cfg.anthropic_api_key)
            response = client.messages.create(
                model=self._cfg.llm_model,
                max_tokens=20,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip().lower()
            return DocumentType(raw)
        except Exception as exc:
            logger.warning("LLM classification failed for '%s': %s", filename, exc)
            return None
