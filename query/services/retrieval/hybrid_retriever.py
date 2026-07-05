from __future__ import annotations

import asyncio
import time
from typing import Optional

from query.models.query import RetrievalQuery, RetrievalSource, RetrievalStrategy
from query.models.result import FusedResult, RetrievedChunk, RetrievalResult

from .base_retriever import BaseRetriever
from .elasticsearch_retriever import ElasticsearchRetriever
from .neo4j_retriever import Neo4jRetriever
from .pubmed_retriever import PubMedRetriever
from .qdrant_retriever import QdrantRetriever

_RRF_K = 60  # standard constant — gives strong credit to top ranks, diminishing returns below rank ~10


def _reciprocal_rank_fusion(
    results: list[RetrievalResult],
    top_k:   int,
) -> list[RetrievedChunk]:
    """
    Merge multi-source results using Reciprocal Rank Fusion.

    Formula: rrf_score(chunk) = Σ  1 / (k + rank + 1)  across all sources.
    When the same chunk_id appears in multiple sources the scores are summed
    and the version with the richest content is kept.
    """
    rrf_scores:  dict[str, float]          = {}
    chunk_by_id: dict[str, RetrievedChunk] = {}

    for result in results:
        if not result.success:
            continue
        for chunk in result.chunks:
            rrf_scores[chunk.chunk_id] = (
                rrf_scores.get(chunk.chunk_id, 0.0) + 1.0 / (_RRF_K + chunk.rank + 1)
            )
            # Keep the chunk with the longer (richer) content when deduplicating
            existing = chunk_by_id.get(chunk.chunk_id)
            if existing is None or len(chunk.content) > len(existing.content):
                chunk_by_id[chunk.chunk_id] = chunk

    sorted_ids = sorted(rrf_scores, key=lambda cid: rrf_scores[cid], reverse=True)[:top_k]

    fused: list[RetrievedChunk] = []
    for final_rank, cid in enumerate(sorted_ids):
        chunk           = chunk_by_id[cid].model_copy(deep=True)
        chunk.rrf_score = rrf_scores[cid]
        chunk.rank      = final_rank
        fused.append(chunk)

    return fused


class HybridRetriever:
    """
    Parallel multi-source retrieval + RRF fusion.

    Strategy shortcuts route to a single source:
        VECTOR_ONLY  → Qdrant
        KEYWORD_ONLY → Elasticsearch
        GRAPH_ONLY   → Neo4j
        PUBMED_ONLY  → PubMed
        HYBRID       → all four sources in parallel (default)

    Failed retrievers are excluded from fusion but their errors are surfaced
    in FusedResult.source_results for observability.
    """

    def __init__(
        self,
        qdrant:  Optional[QdrantRetriever]        = None,
        elastic: Optional[ElasticsearchRetriever] = None,
        neo4j:   Optional[Neo4jRetriever]         = None,
        pubmed:  Optional[PubMedRetriever]        = None,
    ) -> None:
        self._qdrant  = qdrant  or QdrantRetriever()
        self._elastic = elastic or ElasticsearchRetriever()
        self._neo4j   = neo4j   or Neo4jRetriever()
        self._pubmed  = pubmed  or PubMedRetriever()

        self._source_map: dict[RetrievalSource, BaseRetriever] = {
            RetrievalSource.QDRANT:        self._qdrant,
            RetrievalSource.ELASTICSEARCH: self._elastic,
            RetrievalSource.NEO4J:         self._neo4j,
            RetrievalSource.PUBMED:        self._pubmed,
        }

    async def retrieve(self, query: RetrievalQuery) -> FusedResult:
        start  = time.monotonic()
        active = self._active_sources(query)

        results_list: list[RetrievalResult] = await asyncio.gather(
            *[self._source_map[src].retrieve(query) for src in active]
        )
        source_results: dict[str, RetrievalResult] = {
            src.value: res
            for src, res in zip(active, results_list)
        }

        fused_chunks = _reciprocal_rank_fusion(list(source_results.values()), query.top_k)

        return FusedResult(
            query_text       = query.query_text,
            chunks           = fused_chunks,
            source_results   = source_results,
            total_latency_ms = (time.monotonic() - start) * 1000,
            sources_used     = active,
        )

    def _active_sources(self, query: RetrievalQuery) -> list[RetrievalSource]:
        strategy_map: dict[RetrievalStrategy, list[RetrievalSource]] = {
            RetrievalStrategy.VECTOR_ONLY:  [RetrievalSource.QDRANT],
            RetrievalStrategy.KEYWORD_ONLY: [RetrievalSource.ELASTICSEARCH],
            RetrievalStrategy.GRAPH_ONLY:   [RetrievalSource.NEO4J],
            RetrievalStrategy.PUBMED_ONLY:  [RetrievalSource.PUBMED],
        }
        if query.strategy in strategy_map:
            return strategy_map[query.strategy]

        # HYBRID: use explicitly requested sources (defaults to all four)
        sources = list(query.sources)
        if not query.include_pubmed and RetrievalSource.PUBMED in sources:
            sources.remove(RetrievalSource.PUBMED)
        return sources

    def health_check(self) -> dict[str, bool]:
        return {
            src.value: retriever.health_check()
            for src, retriever in self._source_map.items()
        }
