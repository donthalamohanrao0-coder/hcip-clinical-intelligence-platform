from __future__ import annotations

import json
import logging
from typing import Optional

from ingestion.config import Settings, get_settings
from ingestion.models import (
    MedicalEntity,
    MedicalEntityType,
    MedicalMetadata,
    ParsedContent,
)
from ingestion.storage.redis_client import RedisCache

logger = logging.getLogger(__name__)

_SCISPACY_MODEL = "en_core_sci_sm"

# Map spaCy/scispaCy entity labels → MedicalEntityType
_LABEL_MAP: dict[str, MedicalEntityType] = {
    "DISEASE":   MedicalEntityType.DISEASE,
    "DISORDER":  MedicalEntityType.DISEASE,
    "CHEMICAL":  MedicalEntityType.DRUG,
    "DRUG":      MedicalEntityType.DRUG,
    "PROCEDURE": MedicalEntityType.PROCEDURE,
    "SYMPTOM":   MedicalEntityType.SYMPTOM,
    "TREATMENT": MedicalEntityType.TREATMENT,
    "ANATOMY":   MedicalEntityType.ANATOMY,
    "LAB_TEST":  MedicalEntityType.LAB_TEST,
}

_MIN_CONFIDENCE = 0.40


class MedicalEntityExtractor:
    """
    Extract named medical entities from ParsedContent.

    Strategy (cost-first):
        1. scispaCy NER model  — free, runs locally
        2. Claude Haiku         — fallback when spaCy is unavailable or under-performs
    Results are cached in Redis with a 24-hour TTL keyed by document_id.
    """

    _nlp = None  # class-level singleton; loads once per process

    def __init__(
        self,
        cache:    Optional[RedisCache] = None,
        settings: Optional[Settings]   = None,
    ) -> None:
        self._cache = cache
        self._cfg   = settings or get_settings()

    def extract(self, content: ParsedContent, document_id: str) -> MedicalMetadata:
        cache_key = f"entities:{document_id}"
        if self._cache:
            cached = self._cache.get_json(cache_key)
            if cached:
                return self._from_cache(cached)

        text     = content.text[:6_000]
        entities = self._extract_with_spacy(text) or self._extract_with_llm(text, document_id)
        metadata = self._build_metadata(entities)

        if self._cache and entities:
            self._cache.set_json(cache_key, self._to_cache(metadata), ttl_seconds=86_400)

        logger.info("EntityExtractor | doc=%s entities=%d", document_id, len(entities))
        return metadata

    # ── spaCy path ────────────────────────────────────────────────────────────

    @classmethod
    def _load_nlp(cls):
        if cls._nlp is not None:
            return cls._nlp
        try:
            import spacy
            cls._nlp = spacy.load(_SCISPACY_MODEL)
            logger.info("scispaCy model '%s' loaded", _SCISPACY_MODEL)
        except (ImportError, OSError):
            logger.warning(
                "scispaCy '%s' not available. "
                "pip install scispacy && python -m spacy download %s",
                _SCISPACY_MODEL, _SCISPACY_MODEL,
            )
            cls._nlp = None
        return cls._nlp

    def _extract_with_spacy(self, text: str) -> list[MedicalEntity]:
        nlp = self._load_nlp()
        if nlp is None:
            return []
        try:
            doc    = nlp(text)
            seen   = set()
            result = []
            for ent in doc.ents:
                entity_type = _LABEL_MAP.get(ent.label_)
                if entity_type is None:
                    continue
                key = (ent.text.strip().lower(), entity_type)
                if key in seen:
                    continue
                seen.add(key)
                confidence = float(
                    getattr(ent, "kb_ents", [[None, 0.7]])[0][1] or 0.7
                )
                if confidence < _MIN_CONFIDENCE:
                    continue
                result.append(MedicalEntity(
                    text              = ent.text.strip(),
                    normalized_text   = ent.text.strip().lower(),
                    entity_type       = entity_type,
                    confidence        = confidence,
                    ontology_mappings = [],
                ))
            return result
        except Exception as exc:
            logger.warning("scispaCy extraction failed: %s", exc)
            return []

    # ── LLM fallback ──────────────────────────────────────────────────────────

    def _extract_with_llm(self, text: str, document_id: str) -> list[MedicalEntity]:
        if not self._cfg.anthropic_api_key:
            return []
        types_list = ", ".join(t.value for t in MedicalEntityType)
        prompt = (
            "Extract medical entities from the text below. "
            "Return ONLY a JSON array:\n"
            '[{"text": "...", "normalized_text": "...", "entity_type": "...", "confidence": 0.85}]\n'
            f"entity_type must be one of: {types_list}\n\n"
            f"Text:\n{text[:3_000]}"
        )
        try:
            import anthropic
            client   = anthropic.Anthropic(api_key=self._cfg.anthropic_api_key)
            response = client.messages.create(
                model      = self._cfg.llm_model,
                max_tokens = 1_024,
                messages   = [{"role": "user", "content": prompt}],
            )
            items  = json.loads(response.content[0].text.strip())
            result = []
            for item in items:
                try:
                    conf = float(item.get("confidence", 0.75))
                    if conf < _MIN_CONFIDENCE:
                        continue
                    result.append(MedicalEntity(
                        text              = item["text"],
                        normalized_text   = item.get("normalized_text", item["text"].lower()),
                        entity_type       = MedicalEntityType(item["entity_type"]),
                        confidence        = conf,
                        ontology_mappings = [],
                    ))
                except (KeyError, ValueError):
                    continue
            logger.info("LLM entity extraction | doc=%s count=%d", document_id, len(result))
            return result
        except Exception as exc:
            logger.warning("LLM entity extraction failed doc=%s: %s", document_id, exc)
            return []

    # ── Metadata assembly ─────────────────────────────────────────────────────

    @staticmethod
    def _build_metadata(entities: list[MedicalEntity]) -> MedicalMetadata:
        m = MedicalMetadata()
        for e in entities:
            if e.entity_type == MedicalEntityType.DISEASE:
                m.diseases.append(e)
            elif e.entity_type == MedicalEntityType.DRUG:
                m.drugs.append(e)
            elif e.entity_type == MedicalEntityType.PROCEDURE:
                m.procedures.append(e)
            elif e.entity_type == MedicalEntityType.SYMPTOM:
                m.symptoms.append(e)
            elif e.entity_type == MedicalEntityType.TREATMENT:
                m.treatments.append(e)
            elif e.entity_type == MedicalEntityType.GUIDELINE:
                m.guidelines.append(e)
            # ANATOMY and LAB_TEST are valid entity types but MedicalMetadata
            # groups them under treatments as closest clinical bucket
            elif e.entity_type in (MedicalEntityType.ANATOMY, MedicalEntityType.LAB_TEST):
                m.treatments.append(e)
        return m

    # ── Cache helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _to_cache(m: MedicalMetadata) -> dict:
        return {
            "diseases":   [e.model_dump() for e in m.diseases],
            "drugs":      [e.model_dump() for e in m.drugs],
            "procedures": [e.model_dump() for e in m.procedures],
            "symptoms":   [e.model_dump() for e in m.symptoms],
            "treatments": [e.model_dump() for e in m.treatments],
            "guidelines": [e.model_dump() for e in m.guidelines],
        }

    @staticmethod
    def _from_cache(data: dict) -> MedicalMetadata:
        def _load(lst: list) -> list[MedicalEntity]:
            out = []
            for item in lst:
                try:
                    out.append(MedicalEntity(**item))
                except Exception:
                    continue
            return out

        return MedicalMetadata(
            diseases   = _load(data.get("diseases",   [])),
            drugs      = _load(data.get("drugs",      [])),
            procedures = _load(data.get("procedures", [])),
            symptoms   = _load(data.get("symptoms",   [])),
            treatments = _load(data.get("treatments", [])),
            guidelines = _load(data.get("guidelines", [])),
        )
