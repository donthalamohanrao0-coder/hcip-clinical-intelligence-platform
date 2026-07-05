from __future__ import annotations

import logging
from typing import Optional

from ingestion.exceptions import IndexingError
from ingestion.models import Chunk
from ingestion.storage.qdrant_client import QdrantVectorStore

logger = logging.getLogger(__name__)


class QdrantIndexer:
    """
    Handles vector store indexing for document chunks.

    First-time indexing:
        index(chunks) — upsert all embedded chunks into their collections.

    Re-indexing (new document version):
        reindex(chunks, document_id) — delete ALL existing vectors for the
        document first, then upsert. The delete step is safe because the
        governance gate (approval_status) prevents deleted vectors from
        being served while the re-index is in progress.

    Chunks without an embedding (is_embedded=False) are silently skipped.
    A document with zero embeddable chunks raises IndexingError.
    """

    def __init__(self, qdrant: Optional[QdrantVectorStore] = None) -> None:
        self._qdrant = qdrant or QdrantVectorStore()

    def index(self, chunks: list[Chunk]) -> int:
        """
        Upsert embedded chunks into Qdrant.
        Returns the count of chunks that were successfully indexed.
        """
        embedded = [c for c in chunks if c.is_embedded]
        if not embedded:
            raise IndexingError(
                "No embedded chunks available to index. "
                "Run EmbeddingPipeline before IndexingService."
            )
        try:
            self._qdrant.upsert_chunks(embedded)
            logger.info(
                "QdrantIndexer | indexed=%d skipped_no_embedding=%d",
                len(embedded), len(chunks) - len(embedded),
            )
            return len(embedded)
        except Exception as exc:
            raise IndexingError(f"Qdrant upsert failed: {exc}") from exc

    def reindex(self, chunks: list[Chunk], document_id: str) -> int:
        """
        Delete all existing vectors for `document_id`, then index the new chunks.
        Used when a new document version supersedes the previous one.
        """
        try:
            self._qdrant.delete_by_document(document_id)
            logger.info("QdrantIndexer | cleared old vectors for doc=%s", document_id)
        except Exception as exc:
            raise IndexingError(
                f"Failed to clear old vectors for doc={document_id}: {exc}"
            ) from exc

        return self.index(chunks)
