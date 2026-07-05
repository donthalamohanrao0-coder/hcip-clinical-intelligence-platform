from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration loaded from environment variables / .env file.
    All pipeline services receive this via dependency injection.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    app_name: str = "HCIP Ingestion Pipeline"
    environment: str = "development"
    debug: bool = False

    # ── AWS S3 ───────────────────────────────────────────────────────────────
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    s3_bucket: str = "hcip-documents"
    s3_raw_prefix: str = "raw"
    s3_parsed_prefix: str = "parsed"
    s3_versions_prefix: str = "versions"

    # ── Supabase ─────────────────────────────────────────────────────────────
    supabase_url: str = ""
    supabase_service_key: str = ""

    # ── Qdrant ───────────────────────────────────────────────────────────────
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_api_key: str = ""
    qdrant_text_collection: str = "hcip_text"
    qdrant_image_collection: str = "hcip_images"
    qdrant_table_collection: str = "hcip_tables"

    # ── Neo4j ────────────────────────────────────────────────────────────────
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # ── Redis ────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # ── Embedding ────────────────────────────────────────────────────────────
    text_embedding_model: str = "BAAI/bge-base-en-v1.5"
    embedding_vector_dim: int = 768
    embedding_batch_size: int = 64
    embedding_cache_ttl_seconds: int = 86_400       # 24 hours

    # ── LLM (used only for metadata enrichment & classification fallback) ────
    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"    # cheapest OpenAI model — cost-first principle
    llm_max_tokens: int = 1024

    # ── File processing ──────────────────────────────────────────────────────
    max_file_size_mb: int = 100
    allowed_extensions: list[str] = Field(
        default=[
            "pdf", "docx", "pptx", "xlsx", "csv", "txt",
            "png", "jpg", "jpeg", "tiff",
            "json", "xml",
        ]
    )

    # ── Chunking ─────────────────────────────────────────────────────────────
    max_chunk_tokens: int = 512
    min_chunk_tokens: int = 50
    chunk_overlap_tokens: int = 50
    semantic_similarity_threshold: float = 0.85     # boundary detection cut-off

    # ── Quality thresholds ───────────────────────────────────────────────────
    ocr_confidence_threshold: float = 0.70
    metadata_completeness_threshold: float = 0.95
    chunk_quality_threshold: float = 0.90
    index_readiness_threshold: float = 0.85

    # ── Elasticsearch ───────────────────────────────────────────────────────
    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_api_key: str = ""
    elasticsearch_chunk_index: str = "hcip_chunks"

    # ── PubMed / NCBI E-utilities ────────────────────────────────────────────
    pubmed_api_key: str = ""
    pubmed_max_results: int = 5

    # ── Query cache (4-layer) ─────────────────────────────────────────────────
    cache_exact_ttl_seconds:       int   = 3_600    # L1: 1 hour
    cache_semantic_ttl_seconds:    int   = 3_600    # L2: 1 hour
    cache_semantic_threshold:      float = 0.95     # L2: cosine similarity cut-off
    cache_retrieval_ttl_seconds:   int   = 1_800    # L3: 30 minutes
    qdrant_query_cache_collection: str   = "hcip_query_cache"

    # ── Celery workers ───────────────────────────────────────────────────────
    celery_max_retries: int = 3
    celery_retry_backoff_seconds: int = 60

    # ── API / Auth (Phase 22) ─────────────────────────────────────────────────
    # API keys: JSON array of "rawkey:org_id:role" strings.
    # Example .env entry:  API_KEYS=["sk-abc:org-1:physician","sk-xyz:org-2:admin"]
    api_keys: list[str] = Field(default_factory=list)

    # JWT: set JWT_SECRET to enable user-session auth.
    jwt_secret:    str = "REPLACE_WITH_JWT_SECRET"
    jwt_algorithm: str = "HS256"

    # CORS: set to specific origins in production, e.g. ["https://app.hcip.ai"].
    cors_origins: list[str] = Field(default=["*"])

    # Rate limiting (requests per minute per credential).
    rate_limit_per_minute: int = 60

    # ── Observability (Phase 24) ──────────────────────────────────────────────
    # OpenTelemetry: set OTEL_ENDPOINT to export traces to Grafana Tempo.
    # e.g. OTEL_ENDPOINT=http://localhost:4318/v1/traces
    otel_endpoint: str = ""

    # Langfuse: LLM call tracing (cost, tokens, quality).
    # Get keys at https://cloud.langfuse.com or self-host via docker-compose.
    langfuse_secret_key: str = "REPLACE_WITH_LANGFUSE_SECRET_KEY"
    langfuse_public_key: str = "REPLACE_WITH_LANGFUSE_PUBLIC_KEY"
    langfuse_base_url:   str = "https://cloud.langfuse.com"

    # ── Derived helpers (not in .env) ─────────────────────────────────────────
    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()
