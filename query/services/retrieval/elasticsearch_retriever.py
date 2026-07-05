from __future__ import annotations

import time
from typing import Any, Optional

from elasticsearch import AsyncElasticsearch

from ingestion.config import get_settings
from query.models.query import RetrievalQuery, RetrievalSource
from query.models.result import RetrievedChunk, RetrievalResult

from .base_retriever import BaseRetriever

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


class ElasticsearchRetriever(BaseRetriever):
    """
    BM25 keyword retrieval over Elasticsearch.

    Multi-match query across content (boosted 2×), section, and entities fields.
    Enforces org / knowledge-base / approval_status as term filters (no scoring cost).
    BM25 scores are normalised by dividing by the top hit's score so all values
    land in (0, 1] before being passed to RRF fusion.
    """

    def __init__(self, es: Optional[AsyncElasticsearch] = None) -> None:
        cfg         = get_settings()
        self._es    = es or AsyncElasticsearch(
            cfg.elasticsearch_url,
            api_key=cfg.elasticsearch_api_key or None,
        )
        self._index = cfg.elasticsearch_chunk_index

    async def ensure_index_exists(self) -> None:
        """Idempotent index creation with the HCIP chunk mapping."""
        exists = await self._es.indices.exists(index=self._index)
        if not exists:
            await self._es.indices.create(index=self._index, body=_INDEX_MAPPING)

    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        start = time.monotonic()
        try:
            # Only filter on fields actually stored by the ingest router.
            # roles / risk_level are not stored in our simplified ingest payload,
            # so adding those filters would silently return zero results.
            filters: list[dict[str, Any]] = [
                {"term": {"organization_id":   query.organization_id}},
                {"term": {"knowledge_base_id": query.knowledge_base_id}},
                {"term": {"approval_status":   "approved"}},
            ]

            body: dict[str, Any] = {
                "query": {
                    "bool": {
                        "must": [
                            {
                                "multi_match": {
                                    "query":  query.query_text,
                                    # ingest router stores body as "text"; "content" is the
                                    # production field name — try both via copy_to / fallback
                                    "fields": ["text^2", "content^2", "source"],
                                    "type":   "best_fields",
                                }
                            }
                        ],
                        "filter": filters,
                    }
                },
                "size": query.top_k,
            }

            resp  = await self._es.search(index=self._index, body=body)
            hits  = resp["hits"]["hits"]
            max_s = hits[0]["_score"] if hits else 1.0

            _skip = {"chunk_id", "document_id", "text", "content"}
            chunks = [
                RetrievedChunk(
                    chunk_id    = h["_source"]["chunk_id"],
                    document_id = h["_source"]["document_id"],
                    content     = h["_source"].get("text") or h["_source"].get("content", ""),
                    score       = h["_score"] / max_s,
                    rank        = idx,
                    source      = RetrievalSource.ELASTICSEARCH,
                    metadata    = {k: v for k, v in h["_source"].items() if k not in _skip},
                )
                for idx, h in enumerate(hits)
                if (h["_score"] / max_s) >= query.min_score
            ]

        except Exception as exc:
            return RetrievalResult(
                source     = RetrievalSource.ELASTICSEARCH,
                latency_ms = (time.monotonic() - start) * 1000,
                error      = str(exc),
            )

        return RetrievalResult(
            source     = RetrievalSource.ELASTICSEARCH,
            chunks     = chunks,
            latency_ms = (time.monotonic() - start) * 1000,
        )

    def health_check(self) -> bool:
        import asyncio as _asyncio
        try:
            loop = _asyncio.get_event_loop()
            return bool(loop.run_until_complete(self._es.ping()))
        except Exception:
            return False
