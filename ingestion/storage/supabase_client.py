from datetime import datetime
from typing import Optional
from uuid import uuid4

from supabase import Client, create_client

from ingestion.config import Settings, get_settings
from ingestion.exceptions import DatabaseError
from ingestion.models import Document, DocumentVersion, GovernanceState, ProcessingStatus


class SupabaseClient:
    """
    Typed wrapper for all Supabase (PostgreSQL) operations.

    Tables managed:
        documents          — primary document record
        document_versions  — immutable version history
        ingestion_jobs     — per-document pipeline job tracking
        audit_logs         — governance state-change trail
    """

    _DOCUMENTS = "documents"
    _VERSIONS  = "document_versions"
    _JOBS      = "ingestion_jobs"
    _AUDIT     = "audit_logs"

    def __init__(self, settings: Optional[Settings] = None) -> None:
        cfg = settings or get_settings()
        self._db: Client = create_client(cfg.supabase_url, cfg.supabase_service_key)

    # ── Documents ──────────────────────────────────────────────────────────────

    def create_document(self, document: Document) -> Document:
        try:
            result = (
                self._db.table(self._DOCUMENTS)
                .insert(document.model_dump(mode="json"))
                .execute()
            )
            return Document(**result.data[0])
        except Exception as exc:
            raise DatabaseError(f"create_document failed: {exc}") from exc

    def get_document(self, document_id: str) -> Optional[Document]:
        try:
            result = (
                self._db.table(self._DOCUMENTS)
                .select("*")
                .eq("document_id", document_id)
                .maybe_single()
                .execute()
            )
            return Document(**result.data) if result.data else None
        except Exception as exc:
            raise DatabaseError(f"get_document({document_id}) failed: {exc}") from exc

    def update_processing_status(
        self, document_id: str, status: ProcessingStatus
    ) -> None:
        try:
            self._db.table(self._DOCUMENTS).update({
                "processing_status": status.value,
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("document_id", document_id).execute()
        except Exception as exc:
            raise DatabaseError(
                f"update_processing_status({document_id}) failed: {exc}"
            ) from exc

    def update_governance_state(
        self,
        document_id: str,
        new_state: GovernanceState,
        actor: str,
        previous_state: Optional[GovernanceState] = None,
    ) -> None:
        try:
            self._db.table(self._DOCUMENTS).update({
                "governance_state": new_state.value,
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("document_id", document_id).execute()

            self._write_audit_log(
                document_id=document_id,
                action="governance_transition",
                actor=actor,
                from_state=previous_state.value if previous_state else None,
                to_state=new_state.value,
            )
        except Exception as exc:
            raise DatabaseError(
                f"update_governance_state({document_id}) failed: {exc}"
            ) from exc

    def list_documents(
        self,
        organization_id: str,
        governance_state: Optional[GovernanceState] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Document]:
        try:
            query = (
                self._db.table(self._DOCUMENTS)
                .select("*")
                .eq("organization_id", organization_id)
                .range(offset, offset + limit - 1)
            )
            if governance_state:
                query = query.eq("governance_state", governance_state.value)
            result = query.execute()
            return [Document(**row) for row in result.data]
        except Exception as exc:
            raise DatabaseError(f"list_documents({organization_id}) failed: {exc}") from exc

    # ── Document versions ──────────────────────────────────────────────────────

    def create_version(self, version: DocumentVersion) -> DocumentVersion:
        """
        Deactivates all existing versions for the document before inserting
        the new one — only one active version at a time.
        """
        try:
            self._db.table(self._VERSIONS).update({"is_active": False}).eq(
                "document_id", version.document_id
            ).execute()

            result = (
                self._db.table(self._VERSIONS)
                .insert(version.model_dump(mode="json"))
                .execute()
            )
            return DocumentVersion(**result.data[0])
        except Exception as exc:
            raise DatabaseError(f"create_version failed: {exc}") from exc

    def get_active_version(self, document_id: str) -> Optional[DocumentVersion]:
        try:
            result = (
                self._db.table(self._VERSIONS)
                .select("*")
                .eq("document_id", document_id)
                .eq("is_active", True)
                .maybe_single()
                .execute()
            )
            return DocumentVersion(**result.data) if result.data else None
        except Exception as exc:
            raise DatabaseError(
                f"get_active_version({document_id}) failed: {exc}"
            ) from exc

    def list_versions(self, document_id: str) -> list[DocumentVersion]:
        try:
            result = (
                self._db.table(self._VERSIONS)
                .select("*")
                .eq("document_id", document_id)
                .order("version_number", desc=True)
                .execute()
            )
            return [DocumentVersion(**row) for row in result.data]
        except Exception as exc:
            raise DatabaseError(f"list_versions({document_id}) failed: {exc}") from exc

    # ── Ingestion jobs ─────────────────────────────────────────────────────────

    def create_job(self, document_id: str, organization_id: str) -> str:
        """Create a new ingestion job record and return its job_id."""
        job_id = str(uuid4())
        try:
            self._db.table(self._JOBS).insert({
                "job_id":          job_id,
                "document_id":     document_id,
                "organization_id": organization_id,
                "stage":           "upload",
                "status":          "pending",
                "started_at":      datetime.utcnow().isoformat(),
                "retry_count":     0,
            }).execute()
            return job_id
        except Exception as exc:
            raise DatabaseError(f"create_job({document_id}) failed: {exc}") from exc

    def update_job(
        self,
        job_id: str,
        stage: str,
        status: str,
        error_message: Optional[str] = None,
        increment_retry: bool = False,
    ) -> None:
        updates: dict = {"stage": stage, "status": status}
        if error_message:
            updates["error_message"] = error_message
        if status in {"completed", "failed", "dead_letter"}:
            updates["completed_at"] = datetime.utcnow().isoformat()
        try:
            self._db.table(self._JOBS).update(updates).eq("job_id", job_id).execute()
            if increment_retry:
                self._db.rpc("increment_job_retry", {"p_job_id": job_id}).execute()
        except Exception as exc:
            raise DatabaseError(f"update_job({job_id}) failed: {exc}") from exc

    # ── Audit logs ─────────────────────────────────────────────────────────────

    def _write_audit_log(
        self,
        document_id: str,
        action: str,
        actor: str,
        from_state: Optional[str] = None,
        to_state: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> None:
        """Internal helper — always called inside an existing try/except block."""
        self._db.table(self._AUDIT).insert({
            "log_id":      str(uuid4()),
            "document_id": document_id,
            "action":      action,
            "actor":       actor,
            "from_state":  from_state,
            "to_state":    to_state,
            "metadata":    extra or {},
            "created_at":  datetime.utcnow().isoformat(),
        }).execute()

    def write_audit_log(
        self,
        document_id: str,
        action: str,
        actor: str,
        from_state: Optional[str] = None,
        to_state: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> None:
        """Public audit log writer for pipeline events outside governance transitions."""
        try:
            self._write_audit_log(document_id, action, actor, from_state, to_state, extra)
        except Exception as exc:
            raise DatabaseError(f"write_audit_log({document_id}) failed: {exc}") from exc
