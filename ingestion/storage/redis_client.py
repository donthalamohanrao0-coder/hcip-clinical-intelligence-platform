import hashlib
import json
from typing import Any, Optional

import redis

from ingestion.config import Settings, get_settings
from ingestion.exceptions import CacheError


class RedisCache:
    """
    Wrapper for Redis cache operations used by:
        - EmbeddingPipeline   → cache computed embeddings   (TTL 24 h)
        - MetadataExtractor   → cache LLM enrichment calls  (TTL 24 h)
        - OntologyMapper      → cache ontology lookups       (TTL 7 d)
        - IngestionPipeline   → semantic dedup cache         (TTL 1 h)

    Redis as the Celery broker is configured separately in workers/celery_app.py.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        cfg = settings or get_settings()
        self._client: redis.Redis = redis.Redis.from_url(
            cfg.redis_url,
            decode_responses=False,     # we manage encoding ourselves
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        self._default_ttl = cfg.embedding_cache_ttl_seconds

    # ── Key helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def embedding_key(text: str, model: str) -> str:
        """Deterministic cache key for a text + model pair."""
        digest = hashlib.sha256(f"{model}:{text}".encode()).hexdigest()
        return f"embed:{digest}"

    @staticmethod
    def ontology_key(standard: str, term: str) -> str:
        """Cache key for an ontology lookup result."""
        digest = hashlib.md5(f"{standard}:{term.lower()}".encode()).hexdigest()
        return f"ontology:{standard}:{digest}"

    @staticmethod
    def metadata_key(doc_id: str) -> str:
        return f"meta:{doc_id}"

    # ── Raw bytes ─────────────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[bytes]:
        try:
            return self._client.get(key)
        except redis.RedisError as exc:
            raise CacheError(f"GET [{key}] failed: {exc}") from exc

    def set(self, key: str, value: bytes, ttl_seconds: Optional[int] = None) -> None:
        try:
            self._client.setex(key, ttl_seconds or self._default_ttl, value)
        except redis.RedisError as exc:
            raise CacheError(f"SET [{key}] failed: {exc}") from exc

    # ── JSON helpers ──────────────────────────────────────────────────────────

    def get_json(self, key: str) -> Optional[Any]:
        raw = self.get(key)
        return json.loads(raw) if raw is not None else None

    def set_json(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        self.set(key, json.dumps(value, default=str).encode(), ttl_seconds)

    # ── Embedding-specific helpers ────────────────────────────────────────────

    def get_embedding(self, text: str, model: str) -> Optional[list[float]]:
        """Return a cached embedding vector, or None on cache miss."""
        return self.get_json(self.embedding_key(text, model))

    def set_embedding(
        self, text: str, model: str, vector: list[float], ttl_seconds: Optional[int] = None
    ) -> None:
        self.set_json(self.embedding_key(text, model), vector, ttl_seconds)

    def get_embeddings_batch(
        self, texts: list[str], model: str
    ) -> dict[str, Optional[list[float]]]:
        """
        Pipeline GET for a batch of texts.
        Returns a dict mapping text → vector (or None on miss).
        Uses a Redis pipeline for a single round-trip.
        """
        keys = [self.embedding_key(t, model) for t in texts]
        try:
            with self._client.pipeline(transaction=False) as pipe:
                for key in keys:
                    pipe.get(key)
                raw_values = pipe.execute()
        except redis.RedisError as exc:
            raise CacheError(f"batch GET failed: {exc}") from exc

        return {
            text: (json.loads(raw) if raw is not None else None)
            for text, raw in zip(texts, raw_values)
        }

    # ── Utility ───────────────────────────────────────────────────────────────

    def exists(self, key: str) -> bool:
        try:
            return bool(self._client.exists(key))
        except redis.RedisError as exc:
            raise CacheError(f"EXISTS [{key}] failed: {exc}") from exc

    def delete(self, *keys: str) -> None:
        if not keys:
            return
        try:
            self._client.delete(*keys)
        except redis.RedisError as exc:
            raise CacheError(f"DELETE failed: {exc}") from exc

    def verify_connectivity(self) -> bool:
        try:
            return self._client.ping()
        except redis.RedisError:
            return False

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "RedisCache":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
