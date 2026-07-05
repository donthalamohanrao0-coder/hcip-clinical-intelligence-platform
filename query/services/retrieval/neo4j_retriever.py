from __future__ import annotations

import asyncio
import re
import time
from typing import Optional

from ingestion.storage.neo4j_client import Neo4jClient
from query.models.query import RetrievalQuery, RetrievalSource
from query.models.result import RetrievedChunk, RetrievalResult

from .base_retriever import BaseRetriever

_MIN_TOKEN_LEN = 4  # skip tokens shorter than this (articles, conjunctions)

_GRAPH_CYPHER = """
UNWIND $tokens AS token
MATCH (e)
WHERE toLower(e.name) CONTAINS toLower(token)
MATCH (e)-[r:MENTIONED_IN]->(d:Document)
WITH  r.chunk_id          AS chunk_id,
      d.document_id        AS document_id,
      count(DISTINCT e)    AS match_count,
      collect(DISTINCT e.name) AS matched_entities
ORDER BY match_count DESC
LIMIT $limit
RETURN chunk_id, document_id, match_count, matched_entities
"""


def _tokenize(text: str) -> list[str]:
    """Extract meaningful tokens from free-text clinical query."""
    return [t for t in re.findall(r"[a-zA-Z0-9]+", text) if len(t) >= _MIN_TOKEN_LEN]


class Neo4jRetriever(BaseRetriever):
    """
    Graph-based retrieval via MENTIONED_IN relationship traversal.

    For each meaningful token in the query, finds entities whose name contains
    that token, then returns the document chunks those entities are mentioned in.
    Score = entity_match_count / max_entity_match_count (normalised).

    Content field is populated with matched entity names as a placeholder;
    the Retriever Agent (Phase 17) enriches this with full chunk text from Qdrant.
    """

    def __init__(self, client: Optional[Neo4jClient] = None) -> None:
        self._client = client or Neo4jClient()

    _graph_populated: bool | None = None  # class-level cache

    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        tokens = _tokenize(query.query_text)
        if not tokens:
            return RetrievalResult(source=RetrievalSource.NEO4J, chunks=[])

        # Skip Cypher if graph is known empty — avoids noisy schema warnings
        if Neo4jRetriever._graph_populated is None:
            try:
                count = await asyncio.to_thread(
                    self._client.execute_query,
                    "MATCH (n) RETURN count(n) AS c LIMIT 1",
                    {},
                )
                Neo4jRetriever._graph_populated = bool(count and int(count[0].get("c", 0)) > 0)
            except Exception:
                Neo4jRetriever._graph_populated = False

        if not Neo4jRetriever._graph_populated:
            return RetrievalResult(source=RetrievalSource.NEO4J, chunks=[])

        start = time.monotonic()
        try:
            raw = await asyncio.to_thread(
                self._client.execute_query,
                _GRAPH_CYPHER,
                {"tokens": tokens, "limit": query.top_k},
            )
        except Exception as exc:
            return RetrievalResult(
                source     = RetrievalSource.NEO4J,
                latency_ms = (time.monotonic() - start) * 1000,
                error      = str(exc),
            )

        if not raw:
            return RetrievalResult(
                source     = RetrievalSource.NEO4J,
                chunks     = [],
                latency_ms = (time.monotonic() - start) * 1000,
            )

        max_count = max(int(r["match_count"]) for r in raw)

        chunks = [
            RetrievedChunk(
                chunk_id    = r["chunk_id"] or f"neo4j:{r['document_id']}:{idx}",
                document_id = r["document_id"],
                content     = "[Graph match] " + ", ".join(r["matched_entities"]),
                score       = int(r["match_count"]) / max_count,
                rank        = idx,
                source      = RetrievalSource.NEO4J,
                metadata    = {
                    "matched_entities": r["matched_entities"],
                    "match_count":      int(r["match_count"]),
                },
            )
            for idx, r in enumerate(raw)
            if (int(r["match_count"]) / max_count) >= query.min_score
        ]

        return RetrievalResult(
            source     = RetrievalSource.NEO4J,
            chunks     = chunks,
            latency_ms = (time.monotonic() - start) * 1000,
        )

    def health_check(self) -> bool:
        return self._client.verify_connectivity()
