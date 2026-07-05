from __future__ import annotations

import logging
from typing import Any, Optional

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from ingestion.config import Settings, get_settings
from ingestion.exceptions import IndexingError
from ingestion.models import Chunk

logger = logging.getLogger(__name__)

_INDEX_MAPPING: dict[str, Any] = {
    "mappings": {
        "properties": {
            "chunk_id":          {"type": "keyword"},
            "document_id":       {"type": "keyword"},
            "organization_id":   {"type": "keyword"},
            "knowledge_base_id": {"type": "keyword"},
            "content":           {"type": "text", "analyzer": "english"},
            "chunk_type":        {"type": "keyword"},
            "specialty":         {"type": "keyword"},
            "source":            {"type": "keyword"},
            "document_type":     {"type": "keyword"},
            "approval_status":   {"type": "keyword"},
            "risk_level":        {"type": "keyword"},
            "roles":             {"type": "keyword"},
            "section":           {"type": "text"},
            "subsection":        {"type": "text"},
            "entities":          {"type": "text"},
            "icd10_codes":       {"type": "keyword"},
            "rxnorm_codes":      {"type": "keyword"},
            "chunk_index":       {"type": "integer"},
            "page_number":       {"type": "integer"},
            "token_count":       {"type": "integer"},
        }
    },
    "settings": {
        "number_of_shards":   1,
        "number_of_replicas": 0,
    },
}


class ElasticsearchIndexer:
    """
    BM25 indexer: writes chunks to Elasticsearch alongside Qdrant vector storage.

    Mirrors the QdrantIndexer interface so IndexingService can include it
    as an optional third indexer without restructuring the pipeline.
    Uses the synchronous Elasticsearch client to match the Celery worker model.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        cfg         = settings or get_settings()
        self._es    = Elasticsearch(
            cfg.elasticsearch_url,
            api_key=cfg.elasticsearch_api_key or None,
        )
        self._index = cfg.elasticsearch_chunk_index

    def ensure_index_exists(self) -> None:
        if not self._es.indices.exists(index=self._index):
            self._es.indices.create(index=self._index, body=_INDEX_MAPPING)
            logger.info("Created Elasticsearch index '%s'", self._index)

    def index(self, chunks: list[Chunk]) -> int:
        """Bulk-index chunks; returns the count successfully indexed."""
        if not chunks:
            return 0
        self.ensure_index_exists()
        try:
            actions  = [self._to_action(c) for c in chunks]
            success, _ = bulk(self._es, actions, raise_on_error=True)
            logger.info("ElasticsearchIndexer | indexed %d chunks", success)
            return success
        except Exception as exc:
            raise IndexingError(f"Elasticsearch bulk index failed: {exc}") from exc

    def reindex(self, chunks: list[Chunk], document_id: str) -> int:
        """Delete existing vectors for document_id then re-index."""
        self.delete_by_document(document_id)
        return self.index(chunks)

    def delete_by_document(self, document_id: str) -> None:
        try:
            self._es.delete_by_query(
                index   = self._index,
                body    = {"query": {"term": {"document_id": document_id}}},
                refresh = True,
            )
        except Exception as exc:
            raise IndexingError(
                f"Elasticsearch delete_by_document({document_id}) failed: {exc}"
            ) from exc

    def _to_action(self, chunk: Chunk) -> dict[str, Any]:
        payload = chunk.to_qdrant_payload()
        return {
            "_index": self._index,
            "_id":    chunk.chunk_id,
            "_source": {
                "chunk_id":          chunk.chunk_id,
                "document_id":       chunk.document_id,
                "organization_id":   chunk.metadata.organization_id,
                "knowledge_base_id": chunk.metadata.knowledge_base_id,
                "content":           chunk.content,
                "chunk_type":        chunk.chunk_type.value,
                "specialty":         chunk.metadata.specialty,
                "source":            chunk.metadata.source,
                "document_type":     chunk.metadata.document_type,
                "approval_status":   chunk.metadata.approval_status,
                "risk_level":        chunk.metadata.risk_level.value,
                "roles":             chunk.metadata.roles,
                "section":           chunk.metadata.section,
                "subsection":        chunk.metadata.subsection,
                "entities":          " ".join(e.text for e in chunk.metadata.entities),
                "icd10_codes":       payload["icd10_codes"],
                "rxnorm_codes":      payload["rxnorm_codes"],
                "chunk_index":       chunk.metadata.chunk_index,
                "page_number":       chunk.metadata.page_number,
                "token_count":       chunk.token_count,
            },
        }
