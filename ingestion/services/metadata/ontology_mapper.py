from __future__ import annotations

import logging
from typing import Optional

import httpx

from ingestion.models import (
    MedicalEntity,
    MedicalEntityType,
    MedicalMetadata,
    OntologyMapping,
    OntologyStandard,
)
from ingestion.storage.redis_client import RedisCache

logger = logging.getLogger(__name__)

_RXNORM_BASE = "https://rxnav.nlm.nih.gov/REST"
_ICD10_BASE  = "https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search"
_LOINC_BASE  = "https://clinicaltables.nlm.nih.gov/api/loinc_items/v3/search"

_CACHE_TTL = 7 * 24 * 3600  # 7 days
_TIMEOUT   = 5.0             # seconds


class OntologyMapper:
    """
    Map medical entities to standard ontology codes using free public APIs.

    Routing:
        DRUG                 → RxNorm
        DISEASE              → ICD-10
        LAB_TEST             → LOINC
        Everything else      → no mapping (not enough coverage in free APIs)

    All lookups are cached in Redis for 7 days.
    API failures are swallowed — missing codes never block ingestion.
    """

    def __init__(self, cache: Optional[RedisCache] = None) -> None:
        self._cache  = cache
        self._client = httpx.Client(timeout=_TIMEOUT)

    def map(self, metadata: MedicalMetadata) -> MedicalMetadata:
        """Enrich entity ontology_mappings in-place; returns same object."""
        for entity in metadata.diseases:
            self._enrich(entity, OntologyStandard.ICD_10, self._lookup_icd10)

        for entity in metadata.drugs:
            self._enrich(entity, OntologyStandard.RXNORM, self._lookup_rxnorm)

        # LAB_TEST entities are grouped in treatments; iterate all_entities
        for entity in metadata.all_entities:
            if entity.entity_type == MedicalEntityType.LAB_TEST:
                self._enrich(entity, OntologyStandard.LOINC, self._lookup_loinc)

        return metadata

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ── Enrichment driver ─────────────────────────────────────────────────────

    def _enrich(
        self,
        entity:    MedicalEntity,
        standard:  OntologyStandard,
        lookup_fn,
    ) -> None:
        if any(m.standard == standard for m in entity.ontology_mappings):
            return  # already mapped
        mapping = self._cached_lookup(entity.normalized_text, standard, lookup_fn)
        if mapping:
            entity.ontology_mappings.append(mapping)

    def _cached_lookup(
        self,
        term:      str,
        standard:  OntologyStandard,
        lookup_fn,
    ) -> Optional[OntologyMapping]:
        cache_key = f"ontology:{standard.value}:{term}"
        if self._cache:
            cached = self._cache.get_json(cache_key)
            if cached is not None:
                return OntologyMapping(**cached) if cached else None

        result = lookup_fn(term)
        if self._cache:
            self._cache.set_json(
                cache_key,
                result.model_dump() if result else {},
                ttl_seconds=_CACHE_TTL,
            )
        return result

    # ── RxNorm ────────────────────────────────────────────────────────────────

    def _lookup_rxnorm(self, term: str) -> Optional[OntologyMapping]:
        try:
            resp = self._client.get(
                f"{_RXNORM_BASE}/rxcui.json",
                params={"name": term, "search": 1},
            )
            if resp.status_code != 200:
                return None
            rxcui = resp.json().get("idGroup", {}).get("rxnormId", [None])[0]
            if not rxcui:
                return None

            name_resp    = self._client.get(f"{_RXNORM_BASE}/rxcui/{rxcui}/properties.json")
            display_name = term
            if name_resp.status_code == 200:
                display_name = name_resp.json().get("properties", {}).get("name", term)

            return OntologyMapping(
                standard=OntologyStandard.RXNORM,
                code=rxcui,
                display_name=display_name,
                confidence=0.95,
            )
        except Exception as exc:
            logger.debug("RxNorm lookup failed for '%s': %s", term, exc)
            return None

    # ── ICD-10 ────────────────────────────────────────────────────────────────

    def _lookup_icd10(self, term: str) -> Optional[OntologyMapping]:
        try:
            resp = self._client.get(
                _ICD10_BASE,
                params={"sf": "code,name", "terms": term, "maxList": 1},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            # Response format: [total_count, [codes], extra, [[name, ...]]]
            if not data or not data[1]:
                return None
            code         = data[1][0]
            display_name = (data[3] or [[None]])[0][0] or term
            return OntologyMapping(
                standard=OntologyStandard.ICD_10,
                code=code,
                display_name=display_name,
                confidence=0.90,
            )
        except Exception as exc:
            logger.debug("ICD-10 lookup failed for '%s': %s", term, exc)
            return None

    # ── LOINC ─────────────────────────────────────────────────────────────────

    def _lookup_loinc(self, term: str) -> Optional[OntologyMapping]:
        try:
            resp = self._client.get(
                _LOINC_BASE,
                params={"sf": "LOINC_NUM,LONG_COMMON_NAME", "terms": term, "maxList": 1},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            if not data or not data[1]:
                return None
            code         = data[1][0]
            display_name = (data[3] or [[None, term]])[0][1] or term
            return OntologyMapping(
                standard=OntologyStandard.LOINC,
                code=code,
                display_name=display_name,
                confidence=0.88,
            )
        except Exception as exc:
            logger.debug("LOINC lookup failed for '%s': %s", term, exc)
            return None
