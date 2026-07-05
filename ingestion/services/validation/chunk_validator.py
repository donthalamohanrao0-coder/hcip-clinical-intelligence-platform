from __future__ import annotations

import logging

from ingestion.models import Chunk

logger = logging.getLogger(__name__)

# Token sweet-spot (1 token ≈ 4 chars)
_MIN_AVG_TOKENS = 20
_MAX_AVG_TOKENS = 600

# Minimum content length for a chunk to count as "dense"
_MIN_CONTENT_CHARS = 50


class ChunkValidator:
    """
    Scores the quality of the chunking output for a document.

    Returns a float in [0.0, 1.0].

    Scoring model:
        Count adequacy   30%  — chunks / 5, capped at 1.0
                                (< 5 chunks suggests the document is very thin)
        Token distribution 40%  — 1.0 if avg tokens in [20, 600]
                                   0.6 if avg tokens > 600 (chunks too large)
                                   0.3 if avg tokens < 20  (chunks too small)
        Content density  30%  — fraction of chunks with ≥ 50 content chars

    Critical failure (returns 0.0):
        Any chunk has empty content after stripping whitespace.
    """

    def validate(self, chunks: list[Chunk]) -> float:
        if not chunks:
            logger.warning("ChunkValidator: no chunks produced — score=0.0")
            return 0.0

        # Critical failure gate — empty chunks break downstream embedding
        if any(not c.content.strip() for c in chunks):
            logger.error("ChunkValidator: empty chunk detected — score=0.0")
            return 0.0

        count_score  = min(len(chunks) / 5, 1.0)

        avg_tokens   = sum(c.token_count for c in chunks) / len(chunks)
        if avg_tokens < _MIN_AVG_TOKENS:
            token_score = 0.30   # severely fragmented
        elif avg_tokens > _MAX_AVG_TOKENS:
            token_score = 0.60   # chunks too large, will hurt retrieval precision
        else:
            token_score = 1.0    # sweet spot

        dense_count   = sum(1 for c in chunks if len(c.content) >= _MIN_CONTENT_CHARS)
        density_score = dense_count / len(chunks)

        score = (
            count_score   * 0.30
            + token_score * 0.40
            + density_score * 0.30
        )

        logger.debug(
            "ChunkValidator | count=%d avg_tokens=%.1f dense=%d score=%.3f",
            len(chunks), avg_tokens, dense_count, score,
        )
        return round(min(score, 1.0), 4)
