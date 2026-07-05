from __future__ import annotations

import logging
from typing import Optional

from ingestion.exceptions import IndexingError
from ingestion.models import ProcessingStatus
from ingestion.storage.supabase_client import SupabaseClient

logger = logging.getLogger(__name__)


class SupabaseIndexer:
    """
    Updates Supabase records to reflect the outcome of the indexing stage.

    On success (complete):
        1. Document processing_status → COMPLETED
        2. Ingestion job stage="indexing", status="completed"
        3. Audit log entry with chunk_count

    On failure (fail):
        1. Document processing_status → FAILED
        2. Ingestion job stage="indexing", status="failed" + error_message
        3. Audit log entry with error detail

    These are intentionally lightweight — no separate chunks table is maintained
    in Supabase. The vector store (Qdrant) is the source of truth for chunks.
    """

    def __init__(self, supabase: Optional[SupabaseClient] = None) -> None:
        self._db = supabase or SupabaseClient()

    def complete(
        self,
        document_id:     str,
        job_id:          str,
        organization_id: str,
        chunk_count:     int,
    ) -> None:
        """Mark the document and job as successfully indexed."""
        try:
            self._db.update_processing_status(document_id, ProcessingStatus.COMPLETED)
            self._db.update_job(job_id, stage="indexing", status="completed")
            self._db.write_audit_log(
                document_id = document_id,
                action      = "indexed",
                actor       = "system",
                extra       = {
                    "chunk_count":    chunk_count,
                    "organization_id": organization_id,
                },
            )
            logger.info(
                "SupabaseIndexer | doc=%s COMPLETED chunks=%d",
                document_id, chunk_count,
            )
        except Exception as exc:
            raise IndexingError(
                f"Supabase completion update failed for doc={document_id}: {exc}"
            ) from exc

    def fail(
        self,
        document_id: str,
        job_id:      str,
        error:       str,
    ) -> None:
        """Record an indexing failure — best effort, never raises."""
        try:
            self._db.update_processing_status(document_id, ProcessingStatus.FAILED)
            self._db.update_job(
                job_id,
                stage         = "indexing",
                status        = "failed",
                error_message = error[:500],  # Supabase text column limit guard
            )
            self._db.write_audit_log(
                document_id = document_id,
                action      = "indexing_failed",
                actor       = "system",
                extra       = {"error": error[:500]},
            )
        except Exception as inner:
            # Failure to record failure must not mask the original error
            logger.error(
                "SupabaseIndexer.fail() itself failed for doc=%s: %s", document_id, inner
            )
