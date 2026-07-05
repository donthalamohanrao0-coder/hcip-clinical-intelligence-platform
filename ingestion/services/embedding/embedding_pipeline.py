from __future__ import annotations

import logging
from typing import Optional

from ingestion.config import Settings, get_settings
from ingestion.exceptions import EmbeddingError
from ingestion.models import Chunk, ChunkType
from ingestion.storage.redis_client import RedisCache
from ingestion.storage.s3_storage import S3Storage

from .image_embedder import ImageEmbedder
from .text_embedder import TextEmbedder

logger = logging.getLogger(__name__)

# Chunk types that use text embedding (TEXT + TABLE both go into BGE-M3)
_TEXT_TYPES: frozenset[ChunkType] = frozenset({
    ChunkType.TEXT,
    ChunkType.HEADING,
    ChunkType.TABLE,
})

_TEXT_MODEL_NAME  = "BAAI/bge-m3"
_IMAGE_MODEL_NAME = "vidore/colqwen2-v1.0"


class EmbeddingPipeline:
    """
    Routes chunks to the correct embedder and injects embeddings in-place.

    Routing rules:
        TEXT, HEADING, TABLE → TextEmbedder (BGE-M3, 1024-dim)
        FIGURE               → ImageEmbedder (ColQwen2, 128-dim) when s3_key present
                               Falls back to TextEmbedder on caption text if no S3 key

    Batch strategy:
        All text-type chunks are embedded in a single batched BGE-M3 call
        (with per-text Redis cache-first lookup).
        Figure chunks are embedded sequentially (each requires a separate
        S3 download + ColQwen inference pass).
    """

    def __init__(
        self,
        text_embedder:  Optional[TextEmbedder]  = None,
        image_embedder: Optional[ImageEmbedder] = None,
        cache:          Optional[RedisCache]     = None,
        s3:             Optional[S3Storage]      = None,
        settings:       Optional[Settings]       = None,
    ) -> None:
        cfg = settings or get_settings()
        self._text_embedder  = text_embedder  or TextEmbedder(cache=cache, settings=cfg)
        self._image_embedder = image_embedder or ImageEmbedder(s3=s3, settings=cfg)

    def embed(self, chunks: list[Chunk]) -> list[Chunk]:
        """
        Embed all chunks and inject .embedding + .embedding_model.
        Returns the same list with embeddings populated.
        Raises EmbeddingError if no text chunks could be embedded.
        """
        if not chunks:
            return chunks

        text_chunks   = [c for c in chunks if c.chunk_type in _TEXT_TYPES]
        figure_chunks = [c for c in chunks if c.chunk_type not in _TEXT_TYPES]

        # ── Batch-embed text chunks ───────────────────────────────────────────
        if text_chunks:
            self._embed_text_chunks(text_chunks)

        # ── Embed figure chunks ───────────────────────────────────────────────
        if figure_chunks:
            self._embed_figure_chunks(figure_chunks)

        embedded = sum(1 for c in chunks if c.is_embedded)
        logger.info(
            "EmbeddingPipeline | total=%d embedded=%d skipped=%d",
            len(chunks), embedded, len(chunks) - embedded,
        )
        return chunks

    # ── Private ───────────────────────────────────────────────────────────────

    def _embed_text_chunks(self, chunks: list[Chunk]) -> None:
        texts = [c.content for c in chunks]
        try:
            vectors = self._text_embedder.embed_batch(texts)
        except EmbeddingError as exc:
            logger.error("Text embedding failed: %s", exc)
            return

        for chunk, vector in zip(chunks, vectors):
            if vector:
                chunk.embedding       = vector
                chunk.embedding_model = _TEXT_MODEL_NAME

    def _embed_figure_chunks(self, chunks: list[Chunk]) -> None:
        for chunk in chunks:
            s3_key = chunk.metadata.section  # set by FigureChunker

            if s3_key:
                vector = self._image_embedder.embed_figure(s3_key)
                if vector:
                    chunk.embedding       = vector
                    chunk.embedding_model = _IMAGE_MODEL_NAME
                    continue

            # No S3 key or image embedding failed → embed caption text instead
            try:
                vector = self._text_embedder.embed(chunk.content)
                chunk.embedding       = vector
                chunk.embedding_model = _TEXT_MODEL_NAME
            except EmbeddingError as exc:
                logger.warning(
                    "Caption text embedding failed for chunk=%s: %s",
                    chunk.chunk_id, exc,
                )
