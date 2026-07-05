from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class QueryIntent(str, Enum):
    DIAGNOSIS = "diagnosis"
    TREATMENT = "treatment"
    DRUG_INFO = "drug_info"
    PROTOCOL  = "protocol"
    RESEARCH  = "research"
    GENERAL   = "general"


class RetrievalSource(str, Enum):
    QDRANT        = "qdrant"
    ELASTICSEARCH = "elasticsearch"
    NEO4J         = "neo4j"
    PUBMED        = "pubmed"


class RetrievalStrategy(str, Enum):
    HYBRID       = "hybrid"         # all sources, RRF fusion
    VECTOR_ONLY  = "vector_only"    # Qdrant only
    KEYWORD_ONLY = "keyword_only"   # Elasticsearch only
    GRAPH_ONLY   = "graph_only"     # Neo4j only
    PUBMED_ONLY  = "pubmed_only"    # live PubMed only


class RetrievalQuery(BaseModel):
    """Input contract for every retriever in the pipeline."""

    query_text:        str
    query_embedding:   Optional[list[float]] = None    # pre-computed by EmbeddingPipeline
    organization_id:   str
    knowledge_base_id: str
    role:              Optional[str]         = None    # RBAC filter
    risk_levels:       Optional[list[str]]   = None    # e.g. ["low", "medium"]
    top_k:             int                   = Field(default=10, ge=1, le=50)
    sources:           list[RetrievalSource] = Field(
        default_factory=lambda: list(RetrievalSource)
    )
    strategy:          RetrievalStrategy     = RetrievalStrategy.HYBRID
    intent:            QueryIntent           = QueryIntent.GENERAL
    include_pubmed:    bool                  = True
    min_score:         float                 = Field(default=0.0, ge=0.0, le=1.0)
