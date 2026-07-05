from __future__ import annotations

import logging
from typing import Optional
from uuid import uuid4

from ingestion.config import Settings, get_settings
from ingestion.exceptions import UploadError, VirusScanError
from ingestion.models import (
    Document,
    DocumentVersion,
    FileType,
    GovernanceState,
    ProcessingStatus,
)
from ingestion.storage import S3Storage, SupabaseClient

from .file_validator import FileValidator
from .virus_scanner import BaseVirusScanner, StubVirusScanner

logger = logging.getLogger(__name__)


# MIME type map kept at module level — single source of truth
_MIME_TYPES: dict[FileType, str] = {
    FileType.PDF:  "application/pdf",
    FileType.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    FileType.PPTX: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    FileType.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    FileType.CSV:  "text/csv",
    FileType.TXT:  "text/plain",
    FileType.PNG:  "image/png",
    FileType.JPG:  "image/jpeg",
    FileType.JPEG: "image/jpeg",
    FileType.TIFF: "image/tiff",
    FileType.JSON: "application/json",
    FileType.XML:  "application/xml",
    FileType.FHIR: "application/fhir+json",
}


class UploadService:
    """
    Entry point for all document uploads.

    Responsibilities (in order):
        1. Validate file (extension, size, magic bytes)
        2. Virus scan
        3. Upload raw bytes to S3
        4. Persist Document record to Supabase
        5. Persist DocumentVersion record (v1 for new, vN for re-upload)
        6. Create IngestionJob record
        7. Write audit log

    Returns (Document, job_id) — the job_id is used by the caller to
    dispatch the next pipeline stage (Classification) via Celery.
    """

    def __init__(
        self,
        s3:        S3Storage,
        db:        SupabaseClient,
        validator: Optional[FileValidator]     = None,
        scanner:   Optional[BaseVirusScanner]  = None,
        settings:  Optional[Settings]          = None,
    ) -> None:
        self._s3        = s3
        self._db        = db
        self._validator = validator or FileValidator(settings)
        self._scanner   = scanner   or StubVirusScanner()

    # ── Public API ────────────────────────────────────────────────────────────

    def upload_document(
        self,
        file_bytes:        bytes,
        filename:          str,
        organization_id:   str,
        department_id:     str,
        knowledge_base_id: str,
        uploaded_by:       str,
    ) -> tuple[Document, str]:
        """
        Full upload flow for a brand-new document.
        Returns (Document, job_id).
        """
        file_type = self._run_pre_upload_checks(file_bytes, filename)
        document_id = str(uuid4())

        s3_key = self._upload_to_s3(
            file_bytes, filename, organization_id, document_id, file_type
        )

        document = self._persist_new_document(
            document_id, filename, file_type, s3_key,
            organization_id, department_id, knowledge_base_id,
            uploaded_by, len(file_bytes),
        )

        self._db.create_version(DocumentVersion(
            document_id=document_id,
            version_number=1,
            s3_key=s3_key,
            is_active=True,
            created_by=uploaded_by,
            change_summary="Initial upload",
        ))

        job_id = self._db.create_job(document_id, organization_id)

        self._db.write_audit_log(
            document_id=document_id,
            action="document_uploaded",
            actor=uploaded_by,
            extra={"filename": filename, "file_type": file_type.value,
                   "size_bytes": len(file_bytes)},
        )

        logger.info(
            "Document uploaded: doc_id=%s org=%s filename=%s job_id=%s",
            document_id, organization_id, filename, job_id,
        )
        return document, job_id

    def upload_new_version(
        self,
        file_bytes:    bytes,
        filename:      str,
        document_id:   str,
        uploaded_by:   str,
        change_summary: str = "",
    ) -> tuple[Document, str]:
        """
        Upload a revised version of an existing document.
        Increments version_number, deactivates all previous versions,
        and marks the document as PENDING for incremental re-processing.
        """
        existing = self._db.get_document(document_id)
        if existing is None:
            raise UploadError(f"Document '{document_id}' not found")

        file_type = self._run_pre_upload_checks(file_bytes, filename)

        next_version = existing.version_number + 1
        s3_key = self._s3.version_key(
            existing.organization_id, document_id, next_version, filename
        )
        self._s3.upload_bytes(file_bytes, s3_key, _MIME_TYPES.get(file_type, "application/octet-stream"))

        self._db.create_version(DocumentVersion(
            document_id=document_id,
            version_number=next_version,
            s3_key=s3_key,
            is_active=True,
            created_by=uploaded_by,
            change_summary=change_summary or f"Version {next_version} upload",
        ))

        self._db.update_processing_status(document_id, ProcessingStatus.PENDING)

        job_id = self._db.create_job(document_id, existing.organization_id)

        self._db.write_audit_log(
            document_id=document_id,
            action="new_version_uploaded",
            actor=uploaded_by,
            extra={"version": next_version, "filename": filename,
                   "change_summary": change_summary},
        )

        # Return the refreshed document with updated version_number
        existing.version_number = next_version
        existing.s3_key = s3_key
        existing.processing_status = ProcessingStatus.PENDING

        logger.info(
            "New version uploaded: doc_id=%s version=%s job_id=%s",
            document_id, next_version, job_id,
        )
        return existing, job_id

    def generate_presigned_url(
        self,
        organization_id: str,
        filename:        str,
        expires_in:      int = 3_600,
    ) -> dict:
        """
        Generate a presigned S3 PUT URL for direct browser → S3 upload.
        The caller uses the returned s3_key when registering the document afterwards.
        """
        document_id = str(uuid4())
        s3_key = self._s3.raw_key(organization_id, document_id, filename)
        url = self._s3.presigned_upload_url(s3_key, expires_in)
        return {
            "upload_url":  url,
            "s3_key":      s3_key,
            "document_id": document_id,
            "expires_in":  expires_in,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _run_pre_upload_checks(self, content: bytes, filename: str) -> FileType:
        """Validate then virus-scan. Returns FileType on success, raises on failure."""
        result = self._validator.validate(filename, content)
        if not result.is_valid:
            raise UploadError(
                f"File validation failed for '{filename}': {result.error_summary}"
            )

        scan = self._scanner.scan(content, filename)
        if not scan.is_clean:
            raise VirusScanError(
                f"Malware detected in '{filename}' [{scan.scanner}]: {scan.threat_name}"
            )

        return result.file_type  # type: ignore[return-value]  # guaranteed non-None after is_valid

    def _upload_to_s3(
        self,
        content:         bytes,
        filename:        str,
        organization_id: str,
        document_id:     str,
        file_type:       FileType,
    ) -> str:
        """Upload bytes to S3 and return the s3_key."""
        s3_key = self._s3.raw_key(organization_id, document_id, filename)
        mime   = _MIME_TYPES.get(file_type, "application/octet-stream")
        self._s3.upload_bytes(content, s3_key, mime)
        return s3_key

    def _persist_new_document(
        self,
        document_id:       str,
        filename:          str,
        file_type:         FileType,
        s3_key:            str,
        organization_id:   str,
        department_id:     str,
        knowledge_base_id: str,
        uploaded_by:       str,
        file_size_bytes:   int,
    ) -> Document:
        """Create the Document row in Supabase and return it."""
        document = Document(
            document_id=document_id,
            organization_id=organization_id,
            department_id=department_id,
            knowledge_base_id=knowledge_base_id,
            file_name=filename,
            file_type=file_type,
            s3_key=s3_key,
            file_size_bytes=file_size_bytes,
            uploaded_by=uploaded_by,
            governance_state=GovernanceState.DRAFT,
            processing_status=ProcessingStatus.PENDING,
        )
        return self._db.create_document(document)
