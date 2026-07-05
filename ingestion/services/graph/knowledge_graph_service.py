from __future__ import annotations

import hashlib
import logging
from typing import Optional

from ingestion.exceptions import KnowledgeGraphError
from ingestion.models import (
    Chunk,
    DocumentMetadata,
    MedicalEntity,
    MedicalEntityType,
    MedicalMetadata,
    OntologyStandard,
)
from ingestion.storage.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)

# ── Entity type → Neo4j label ─────────────────────────────────────────────────
_LABEL: dict[MedicalEntityType, str] = {
    MedicalEntityType.DISEASE:   "Disease",
    MedicalEntityType.DRUG:      "Drug",
    MedicalEntityType.SYMPTOM:   "Symptom",
    MedicalEntityType.PROCEDURE: "Procedure",
    MedicalEntityType.TREATMENT: "Treatment",
    MedicalEntityType.GUIDELINE: "Guideline",
    MedicalEntityType.ANATOMY:   "Anatomy",
    MedicalEntityType.LAB_TEST:  "LabTest",
}


def _entity_id(entity_type: MedicalEntityType, normalized_text: str) -> str:
    """
    Stable, reproducible ID for a medical concept.
    Same concept across documents always maps to the same Neo4j node.
    """
    raw = f"{entity_type.value}:{normalized_text}"
    return hashlib.md5(raw.encode()).hexdigest()


class KnowledgeGraphService:
    """
    Builds and maintains the medical knowledge graph in Neo4j.

    Graph schema
    ────────────
    Nodes:
        Document  — one per ingested document
        Disease, Drug, Symptom, Procedure, Treatment, Guideline, Anatomy, LabTest

    Relationships:
        (Document)  -[:MENTIONS]->       (Entity)     — every entity in the doc
        (Drug)      -[:TREATS]->         (Disease)    — co-occurrence signal
        (Disease)   -[:CAUSES]->         (Symptom)    — co-occurrence signal
        (Entity)    -[:MENTIONED_IN]->   (Document)   — per-chunk link for GraphRAG

    Co-occurrence edges represent correlation in the same document, not causal facts.
    They are merge-safe (MERGE prevents duplicates on re-indexing).
    """

    def __init__(self, neo4j: Optional[Neo4jClient] = None) -> None:
        self._neo4j = neo4j or Neo4jClient()

    def index_document(
        self,
        document_id:      str,
        organization_id:  str,
        doc_metadata:     DocumentMetadata,
        chunks:           list[Chunk],
    ) -> None:
        """
        Full graph indexing for a document. Idempotent — safe to re-run.
        Order:
            1. Upsert Document node
            2. Upsert all entity nodes
            3. Document -[:MENTIONS]-> each entity
            4. Drug -[:TREATS]-> Disease  (co-occurrence)
            5. Disease -[:CAUSES]-> Symptom  (co-occurrence)
            6. Entity -[:MENTIONED_IN]-> Document  (per-chunk links)
        """
        try:
            medical = doc_metadata.medical

            self._upsert_document(document_id, organization_id, doc_metadata)
            entity_ids = self._upsert_entities(medical)
            self._create_mentions(document_id, entity_ids)
            self._create_treats(medical)
            self._create_causes(medical)
            self._link_chunks(chunks, document_id)

            logger.info(
                "KnowledgeGraph | doc=%s entities=%d chunks=%d",
                document_id, len(entity_ids), len(chunks),
            )
        except Exception as exc:
            raise KnowledgeGraphError(
                f"Graph indexing failed for doc={document_id}: {exc}"
            ) from exc

    # ── Node upserts ──────────────────────────────────────────────────────────

    def _upsert_document(
        self,
        document_id:     str,
        organization_id: str,
        doc_metadata:    DocumentMetadata,
    ) -> None:
        self._neo4j.upsert_entity(
            label = "Document",
            properties = {
                "document_id":      document_id,
                "organization_id":  organization_id,
                "document_type":    doc_metadata.document_type,
                "specialty":        doc_metadata.medical_specialty.value,
                "source":           doc_metadata.source,
                "version":          doc_metadata.version,
                "author":           doc_metadata.author,
                "knowledge_base_id":doc_metadata.knowledge_base_id,
            },
            match_keys=["document_id"],
        )

    def _upsert_entities(self, medical: MedicalMetadata) -> list[str]:
        """
        Upsert all entity nodes and return their stable entity_ids.
        Ontology codes (ICD-10, RxNorm) are stored as indexed properties.
        """
        entity_ids: list[str] = []
        for entity in medical.all_entities:
            label = _LABEL.get(entity.entity_type)
            if label is None:
                continue
            eid        = _entity_id(entity.entity_type, entity.normalized_text)
            properties = self._build_entity_props(entity, eid)
            self._neo4j.upsert_entity(
                label      = label,
                properties = properties,
                match_keys = ["entity_id"],
            )
            entity_ids.append(eid)
        return entity_ids

    @staticmethod
    def _build_entity_props(entity: MedicalEntity, eid: str) -> dict:
        props: dict = {
            "entity_id":      eid,
            "normalized_text":entity.normalized_text,
            "display_name":   entity.text,
            "confidence":     entity.confidence,
            "entity_type":    entity.entity_type.value,
        }
        # Add ontology codes as first-class properties for indexed lookup
        for mapping in entity.ontology_mappings:
            if mapping.standard == OntologyStandard.ICD_10:
                props["icd10_code"]    = mapping.code
                props["icd10_display"] = mapping.display_name
            elif mapping.standard == OntologyStandard.RXNORM:
                props["rxnorm_code"]    = mapping.code
                props["rxnorm_display"] = mapping.display_name
            elif mapping.standard == OntologyStandard.LOINC:
                props["loinc_code"]    = mapping.code
                props["loinc_display"] = mapping.display_name
        return props

    # ── Relationship creation ─────────────────────────────────────────────────

    def _create_mentions(self, document_id: str, entity_ids: list[str]) -> None:
        """Document -[:MENTIONS]-> each entity in a single UNWIND batch."""
        if not entity_ids:
            return
        self._neo4j.execute_query(
            """
            MATCH (doc:Document {document_id: $doc_id})
            UNWIND $ids AS eid
            MATCH (e {entity_id: eid})
            MERGE (doc)-[:MENTIONS]->(e)
            """,
            {"doc_id": document_id, "ids": entity_ids},
        )

    def _create_treats(self, medical: MedicalMetadata) -> None:
        """Drug -[:TREATS]-> Disease for every drug-disease pair in this document."""
        drug_ids    = [_entity_id(e.entity_type, e.normalized_text) for e in medical.drugs]
        disease_ids = [_entity_id(e.entity_type, e.normalized_text) for e in medical.diseases]
        if not drug_ids or not disease_ids:
            return
        self._neo4j.execute_query(
            """
            UNWIND $drug_ids AS did
            UNWIND $disease_ids AS disid
            MATCH (d:Drug    {entity_id: did})
            MATCH (dis:Disease {entity_id: disid})
            MERGE (d)-[:TREATS]->(dis)
            """,
            {"drug_ids": drug_ids, "disease_ids": disease_ids},
        )

    def _create_causes(self, medical: MedicalMetadata) -> None:
        """Disease -[:CAUSES]-> Symptom for every disease-symptom pair in this document."""
        disease_ids = [_entity_id(e.entity_type, e.normalized_text) for e in medical.diseases]
        symptom_ids = [_entity_id(e.entity_type, e.normalized_text) for e in medical.symptoms]
        if not disease_ids or not symptom_ids:
            return
        self._neo4j.execute_query(
            """
            UNWIND $disease_ids AS disid
            UNWIND $symptom_ids AS sid
            MATCH (dis:Disease {entity_id: disid})
            MATCH (s:Symptom   {entity_id: sid})
            MERGE (dis)-[:CAUSES]->(s)
            """,
            {"disease_ids": disease_ids, "symptom_ids": symptom_ids},
        )

    def _link_chunks(self, chunks: list[Chunk], document_id: str) -> None:
        """
        Entity -[:MENTIONED_IN {chunk_id}]-> Document for every chunk.
        Uses the chunk's entity list (inherited from document-level entities).
        Batches all entity_ids per chunk in a single call.
        """
        for chunk in chunks:
            entity_ids = [
                _entity_id(e.entity_type, e.normalized_text)
                for e in chunk.metadata.entities
            ]
            if entity_ids:
                self._neo4j.link_chunk_to_entities(
                    chunk_id    = chunk.chunk_id,
                    entity_ids  = entity_ids,
                    document_id = document_id,
                )

    # ── Deletion (for re-indexing) ────────────────────────────────────────────

    def delete_document(self, document_id: str) -> None:
        """
        Remove the Document node and all its MENTIONS / MENTIONED_IN edges.
        Entity nodes are intentionally left — they may be referenced by other docs.
        """
        try:
            self._neo4j.execute_query(
                """
                MATCH (doc:Document {document_id: $doc_id})
                OPTIONAL MATCH (doc)-[r]-()
                DELETE r, doc
                """,
                {"doc_id": document_id},
            )
            logger.info("KnowledgeGraph | deleted document node doc=%s", document_id)
        except Exception as exc:
            raise KnowledgeGraphError(
                f"delete_document({document_id}) failed: {exc}"
            ) from exc
