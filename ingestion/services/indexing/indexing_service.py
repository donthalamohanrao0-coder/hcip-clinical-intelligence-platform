from __future__ import annotations

import logging
from typing import Optional

from ingestion.exceptions import IndexingError
from ingestion.models import Chunk, QualityScores
from ingestion.storage.qdrant_client import QdrantVectorStore
from ingestion.storage.supabase_client import SupabaseClient

from .qdrant_indexer import QdrantIndexer
from .supabase_indexer import SupabaseIndexer

logger = logging.getLogger(__name__)

_QUALITY_THRESHOLD = 0.85   # must match ValidationPipeline


class IndexingService:
    """
    Orchestrates the final indexing step of the ingestion pipeline.

    Execution order:
        1. Quality gate      — reject if index_readiness_score < 0.85
        2. Qdrant indexing   — upsert (or delete+upsert for re-index) all embedded chunks
        3. Supabase update   — mark document COMPLETED, close job, write audit log

    Failure handling:
        If Qdrant indexing fails → update Supabase to FAILED and re-raise.
        If Supabase update fails → Qdrant vectors are already in place; the
            document is technically searchable once approved, but the DB record
            is inconsistent. The error is re-raised so the Celery worker can
            retry only the Supabase update step.

    Re-indexing (is_reindex=True):
        Deletes all existing vectors for the document before upserting new ones.
        Called when a new document version supersedes the previous active version.
    """

    def __init__(
        self,
        qdrant_indexer:    Optional[QdrantIndexer]    = None,
        supabase_indexer:  Optional[SupabaseIndexer]  = None,
        qdrant:            Optional[QdrantVectorStore] = None,
        supabase:          Optional[SupabaseClient]    = None,
    ) -> None:
        self._qdrant_indexer   = qdrant_indexer   or QdrantIndexer(qdrant)
        self._supabase_indexer = supabase_indexer or SupabaseIndexer(supabase)

    def index(
        self,
        chunks:          list[Chunk],
        document_id:     str,
        job_id:          str,
        organization_id: str,
        scores:          QualityScores,
        is_reindex:      bool = False,
    ) -> int:
        """
        Run the full indexing step for a document.
        Returns the number of chunks indexed into Qdrant.
        Raises IndexingError on any failure after marking the document as FAILED.
        """
        # ── Quality gate ──────────────────────────────────────────────────────
        if not scores.is_ready_for_index(_QUALITY_THRESHOLD):
            error = (
                f"Quality gate blocked indexing for doc={document_id}: "
                f"readiness={scores.index_readiness_score:.3f} < {_QUALITY_THRESHOLD}"
            )
            logger.warning(error)
            self._supabase_indexer.fail(document_id, job_id, error)
            raise IndexingError(error)

        # ── Qdrant indexing ───────────────────────────────────────────────────
        try:
            chunk_count = (
                self._qdrant_indexer.reindex(chunks, document_id)
                if is_reindex
                else self._qdrant_indexer.index(chunks)
            )
        except IndexingError as exc:
            self._supabase_indexer.fail(document_id, job_id, str(exc))
            raise

        # ── Supabase completion ───────────────────────────────────────────────
        self._supabase_indexer.complete(
            document_id     = document_id,
            job_id          = job_id,
            organization_id = organization_id,
            chunk_count     = chunk_count,
        )

        logger.info(
            "IndexingService | doc=%s chunks=%d reindex=%s readiness=%.3f",
            document_id, chunk_count, is_reindex, scores.index_readiness_score,
        )
        return chunk_count
