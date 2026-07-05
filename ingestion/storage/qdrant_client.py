from typing import Any, Optional

from qdrant_client import QdrantClient as _QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from ingestion.config import Settings, get_settings
from ingestion.exceptions import VectorStoreError
from ingestion.models import Chunk, ChunkType


# Map chunk type → collection name key
_CHUNK_TYPE_TO_COLLECTION_KEY = {
    ChunkType.TEXT:    "text",
    ChunkType.HEADING: "text",
    ChunkType.TABLE:   "table",
    ChunkType.IMAGE:   "image",
    ChunkType.FIGURE:  "image",
}


class QdrantVectorStore:
    """
    Typed wrapper for Qdrant vector store operations.

    Three collections isolate different modalities:
        hcip_text   — BGE-M3 text embeddings  (1024-dim)
        hcip_images — ColQwen image embeddings (128-dim)
        hcip_tables — Table representation embeddings (1024-dim)

    Every point carries the full ChunkMetadata as payload so the retriever
    can filter on org_id, knowledge_base_id, risk_level, etc.
    without a secondary DB lookup.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        cfg = settings or get_settings()
        self._client = _QdrantClient(
            host=cfg.qdrant_host,
            port=cfg.qdrant_port,
            api_key=cfg.qdrant_api_key or None,
        )
        self._collections = {
            "text":  cfg.qdrant_text_collection,
            "image": cfg.qdrant_image_collection,
            "table": cfg.qdrant_table_collection,
        }
        self._vector_dim = cfg.embedding_vector_dim

    # ── Collection management ─────────────────────────────────────────────────

    def ensure_collections_exist(self) -> None:
        """Create all three collections if they don't already exist."""
        for name in self._collections.values():
            if not self._client.collection_exists(name):
                self._client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(
                        size=self._vector_dim,
                        distance=Distance.COSINE,
                    ),
                )

    def collection_for(self, chunk_type: ChunkType) -> str:
        """Return the collection name for a given chunk type."""
        key = _CHUNK_TYPE_TO_COLLECTION_KEY.get(chunk_type, "text")
        return self._collections[key]

    # ── Write ─────────────────────────────────────────────────────────────────

    def upsert_chunks(self, chunks: list[Chunk]) -> None:
        """
        Batch-upsert chunks into their respective collections.
        Skips any chunk that has not been embedded yet.
        Groups by collection for a single network round-trip per collection.
        """
        grouped: dict[str, list[PointStruct]] = {name: [] for name in self._collections.values()}

        for chunk in chunks:
            if not chunk.is_embedded:
                continue
            collection = self.collection_for(chunk.chunk_type)
            grouped[collection].append(
                PointStruct(
                    id=chunk.chunk_id,
                    vector=chunk.embedding,
                    payload=chunk.to_qdrant_payload(),
                )
            )

        try:
            for collection, points in grouped.items():
                if points:
                    self._client.upsert(collection_name=collection, points=points)
        except Exception as exc:
            raise VectorStoreError(f"upsert_chunks failed: {exc}") from exc

    # ── Read ──────────────────────────────────────────────────────────────────

    def search(
        self,
        query_vector: list[float],
        organization_id: str,
        knowledge_base_id: str,
        collection: Optional[str] = None,
        limit: int = 10,
        role_filter: Optional[str] = None,
        risk_levels: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """
        Similarity search with mandatory org + KB + approval filters.
        Only APPROVED chunks are ever returned (governance rule enforced here).
        """
        must_conditions = [
            FieldCondition(key="organization_id",   match=MatchValue(value=organization_id)),
            FieldCondition(key="knowledge_base_id", match=MatchValue(value=knowledge_base_id)),
            FieldCondition(key="approval_status",   match=MatchValue(value="approved")),
        ]
        if role_filter:
            must_conditions.append(
                FieldCondition(key="roles", match=MatchValue(value=role_filter))
            )
        if risk_levels:
            # Include only chunks at or below the requested risk level
            must_conditions.append(
                FieldCondition(key="risk_level", match=MatchValue(any=risk_levels))
            )

        target = collection or self._collections["text"]
        try:
            response = self._client.query_points(
                collection_name=target,
                query=query_vector,
                query_filter=Filter(must=must_conditions),
                limit=limit,
                with_payload=True,
            )
            results = response.points
            return [{"score": r.score, **r.payload} for r in results]
        except Exception as exc:
            raise VectorStoreError(f"search failed [{target}]: {exc}") from exc

    # ── Delete ────────────────────────────────────────────────────────────────

    def delete_by_document(self, document_id: str) -> None:
        """Remove all vectors belonging to a document (used during re-indexing)."""
        doc_filter = Filter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
        )
        try:
            for collection in self._collections.values():
                self._client.delete(
                    collection_name=collection,
                    points_selector=doc_filter,
                )
        except Exception as exc:
            raise VectorStoreError(
                f"delete_by_document({document_id}) failed: {exc}"
            ) from exc

    def update_document_approval(self, document_id: str, approval_status: str) -> None:
        """
        Update the approval_status payload field on every chunk for a document.
        Called by GovernanceService when a document is APPROVED or ARCHIVED.
        Running across all three collections ensures no stale payload remains.
        """
        doc_filter = Filter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
        )
        try:
            for collection in self._collections.values():
                self._client.set_payload(
                    collection_name=collection,
                    payload={"approval_status": approval_status},
                    points=doc_filter,
                )
        except Exception as exc:
            raise VectorStoreError(
                f"update_document_approval({document_id}, {approval_status}) failed: {exc}"
            ) from exc

    def delete_by_version(self, document_id: str, version: str) -> None:
        """Remove vectors for a specific document version only."""
        version_filter = Filter(must=[
            FieldCondition(key="document_id",      match=MatchValue(value=document_id)),
            FieldCondition(key="document_version", match=MatchValue(value=version)),
        ])
        try:
            for collection in self._collections.values():
                self._client.delete(
                    collection_name=collection,
                    points_selector=version_filter,
                )
        except Exception as exc:
            raise VectorStoreError(
                f"delete_by_version({document_id}, {version}) failed: {exc}"
            ) from exc
