from __future__ import annotations

import logging
from typing import Optional

from ingestion.models import Chunk, ChunkType, DocumentMetadata, ParsedContent, RiskLevel

from .base_chunker import BaseChunker

logger = logging.getLogger(__name__)

_SIMILARITY_THRESHOLD = 0.85   # cosine similarity above which sentences are merged


class SemanticChunker(BaseChunker):
    """
    Groups sentences by semantic similarity using BGE-M3 embeddings.

    Produces more topically coherent chunks than sliding-window or sentence-
    boundary splitting — but is significantly more expensive (GPU/CPU inference).

    Trigger rule (enforced by ChunkingEngine):
        • DocumentType.RESEARCH_PAPER with text > 8 000 chars

    Falls back to sentence-boundary grouping when the embedding model
    is unavailable (FlagEmbedding / sentence-transformers not installed).
    """

    # Lazy class-level singleton — the model loads once per process
    _model = None

    @property
    def chunk_type(self) -> ChunkType:
        return ChunkType.TEXT

    def __init__(
        self,
        max_tokens:         int   = 512,
        similarity_threshold: float = _SIMILARITY_THRESHOLD,
    ) -> None:
        self.MAX_TOKENS           = max_tokens
        self._similarity_threshold = similarity_threshold

    def _do_chunk(
        self,
        content:          ParsedContent,
        document_id:      str,
        document_version: str,
        doc_metadata:     DocumentMetadata,
        risk_level:       RiskLevel,
    ) -> list[Chunk]:
        sentences = self._split_sentences(content.text)
        if not sentences:
            sentences = [content.text]

        embeddings = self._embed_sentences(sentences)
        if embeddings is None:
            # Model unavailable — degrade gracefully to sentence grouping
            logger.warning(
                "SemanticChunker: no embedding model — falling back to sentence grouping"
            )
            windows = self._group_by_tokens(sentences, self.MAX_TOKENS, self.OVERLAP_TOKENS)
        else:
            windows = self._merge_by_similarity(sentences, embeddings)

        chunks = []
        for idx, window in enumerate(windows):
            chunks.append(self._make_chunk(
                text             = window,
                document_id      = document_id,
                document_version = document_version,
                doc_metadata     = doc_metadata,
                risk_level       = risk_level,
                chunk_index      = idx,
            ))
        return chunks

    # ── Embedding ─────────────────────────────────────────────────────────────

    @classmethod
    def _load_model(cls):
        if cls._model is not None:
            return cls._model
        try:
            from FlagEmbedding import FlagModel
            cls._model = FlagModel(
                "BAAI/bge-m3",
                use_fp16=True,
                query_instruction_for_retrieval="",
            )
            logger.info("BGE-M3 model loaded for SemanticChunker")
        except ImportError:
            logger.warning(
                "FlagEmbedding not installed — SemanticChunker will fall back. "
                "pip install FlagEmbedding"
            )
            cls._model = None
        return cls._model

    def _embed_sentences(self, sentences: list[str]) -> Optional[list[list[float]]]:
        model = self._load_model()
        if model is None:
            return None
        try:
            embeddings = model.encode(sentences)
            return [e.tolist() for e in embeddings]
        except Exception as exc:
            logger.warning("Embedding failed in SemanticChunker: %s", exc)
            return None

    # ── Similarity grouping ────────────────────────────────────────────────────

    def _merge_by_similarity(
        self,
        sentences:  list[str],
        embeddings: list[list[float]],
    ) -> list[str]:
        """
        Group consecutive sentences that are semantically similar into one chunk.
        Start a new chunk when similarity drops below threshold OR the current
        chunk would exceed MAX_TOKENS.
        """
        max_chars = self.MAX_TOKENS * 4
        groups:  list[str] = []
        current: list[str] = [sentences[0]]
        cur_len  = len(sentences[0])

        for i in range(1, len(sentences)):
            sim     = self._cosine(embeddings[i - 1], embeddings[i])
            seg_len = len(sentences[i])

            if sim >= self._similarity_threshold and cur_len + seg_len <= max_chars:
                current.append(sentences[i])
                cur_len += seg_len
            else:
                groups.append(" ".join(current))
                current = [sentences[i]]
                cur_len = seg_len

        if current:
            groups.append(" ".join(current))

        return groups

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot   = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
