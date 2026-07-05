"""
Celery tasks for the HCIP ingestion pipeline.

Task chain (triggered after UploadService completes):
    parse_and_classify_task
        → enrich_task
            → chunk_task
                → embed_task
                    → graph_task
                        → validate_and_index_task

Each task:
  • receives a `ctx` dict from the previous task
  • updates the job stage/status in Supabase at start and end
  • returns an enriched `ctx` dict consumed by the next task
  • retries up to 3× with exponential back-off on any exception
  • routes to handle_dead_letter after exhausting retries

Large intermediate data (ParsedContent, chunks) is serialized as dicts
in the ctx dict and passed through the Celery/Redis broker.
"""
from __future__ import annotations

import logging
from typing import Any

from celery import chain, states
from celery.exceptions import MaxRetriesExceededError

from ingestion.config import get_settings
from ingestion.models import (
    Chunk,
    DocumentMetadata,
    DocumentType,
    FileType,
    ParsedContent,
    ProcessingStatus,
    QualityScores,
    RiskLevel,
)
from ingestion.services.chunking import ChunkingEngine
from ingestion.services.classification import DocumentClassifier
from ingestion.services.embedding import EmbeddingPipeline
from ingestion.services.governance import GovernanceService
from ingestion.services.graph import KnowledgeGraphService
from ingestion.services.indexing import IndexingService
from ingestion.services.metadata import MetadataEnrichmentService
from ingestion.services.parsing import get_parser
from ingestion.services.validation import ValidationPipeline
from ingestion.storage.redis_client import RedisCache
from ingestion.storage.s3_storage import S3Storage
from ingestion.storage.supabase_client import SupabaseClient

from .celery_app import celery_app

logger = logging.getLogger(__name__)

# ── Shared helpers ────────────────────────────────────────────────────────────

def _db() -> SupabaseClient:
    return SupabaseClient()


def _s3() -> S3Storage:
    return S3Storage()


def _cache() -> RedisCache:
    return RedisCache()


def _update_stage(job_id: str, stage: str, status: str, error: str = "") -> None:
    """Best-effort job status update — never raises."""
    try:
        _db().update_job(job_id, stage=stage, status=status,
                         error_message=error or None)
    except Exception as exc:
        logger.warning("Failed to update job=%s stage=%s: %s", job_id, stage, exc)


def _update_processing(document_id: str, status: ProcessingStatus) -> None:
    """Best-effort document status update — never raises."""
    try:
        _db().update_processing_status(document_id, status)
    except Exception as exc:
        logger.warning("Failed to update doc=%s status: %s", document_id, exc)


def _retry_countdown(retries: int) -> int:
    """Exponential back-off: 60s, 120s, 240s."""
    return 60 * (2 ** retries)


# ── Task 1 — Parse + Classify ─────────────────────────────────────────────────

@celery_app.task(bind=True, max_retries=3, name="ingestion.workers.tasks.parse_and_classify_task")
def parse_and_classify_task(self, ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Download the raw file from S3, parse it, and classify the document type.
    Combines parse + classify so the file is only downloaded once.
    """
    document_id = ctx["document_id"]
    job_id      = ctx["job_id"]
    org_id      = ctx["organization_id"]

    _update_stage(job_id, "parse", "in_progress")
    _update_processing(document_id, ProcessingStatus.PARSING)

    try:
        db  = _db()
        doc = db.get_document(document_id)
        if doc is None:
            raise ValueError(f"Document not found: {document_id}")

        file_type  = doc.file_type
        file_bytes = _s3().download_bytes(doc.s3_key)
        parser     = get_parser(file_type, is_scanned=False)
        content    = parser.parse(file_bytes, doc.file_name)

        # Classify using parsed text
        classifier = DocumentClassifier()
        doc_type   = classifier.classify(content, doc.file_name, file_type)

        # Persist doc_type on the document record
        db.update_processing_status(document_id, ProcessingStatus.CLASSIFYING)
        _update_stage(job_id, "classify", "completed")
        _update_stage(job_id, "parse",    "completed")

        logger.info("parse_and_classify | doc=%s type=%s", document_id, doc_type.value)
        return {
            **ctx,
            "doc_type":        doc_type.value,
            "file_type":       file_type.value,
            "file_name":       doc.file_name,
            "version":         str(doc.version_number),
            "parsed_content":  content.model_dump(mode="json"),
        }

    except Exception as exc:
        _update_stage(job_id, "parse", "failed", str(exc))
        try:
            raise self.retry(exc=exc, countdown=_retry_countdown(self.request.retries))
        except MaxRetriesExceededError:
            handle_dead_letter.delay({**ctx, "error": str(exc), "stage": "parse"})
            raise


# ── Task 2 — Metadata Enrichment ──────────────────────────────────────────────

@celery_app.task(bind=True, max_retries=3, name="ingestion.workers.tasks.enrich_task")
def enrich_task(self, ctx: dict[str, Any]) -> dict[str, Any]:
    """Extract medical entities, ontology codes, specialty, risk level."""
    document_id = ctx["document_id"]
    job_id      = ctx["job_id"]
    org_id      = ctx["organization_id"]

    _update_stage(job_id, "enrich", "in_progress")
    _update_processing(document_id, ProcessingStatus.ENRICHING)

    try:
        doc     = _db().get_document(document_id)
        cache   = _cache()
        content = ParsedContent.model_validate(ctx["parsed_content"])

        enricher = MetadataEnrichmentService(cache=cache)
        doc_metadata, risk_level = enricher.enrich(
            content           = content,
            document_id       = document_id,
            organization_id   = org_id,
            department_id     = doc.department_id if doc else "",
            knowledge_base_id = doc.knowledge_base_id if doc else "",
            doc_type          = DocumentType(ctx["doc_type"]),
            file_type         = FileType(ctx["file_type"]),
            source            = doc.s3_key if doc else "",
        )

        _update_stage(job_id, "enrich", "completed")
        logger.info(
            "enrich | doc=%s entities=%d risk=%s",
            document_id, doc_metadata.medical.entity_count, risk_level.value,
        )
        return {
            **ctx,
            "doc_metadata": doc_metadata.model_dump(mode="json"),
            "risk_level":   risk_level.value,
        }

    except Exception as exc:
        _update_stage(job_id, "enrich", "failed", str(exc))
        try:
            raise self.retry(exc=exc, countdown=_retry_countdown(self.request.retries))
        except MaxRetriesExceededError:
            handle_dead_letter.delay({**ctx, "error": str(exc), "stage": "enrich"})
            raise


# ── Task 3 — Chunking ─────────────────────────────────────────────────────────

@celery_app.task(bind=True, max_retries=3, name="ingestion.workers.tasks.chunk_task")
def chunk_task(self, ctx: dict[str, Any]) -> dict[str, Any]:
    """Split parsed content into retrievable chunks."""
    document_id = ctx["document_id"]
    job_id      = ctx["job_id"]

    _update_stage(job_id, "chunk", "in_progress")
    _update_processing(document_id, ProcessingStatus.CHUNKING)

    try:
        content      = ParsedContent.model_validate(ctx["parsed_content"])
        doc_metadata = DocumentMetadata.model_validate(ctx["doc_metadata"])
        risk_level   = RiskLevel(ctx["risk_level"])

        engine = ChunkingEngine()
        chunks = engine.chunk(
            content          = content,
            document_id      = document_id,
            document_version = ctx["version"],
            doc_metadata     = doc_metadata,
            file_type        = FileType(ctx["file_type"]),
            doc_type         = DocumentType(ctx["doc_type"]),
            risk_level       = risk_level,
        )

        _update_stage(job_id, "chunk", "completed")
        logger.info("chunk | doc=%s chunks=%d", document_id, len(chunks))
        return {
            **ctx,
            "chunks": [c.model_dump(mode="json") for c in chunks],
        }

    except Exception as exc:
        _update_stage(job_id, "chunk", "failed", str(exc))
        try:
            raise self.retry(exc=exc, countdown=_retry_countdown(self.request.retries))
        except MaxRetriesExceededError:
            handle_dead_letter.delay({**ctx, "error": str(exc), "stage": "chunk"})
            raise


# ── Task 4 — Embedding ────────────────────────────────────────────────────────

@celery_app.task(bind=True, max_retries=3, name="ingestion.workers.tasks.embed_task")
def embed_task(self, ctx: dict[str, Any]) -> dict[str, Any]:
    """Embed all chunks with BGE-M3 (text) and ColQwen (figures)."""
    document_id = ctx["document_id"]
    job_id      = ctx["job_id"]

    _update_stage(job_id, "embed", "in_progress")
    _update_processing(document_id, ProcessingStatus.EMBEDDING)

    try:
        chunks = [Chunk.model_validate(c) for c in ctx["chunks"]]
        cache  = _cache()
        s3     = _s3()

        pipeline = EmbeddingPipeline(cache=cache, s3=s3)
        chunks   = pipeline.embed(chunks)

        embedded_count = sum(1 for c in chunks if c.is_embedded)
        _update_stage(job_id, "embed", "completed")
        logger.info(
            "embed | doc=%s embedded=%d/%d",
            document_id, embedded_count, len(chunks),
        )
        return {
            **ctx,
            "chunks": [c.model_dump(mode="json") for c in chunks],
        }

    except Exception as exc:
        _update_stage(job_id, "embed", "failed", str(exc))
        try:
            raise self.retry(exc=exc, countdown=_retry_countdown(self.request.retries))
        except MaxRetriesExceededError:
            handle_dead_letter.delay({**ctx, "error": str(exc), "stage": "embed"})
            raise


# ── Task 5 — Knowledge Graph ──────────────────────────────────────────────────

@celery_app.task(bind=True, max_retries=2, name="ingestion.workers.tasks.graph_task")
def graph_task(self, ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Build Neo4j entity graph for the document.
    Graph failures are logged but do not block indexing — the pipeline
    continues even if Neo4j is unavailable (the graph is best-effort).
    """
    document_id = ctx["document_id"]
    job_id      = ctx["job_id"]
    org_id      = ctx["organization_id"]

    _update_stage(job_id, "graph", "in_progress")
    _update_processing(document_id, ProcessingStatus.GRAPHING)

    try:
        chunks       = [Chunk.model_validate(c) for c in ctx["chunks"]]
        doc_metadata = DocumentMetadata.model_validate(ctx["doc_metadata"])

        KnowledgeGraphService().index_document(
            document_id     = document_id,
            organization_id = org_id,
            doc_metadata    = doc_metadata,
            chunks          = chunks,
        )
        _update_stage(job_id, "graph", "completed")

    except Exception as exc:
        logger.warning(
            "graph_task non-fatal failure for doc=%s: %s — pipeline continues",
            document_id, exc,
        )
        _update_stage(job_id, "graph", "failed", str(exc))
        # Do not retry — graph is supplemental; don't block indexing

    return ctx   # unchanged — graph stage has no output consumed downstream


# ── Task 6 — Validate + Index ─────────────────────────────────────────────────

@celery_app.task(bind=True, max_retries=3, name="ingestion.workers.tasks.validate_and_index_task")
def validate_and_index_task(self, ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Compute quality scores, then index approved chunks into Qdrant + Supabase.
    Quality gate: if index_readiness_score < 0.85, document stays at FAILED.
    """
    document_id = ctx["document_id"]
    job_id      = ctx["job_id"]
    org_id      = ctx["organization_id"]

    _update_stage(job_id, "validate", "in_progress")
    _update_processing(document_id, ProcessingStatus.VALIDATING)

    try:
        content      = ParsedContent.model_validate(ctx["parsed_content"])
        doc_metadata = DocumentMetadata.model_validate(ctx["doc_metadata"])
        chunks       = [Chunk.model_validate(c) for c in ctx["chunks"]]
        is_reindex   = ctx.get("is_reindex", False)

        # Validate
        scores = ValidationPipeline().validate(
            content      = content,
            doc_metadata = doc_metadata,
            chunks       = chunks,
            document_id  = document_id,
        )
        _update_stage(job_id, "validate", "completed")
        _update_stage(job_id, "index",    "in_progress")
        _update_processing(document_id, ProcessingStatus.INDEXING)

        # Index (quality gate inside IndexingService)
        chunk_count = IndexingService().index(
            chunks          = chunks,
            document_id     = document_id,
            job_id          = job_id,
            organization_id = org_id,
            scores          = scores,
            is_reindex      = is_reindex,
        )

        logger.info(
            "validate_and_index | doc=%s chunks=%d readiness=%.3f",
            document_id, chunk_count, scores.index_readiness_score,
        )
        return {
            **ctx,
            "quality_scores": scores.model_dump(mode="json"),
            "chunk_count":    chunk_count,
        }

    except Exception as exc:
        _update_stage(job_id, "validate_index", "failed", str(exc))
        try:
            raise self.retry(exc=exc, countdown=_retry_countdown(self.request.retries))
        except MaxRetriesExceededError:
            handle_dead_letter.delay({**ctx, "error": str(exc), "stage": "validate_index"})
            raise


# ── Dead Letter Queue handler ─────────────────────────────────────────────────

@celery_app.task(name="ingestion.workers.tasks.handle_dead_letter")
def handle_dead_letter(ctx: dict[str, Any]) -> None:
    """
    Called when a pipeline task exhausts all retries.
    Marks the document + job as DEAD_LETTER and writes an audit log.
    """
    document_id = ctx.get("document_id", "unknown")
    job_id      = ctx.get("job_id",      "unknown")
    stage       = ctx.get("stage",       "unknown")
    error       = ctx.get("error",       "no error recorded")

    logger.error(
        "DEAD_LETTER | doc=%s job=%s stage=%s error=%s",
        document_id, job_id, stage, error,
    )
    try:
        db = _db()
        db.update_processing_status(document_id, ProcessingStatus.DEAD_LETTER)
        db.update_job(job_id, stage=stage, status="dead_letter", error_message=error[:500])
        db.write_audit_log(
            document_id = document_id,
            action      = "dead_letter",
            actor       = "system",
            extra       = {"stage": stage, "error": error[:500]},
        )
    except Exception as exc:
        logger.error("DLQ handler itself failed for doc=%s: %s", document_id, exc)


# ── Pipeline entry point ──────────────────────────────────────────────────────

def launch_pipeline(
    document_id:     str,
    job_id:          str,
    organization_id: str,
    is_reindex:      bool = False,
) -> None:
    """
    Kick off the full ingestion pipeline as a Celery task chain.
    Called by UploadService after a successful upload.
    """
    ctx: dict[str, Any] = {
        "document_id":     document_id,
        "job_id":          job_id,
        "organization_id": organization_id,
        "is_reindex":      is_reindex,
    }
    pipeline = chain(
        parse_and_classify_task.s(ctx),
        enrich_task.s(),
        chunk_task.s(),
        embed_task.s(),
        graph_task.s(),
        validate_and_index_task.s(),
    )
    pipeline.apply_async()
    logger.info(
        "Pipeline launched | doc=%s job=%s reindex=%s",
        document_id, job_id, is_reindex,
    )
