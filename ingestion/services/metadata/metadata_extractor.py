from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Optional

from ingestion.config import Settings, get_settings
from ingestion.exceptions import MetadataError
from ingestion.models import (
    DocumentMetadata,
    DocumentType,
    MedicalMetadata,
    MedicalSpecialty,
    ParsedContent,
)
from ingestion.storage.redis_client import RedisCache

logger = logging.getLogger(__name__)

# ── Specialty keyword map ──────────────────────────────────────────────────────
_SPECIALTY_KEYWORDS: dict[MedicalSpecialty, frozenset[str]] = {
    MedicalSpecialty.CARDIOLOGY:         frozenset({"cardiac", "heart", "coronary", "cardiovascular", "ecg", "arrhythmia", "myocardial", "angina", "atrial fibrillation"}),
    MedicalSpecialty.ONCOLOGY:           frozenset({"cancer", "tumor", "oncology", "chemotherapy", "malignant", "neoplasm", "carcinoma", "lymphoma", "metastasis"}),
    MedicalSpecialty.ENDOCRINOLOGY:      frozenset({"diabetes", "insulin", "thyroid", "hormone", "glucose", "hba1c", "endocrine", "hypoglycemia", "hyperglycemia"}),
    MedicalSpecialty.PHARMACOLOGY:       frozenset({"drug", "medication", "dosage", "pharmacokinetics", "adverse", "interaction", "contraindication", "formulary"}),
    MedicalSpecialty.NEUROLOGY:          frozenset({"neurological", "brain", "seizure", "stroke", "alzheimer", "parkinson", "neuropathy", "dementia", "epilepsy"}),
    MedicalSpecialty.INFECTIOUS_DISEASE: frozenset({"infection", "antibiotic", "viral", "bacterial", "sepsis", "pathogen", "antimicrobial", "hiv", "tuberculosis"}),
    MedicalSpecialty.RADIOLOGY:          frozenset({"imaging", "mri", "ct scan", "xray", "ultrasound", "radiograph", "radiology", "modality", "contrast"}),
    MedicalSpecialty.SURGERY:            frozenset({"surgical", "operation", "incision", "laparoscopic", "anesthesia", "postoperative", "perioperative", "resection"}),
    MedicalSpecialty.PEDIATRICS:         frozenset({"pediatric", "child", "neonatal", "infant", "adolescent", "newborn", "congenital", "paediatric"}),
}

# ── Regex patterns ────────────────────────────────────────────────────────────
_DATE_PATTERNS = [
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),                          # 2024-01-15
    re.compile(r"\b(\w+ \d{1,2},?\s+\d{4})\b"),                      # January 15, 2024
    re.compile(r"\bpublished[:\s]+([A-Za-z]+ \d{4})\b", re.I),       # Published: June 2024
    re.compile(r"\bdate[:\s]+(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})\b", re.I),
]
_VERSION_PATTERN  = re.compile(r"\bv(?:ersion)?\.?\s*(\d+(?:\.\d+)*)\b", re.I)
_AUTHOR_PATTERNS  = [
    re.compile(r"^authors?:?\s*(.+)$", re.I | re.M),
    re.compile(r"^prepared by:?\s*(.+)$", re.I | re.M),
    re.compile(r"^written by:?\s*(.+)$", re.I | re.M),
]
_AUDIENCE_KEYWORDS = {
    "clinician":     {"physician", "doctor", "clinician", "healthcare provider", "hcp", "nurse"},
    "patient":       {"patient", "patient education", "consumer", "caregiver", "public"},
    "pharmacist":    {"pharmacist", "pharmacy", "dispensing"},
    "administrator": {"administrator", "management", "compliance", "regulatory"},
    "researcher":    {"researcher", "scientist", "investigator", "study team"},
}


class MetadataExtractor:
    """
    Extracts document-level metadata from ParsedContent.

    Pipeline (cost-first):
        1. Regex + keyword heuristics  (free, instant)
        2. GPT-4o-mini LLM call        (only for missing fields: author, source, date)
        3. Cache LLM results in Redis  (no repeat calls for the same document)
    """

    def __init__(
        self,
        cache:    Optional[RedisCache] = None,
        settings: Optional[Settings]   = None,
    ) -> None:
        self._cache = cache
        self._cfg   = settings or get_settings()

    def extract(
        self,
        content:           ParsedContent,
        doc_type:          DocumentType,
        organization_id:   str,
        department_id:     str,
        knowledge_base_id: str,
        document_id:       str,
        source:            str = "",
    ) -> DocumentMetadata:
        """
        Build a DocumentMetadata from ParsedContent + upload context.
        Heuristics run first; LLM fills in only what's missing.
        """
        probe = content.text[:4_000]

        specialty        = self._detect_specialty(probe)
        version          = self._extract_version(probe)
        audience         = self._detect_audience(probe)
        author           = self._extract_author(probe)
        publication_date = self._extract_date(probe)

        # LLM fills gaps when key fields are still unknown
        missing = not author or not source or not publication_date
        if missing and self._cfg.openai_api_key:
            llm_data = self._enrich_with_llm(probe, document_id)
            author           = author           or llm_data.get("author", "")
            source           = source           or llm_data.get("source", "")
            publication_date = publication_date or self._parse_date(llm_data.get("publication_date"))
            version          = version          or llm_data.get("version", "1.0")
            if not audience:
                audience = llm_data.get("audience", [])

        return DocumentMetadata(
            organization_id   = organization_id,
            department_id     = department_id,
            knowledge_base_id = knowledge_base_id,
            document_type     = doc_type.value,
            medical_specialty = specialty,
            audience          = audience,
            source            = source,
            version           = version or "1.0",
            approval_status   = "draft",
            publication_date  = publication_date,
            author            = author,
            medical           = MedicalMetadata(),  # populated by MedicalEntityExtractor
        )

    # ── Heuristic extractors ──────────────────────────────────────────────────

    @staticmethod
    def _detect_specialty(text: str) -> MedicalSpecialty:
        lower = text.lower()
        best, best_hits = MedicalSpecialty.GENERAL, 0
        for specialty, keywords in _SPECIALTY_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw in lower)
            if hits > best_hits:
                best_hits = hits
                best      = specialty
        return best

    @staticmethod
    def _extract_version(text: str) -> str:
        match = _VERSION_PATTERN.search(text[:2_000])
        return match.group(1) if match else ""

    @staticmethod
    def _extract_author(text: str) -> str:
        for pattern in _AUTHOR_PATTERNS:
            match = pattern.search(text[:1_500])
            if match:
                raw = match.group(1).strip()
                # Trim excessively long matches (likely grabbed a paragraph)
                return raw[:120] if len(raw) < 120 else ""
        return ""

    @staticmethod
    def _extract_date(text: str) -> Optional[datetime]:
        for pattern in _DATE_PATTERNS:
            match = pattern.search(text[:2_000])
            if match:
                parsed = MetadataExtractor._parse_date(match.group(1))
                if parsed:
                    return parsed
        return None

    @staticmethod
    def _parse_date(raw: Optional[str]) -> Optional[datetime]:
        if not raw:
            return None
        formats = ["%Y-%m-%d", "%B %d, %Y", "%B %d %Y", "%B %Y",
                   "%b %Y", "%m/%d/%Y", "%m-%d-%Y", "%d/%m/%Y"]
        for fmt in formats:
            try:
                return datetime.strptime(raw.strip(), fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def _detect_audience(text: str) -> list[str]:
        lower   = text.lower()
        matched = [aud for aud, kws in _AUDIENCE_KEYWORDS.items()
                   if any(kw in lower for kw in kws)]
        return matched or ["clinician"]  # default — healthcare docs target clinicians

    # ── LLM enrichment ────────────────────────────────────────────────────────

    def _enrich_with_llm(self, text: str, document_id: str) -> dict:
        """
        Use Claude Haiku to fill missing metadata fields.
        Caches the result so repeated calls for the same document are free.
        """
        cache_key = f"meta:llm:{document_id}"
        if self._cache:
            cached = self._cache.get_json(cache_key)
            if cached:
                return cached

        prompt = (
            "Extract metadata from this healthcare document. "
            "Return ONLY valid JSON with these fields:\n"
            '{"author": "", "publication_date": "YYYY-MM-DD or null", '
            '"version": "1.0", "source": "", '
            '"audience": ["clinician"]}\n\n'
            f"Document (first 3000 chars):\n{text[:3_000]}"
        )
        try:
            from openai import OpenAI
            client   = OpenAI(api_key=self._cfg.openai_api_key)
            response = client.chat.completions.create(
                model=self._cfg.llm_model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            raw  = response.choices[0].message.content.strip()
            data = json.loads(raw)
            if self._cache:
                self._cache.set_json(cache_key, data, ttl_seconds=86_400)
            return data
        except Exception as exc:
            logger.warning("LLM metadata enrichment failed doc=%s: %s", document_id, exc)
            return {}
