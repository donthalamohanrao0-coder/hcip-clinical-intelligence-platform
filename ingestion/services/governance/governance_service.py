from __future__ import annotations

import logging
from typing import Optional

from ingestion.exceptions import GovernanceError
from ingestion.models import Document, GovernanceState
from ingestion.storage.qdrant_client import QdrantVectorStore
from ingestion.storage.supabase_client import SupabaseClient

logger = logging.getLogger(__name__)

# Qdrant approval_status values that match each governance state
_QDRANT_STATUS: dict[GovernanceState, str] = {
    GovernanceState.APPROVED: "approved",
    GovernanceState.ARCHIVED: "archived",
}


class GovernanceService:
    """
    Enforces the document governance state machine and maintains audit trail.

    State machine (from GovernanceState.can_transition_to):
        DRAFT          → PENDING_REVIEW   (request_review)
        PENDING_REVIEW → APPROVED         (approve)
        PENDING_REVIEW → DRAFT            (reject)
        APPROVED       → ARCHIVED         (archive)

    Side effects per transition:
        → APPROVED   Qdrant payload updated: approval_status = "approved"
                     Chunks become visible to search queries.
        → ARCHIVED   Qdrant payload updated: approval_status = "archived"
                     Chunks are hidden from all search queries.
        → DRAFT      No Qdrant change (chunks were never approved).
        All states:  Supabase governance_state + audit_logs updated atomically.

    All public methods write a reason to the audit log when provided.
    Transitions that violate the state machine raise GovernanceError immediately
    without touching the database.
    """

    def __init__(
        self,
        supabase: Optional[SupabaseClient]    = None,
        qdrant:   Optional[QdrantVectorStore] = None,
    ) -> None:
        self._supabase = supabase or SupabaseClient()
        self._qdrant   = qdrant   or QdrantVectorStore()

    # ── Public transition API ─────────────────────────────────────────────────

    def request_review(
        self,
        document_id: str,
        actor:       str,
        reason:      str = "",
    ) -> None:
        """Move document from DRAFT → PENDING_REVIEW."""
        doc = self._fetch_and_validate(document_id, GovernanceState.PENDING_REVIEW)
        self._supabase.update_governance_state(
            document_id    = document_id,
            new_state      = GovernanceState.PENDING_REVIEW,
            actor          = actor,
            previous_state = doc.governance_state,
        )
        self._maybe_log_reason(document_id, "review_requested", actor, reason)
        logger.info("Governance | doc=%s DRAFT → PENDING_REVIEW actor=%s", document_id, actor)

    def approve(
        self,
        document_id: str,
        actor:       str,
        reason:      str = "",
    ) -> None:
        """
        Move document from PENDING_REVIEW → APPROVED.
        Updates Qdrant payload so chunks become searchable.
        """
        doc = self._fetch_and_validate(document_id, GovernanceState.APPROVED)
        self._supabase.update_governance_state(
            document_id    = document_id,
            new_state      = GovernanceState.APPROVED,
            actor          = actor,
            previous_state = doc.governance_state,
        )
        self._qdrant.update_document_approval(document_id, "approved")
        self._maybe_log_reason(document_id, "approved", actor, reason)
        logger.info("Governance | doc=%s PENDING_REVIEW → APPROVED actor=%s", document_id, actor)

    def reject(
        self,
        document_id: str,
        actor:       str,
        reason:      str = "",
    ) -> None:
        """
        Move document from PENDING_REVIEW → DRAFT.
        No Qdrant change needed — chunks were never approved.
        """
        doc = self._fetch_and_validate(document_id, GovernanceState.DRAFT)
        self._supabase.update_governance_state(
            document_id    = document_id,
            new_state      = GovernanceState.DRAFT,
            actor          = actor,
            previous_state = doc.governance_state,
        )
        self._maybe_log_reason(document_id, "rejected", actor, reason)
        logger.info("Governance | doc=%s PENDING_REVIEW → DRAFT actor=%s", document_id, actor)

    def archive(
        self,
        document_id: str,
        actor:       str,
        reason:      str = "",
    ) -> None:
        """
        Move document from APPROVED → ARCHIVED.
        Updates Qdrant payload to hide chunks from all search queries.
        """
        doc = self._fetch_and_validate(document_id, GovernanceState.ARCHIVED)
        self._supabase.update_governance_state(
            document_id    = document_id,
            new_state      = GovernanceState.ARCHIVED,
            actor          = actor,
            previous_state = doc.governance_state,
        )
        self._qdrant.update_document_approval(document_id, "archived")
        self._maybe_log_reason(document_id, "archived", actor, reason)
        logger.info("Governance | doc=%s APPROVED → ARCHIVED actor=%s", document_id, actor)

    def get_state(self, document_id: str) -> GovernanceState:
        """Return the current governance state of a document."""
        doc = self._supabase.get_document(document_id)
        if doc is None:
            raise GovernanceError(f"Document not found: {document_id}")
        return doc.governance_state

    # ── Private helpers ───────────────────────────────────────────────────────

    def _fetch_and_validate(
        self,
        document_id: str,
        target:      GovernanceState,
    ) -> Document:
        """
        Fetch the document and check that the target transition is allowed.
        Raises GovernanceError before touching any storage if invalid.
        """
        doc = self._supabase.get_document(document_id)
        if doc is None:
            raise GovernanceError(f"Document not found: {document_id}")

        if not doc.governance_state.can_transition_to(target):
            raise GovernanceError(
                f"Invalid transition for doc={document_id}: "
                f"{doc.governance_state.value} → {target.value}"
            )
        return doc

    def _maybe_log_reason(
        self,
        document_id: str,
        action:      str,
        actor:       str,
        reason:      str,
    ) -> None:
        """Write an extra audit entry when the caller provides a reason."""
        if reason:
            self._supabase.write_audit_log(
                document_id = document_id,
                action      = action,
                actor       = actor,
                extra       = {"reason": reason},
            )
