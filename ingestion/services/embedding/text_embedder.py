from __future__ import annotations

import hashlib
import logging
from typing import Optional

from ingestion.config import Settings, get_settings
from ingestion.exceptions import EmbeddingError
from ingestion.storage.redis_client import RedisCache

logger = logging.getLogger(__name__)

_MODEL_NAME    = "BAAI/bge-base-en-v1.5"
_VECTOR_DIM    = 768
_BATCH_SIZE    = 64          # sentence-transformers handles larger batches efficiently
_CACHE_TTL     = 86_400 * 30  # 30 days — embeddings are deterministic


class TextEmbedder:
    """
    Dense text embedder using BGE-base-en-v1.5 (768-dim, ~430 MB RAM).

    The underlying SentenceTransformer is a class-level singleton — it loads
    once per process and is shared across all TextEmbedder instances.

    Cost-optimisation: every text is SHA256-keyed in Redis so repeated
    chunks (e.g. across document versions) never trigger a second inference.
    """

    _model = None  # lazy class-level singleton

    def __init__(
        self,
        cache:    Optional[RedisCache] = None,
        settings: Optional[Settings]   = None,
    ) -> None:
        self._cache = cache
        self._cfg   = settings or get_settings()

    # ── Public API ────────────────────────────────────────────────────────────

    def embed(self, text: str) -> list[float]:
        """Embed a single text string. Returns a 1024-dim vector."""
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of texts with cache-first lookup.
        Cache misses are grouped into a single BGE-M3 inference call.
        Always returns results in the same order as the input.
        """
        if not texts:
            return []

        keys      = [self._cache_key(t) for t in texts]
        cached    = self._fetch_cache(keys)           # list[Optional[list[float]]]
        miss_idx  = [i for i, v in enumerate(cached) if v is None]

        if miss_idx:
            miss_texts     = [texts[i] for i in miss_idx]
            new_embeddings = self._encode(miss_texts)  # one inference call
            for i, emb in zip(miss_idx, new_embeddings):
                cached[i] = emb
                if self._cache:
                    self._cache.set_embedding(keys[i], emb, ttl_seconds=_CACHE_TTL)

        return [v for v in cached]  # type: ignore[return-value]

    # ── Encoding ──────────────────────────────────────────────────────────────

    @classmethod
    def _load_model(cls):
        if cls._model is not None:
            return cls._model
        try:
            from sentence_transformers import SentenceTransformer
            cls._model = SentenceTransformer(_MODEL_NAME)
            logger.info("BGE-base model loaded (%s)", _MODEL_NAME)
        except ImportError:
            logger.error(
                "sentence-transformers not installed. "
                "pip install sentence-transformers"
            )
            cls._model = None
        return cls._model

    def _encode(self, texts: list[str]) -> list[list[float]]:
        model = self._load_model()
        if model is None:
            raise EmbeddingError(
                "Embedding model unavailable. Install: pip install sentence-transformers"
            )
        try:
            results: list[list[float]] = []
            for start in range(0, len(texts), _BATCH_SIZE):
                batch = texts[start : start + _BATCH_SIZE]
                vecs  = model.encode(batch, normalize_embeddings=True)
                results.extend(v.tolist() for v in vecs)
            return results
        except Exception as exc:
            raise EmbeddingError(f"BGE-base encoding failed: {exc}") from exc

    # ── Cache helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _cache_key(text: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
        return f"emb:{digest}"

    def _fetch_cache(self, keys: list[str]) -> list[Optional[list[float]]]:
        if not self._cache:
            return [None] * len(keys)
        try:
            return self._cache.get_embeddings_batch(keys)
        except Exception as exc:
            logger.warning("Cache batch fetch failed: %s — will re-embed", exc)
            return [None] * len(keys)
