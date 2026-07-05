"""
IngestionPipeline — single entry point for the HCIP ingestion system.

External callers (FastAPI routes, SDK, CLI) interact only with this class.
All implementation details (parsers, embedders, chunkers, Celery, storage)
are hidden behind the façade.
"""
from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel

from ingestion.config import Settings, get_settings
from ingestion.exceptions import IngestionError
from ingestion.models import Document
from ingestion.services.governance import GovernanceService
from ingestion.services.upload import UploadService
from ingestion.services.upload.file_validator import FileValidator
from ingestion.services.upload.virus_scanner import StubVirusScanner
from ingestion.storage.s3_storage import S3Storage
from ingestion.storage.supabase_client import SupabaseClient
from ingestion.workers.tasks import launch_pipeline

logger = logging.getLogger(__name__)


# ── Response models (FastAPI-serialisable) ────────────────────────────────────

class IngestionResult(BaseModel):
    """Returned after a successful upload + pipeline launch."""
    document_id:       str
    job_id:            str
    organization_id:   str
    file_name:         str
    file_type:         str
    version_number:    int
    processing_status: str
    message:           str = ""


class PipelineStatus(BaseModel):
    """Current state of a document in the pipeline."""
    document_id:       str
    organization_id:   str
    file_name:         str
    file_type:         str
    processing_status: str
    governance_state:  str
    version_number:    int
    is_searchable:     bool
    created_at:        Optional[str] = None
    updated_at:        Optional[str] = None


# ── Factory helper ────────────────────────────────────────────────────────────

def _build_upload_service(cfg: Settings) -> UploadService:
    return UploadService(
        s3        = S3Storage(settings=cfg),
        db        = SupabaseClient(settings=cfg),
        validator = FileValidator(settings=cfg),
        scanner   = StubVirusScanner(),
        settings  = cfg,
    )


# ── Main orchestrator ─────────────────────────────────────────────────────────

class IngestionPipeline:
    """
    Façade for the complete HCIP ingestion pipeline.

    Responsibilities:
        • Upload validation, S3 storage, Supabase record creation  (UploadService)
        • Async pipeline dispatch via Celery chain                  (launch_pipeline)
        • Governance transitions (review / approve / reject / archive)

    Usage:
        pipeline = IngestionPipeline()

        # Upload + kick off async pipeline
        result = pipeline.ingest(
            file_bytes        = pdf_bytes,
            filename          = "clinical_guideline.pdf",
            organization_id   = "org-123",
            department_id     = "dept-456",
            knowledge_base_id = "kb-789",
            uploaded_by       = "user@hospital.org",
        )

        # Check status
        status = pipeline.get_status(result.document_id)

        # Governance
        pipeline.request_review(result.document_id, actor="reviewer@hospital.org")
        pipeline.approve(result.document_id, actor="cmo@hospital.org", reason="Reviewed OK")
    """

    def __init__(
        self,
        upload_service:     Optional[UploadService]     = None,
        governance_service: Optional[GovernanceService] = None,
        settings:           Optional[Settings]           = None,
    ) -> None:
        self._cfg        = settings or get_settings()
        self._upload     = upload_service     or _build_upload_service(self._cfg)
        self._governance = governance_service or GovernanceService()
        self._db         = SupabaseClient(settings=self._cfg)

    # ── Upload + launch ───────────────────────────────────────────────────────

    def ingest(
        self,
        file_bytes:        bytes,
        filename:          str,
        organization_id:   str,
        department_id:     str,
        knowledge_base_id: str,
        uploaded_by:       str,
        auto_launch:       bool = True,
    ) -> IngestionResult:
        """
        Validate, store and begin async processing of a new document.

        Steps:
            1. FileValidator (extension, size, magic bytes, virus scan)
            2. S3 upload  →  raw/{org}/{doc_id}/filename
            3. Supabase   →  Document + DocumentVersion v1 + IngestionJob
            4. Celery     →  launch parse → enrich → chunk → embed → graph → index chain

        Raises UploadError on validation or storage failures.
        """
        document, job_id = self._upload.upload_document(
            file_bytes        = file_bytes,
            filename          = filename,
            organization_id   = organization_id,
            department_id     = department_id,
            knowledge_base_id = knowledge_base_id,
            uploaded_by       = uploaded_by,
        )

        if auto_launch:
            launch_pipeline(
                document_id     = document.document_id,
                job_id          = job_id,
                organization_id = organization_id,
                is_reindex      = False,
            )

        logger.info(
            "IngestionPipeline.ingest | doc=%s job=%s org=%s launched=%s",
            document.document_id, job_id, organization_id, auto_launch,
        )
        return IngestionResult(
            document_id       = document.document_id,
            job_id            = job_id,
            organization_id   = organization_id,
            file_name         = document.file_name,
            file_type         = document.file_type.value,
            version_number    = document.version_number,
            processing_status = document.processing_status.value,
            message           = "Pipeline launched" if auto_launch else "Uploaded (pipeline not launched)",
        )

    def ingest_new_version(
        self,
        document_id:    str,
        file_bytes:     bytes,
        filename:       str,
        uploaded_by:    str,
        change_summary: str  = "",
        auto_launch:    bool = True,
    ) -> IngestionResult:
        """
        Upload a revised version of an existing document and re-index it.
        The existing active version's vectors are replaced in Qdrant.
        """
        document, job_id = self._upload.upload_new_version(
            file_bytes     = file_bytes,
            filename       = filename,
            document_id    = document_id,
            uploaded_by    = uploaded_by,
            change_summary = change_summary,
        )

        if auto_launch:
            launch_pipeline(
                document_id     = document_id,
                job_id          = job_id,
                organization_id = document.organization_id,
                is_reindex      = True,
            )

        logger.info(
            "IngestionPipeline.ingest_new_version | doc=%s v%d job=%s launched=%s",
            document_id, document.version_number, job_id, auto_launch,
        )
        return IngestionResult(
            document_id       = document_id,
            job_id            = job_id,
            organization_id   = document.organization_id,
            file_name         = document.file_name,
            file_type         = document.file_type.value,
            version_number    = document.version_number,
            processing_status = document.processing_status.value,
            message           = "Re-index pipeline launched" if auto_launch else "Version uploaded",
        )

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self, document_id: str) -> PipelineStatus:
        """
        Return the current processing and governance state of a document.
        Raises ValueError when the document does not exist.
        """
        doc = self._db.get_document(document_id)
        if doc is None:
            raise ValueError(f"Document not found: {document_id}")
        return PipelineStatus(
            document_id       = doc.document_id,
            organization_id   = doc.organization_id,
            file_name         = doc.file_name,
            file_type         = doc.file_type.value,
            processing_status = doc.processing_status.value,
            governance_state  = doc.governance_state.value,
            version_number    = doc.version_number,
            is_searchable     = doc.is_searchable,
            created_at        = doc.created_at.isoformat() if doc.created_at  else None,
            updated_at        = doc.updated_at.isoformat() if doc.updated_at  else None,
        )

    def list_documents(
        self,
        organization_id: str,
        governance_state: Optional[str] = None,
        limit:  int = 50,
        offset: int = 0,
    ) -> list[PipelineStatus]:
        """List documents for an organisation with optional governance state filter."""
        from ingestion.models import GovernanceState
        gs_filter = GovernanceState(governance_state) if governance_state else None
        docs      = self._db.list_documents(organization_id, gs_filter, limit, offset)
        return [
            PipelineStatus(
                document_id       = d.document_id,
                organization_id   = d.organization_id,
                file_name         = d.file_name,
                file_type         = d.file_type.value,
                processing_status = d.processing_status.value,
                governance_state  = d.governance_state.value,
                version_number    = d.version_number,
                is_searchable     = d.is_searchable,
                created_at        = d.created_at.isoformat() if d.created_at else None,
                updated_at        = d.updated_at.isoformat() if d.updated_at else None,
            )
            for d in docs
        ]

    # ── Governance ────────────────────────────────────────────────────────────

    def request_review(self, document_id: str, actor: str, reason: str = "") -> None:
        """DRAFT → PENDING_REVIEW. Raises GovernanceError on invalid transition."""
        self._governance.request_review(document_id, actor, reason)

    def approve(self, document_id: str, actor: str, reason: str = "") -> None:
        """
        PENDING_REVIEW → APPROVED.
        Immediately updates Qdrant payload so chunks become searchable.
        """
        self._governance.approve(document_id, actor, reason)

    def reject(self, document_id: str, actor: str, reason: str = "") -> None:
        """PENDING_REVIEW → DRAFT. Returns document to author for revision."""
        self._governance.reject(document_id, actor, reason)

    def archive(self, document_id: str, actor: str, reason: str = "") -> None:
        """
        APPROVED → ARCHIVED.
        Hides chunks from all search queries via Qdrant payload update.
        """
        self._governance.archive(document_id, actor, reason)
