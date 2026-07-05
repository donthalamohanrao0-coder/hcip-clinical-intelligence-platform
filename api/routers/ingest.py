"""
HCIP Ingest Router — lightweight direct-ingest endpoint.

POST /api/v1/ingest/upload   — accept a file, chunk+embed+store in Qdrant/ES
GET  /api/v1/ingest/documents — list all ingested documents (Redis-backed)
GET  /api/v1/ingest/status/{doc_id} — single document status
DELETE /api/v1/ingest/documents/{doc_id} — delete document vectors

This bypasses S3/Supabase/Celery for demo/dev use.
The full production pipeline (with governance, versioning, async) lives in
ingestion/pipeline.py and is triggered via Celery workers.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import re
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel

from ingestion.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["Ingestion"])

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

SUPPORTED_TYPES = {
    "application/pdf": "pdf",
    "text/plain": "txt",
    "text/csv": "csv",
    "application/json": "json",
}
SUPPORTED_EXTENSIONS = {"pdf", "txt", "csv", "json", "md"}

# Singleton embedder — loaded once per worker process, reused across all uploads
_EMBEDDER = None


# ── Document registry — Supabase-backed (was an in-memory dict; that reset on
#    every restart and wasn't shared across the 2 uvicorn worker processes,
#    which is why uploads appeared to "disappear") ────────────────────────────

def _supabase():
    from supabase import create_client
    cfg = get_settings()
    return create_client(cfg.supabase_url, cfg.supabase_service_key)


def _insert_document_record(
    document_id: str,
    org_id: str,
    knowledge_base_id: str,
    filename: str,
    extension: str,
    chunks_created: int,
    uploaded_by: str,
) -> None:
    from datetime import datetime, timezone
    try:
        _supabase().table("documents").insert({
            "document_id":       document_id,
            "organization_id":   org_id,
            "department_id":     "general",
            "knowledge_base_id": knowledge_base_id,
            "file_name":         filename,
            "file_type":         extension.upper(),
            "s3_key":            "n/a-direct-ingest",
            "uploaded_by":       uploaded_by,
            "document_type":     extension,
            "governance_state":  "approved",
            "processing_status": "completed",
            "chunks_created":    chunks_created,
            "created_at":        datetime.now(timezone.utc).isoformat(),
            "updated_at":        datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as exc:
        logger.error("Supabase insert failed for %s: %s", document_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to save document record: {exc}")


def _list_document_records(org_id: str) -> list[dict]:
    try:
        result = (
            _supabase().table("documents")
            .select("*")
            .eq("organization_id", org_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        logger.error("Supabase list failed for org=%s: %s", org_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to list documents: {exc}")


def _get_document_record(document_id: str, org_id: str) -> Optional[dict]:
    try:
        result = (
            _supabase().table("documents")
            .select("*")
            .eq("document_id", document_id)
            .eq("organization_id", org_id)
            .maybe_single()
            .execute()
        )
        return result.data if result and result.data else None
    except Exception as exc:
        logger.error("Supabase get failed for %s: %s", document_id, exc)
        return None


def _delete_document_record(document_id: str, org_id: str) -> None:
    try:
        _supabase().table("documents").delete().eq("document_id", document_id).eq(
            "organization_id", org_id
        ).execute()
    except Exception as exc:
        logger.warning("Supabase delete failed for %s: %s", document_id, exc)


def _to_document_info(row: dict) -> "DocumentInfo":
    return DocumentInfo(
        document_id       = row["document_id"],
        file_name          = row["file_name"],
        file_type          = row["file_type"],
        knowledge_base_id  = row["knowledge_base_id"],
        chunks_created     = row.get("chunks_created", 0),
        uploaded_at        = row["created_at"],
        status             = row.get("processing_status", "completed"),
    )


def _get_embedder():
    global _EMBEDDER
    if _EMBEDDER is not None:
        return _EMBEDDER
    try:
        from ingestion.services.embedding.text_embedder import TextEmbedder
        _EMBEDDER = TextEmbedder()
        return _EMBEDDER
    except Exception as exc:
        logger.warning("TextEmbedder unavailable (%s); using zero vectors", exc)
        return None


# ── Auth dep ──────────────────────────────────────────────────────────────────

def _resolve_key(api_key: str) -> tuple[bool, str]:
    """Returns (valid, org_id). org_id parsed from key config: rawkey:org_id:role."""
    cfg = get_settings()
    raw_key = api_key.split(":")[0] if ":" in api_key else api_key
    for entry in cfg.api_keys:
        parts = entry.split(":", 2)
        if len(parts) == 3 and parts[0] == raw_key:
            return True, parts[1]   # org_id is the middle segment
        if parts and parts[0] == raw_key:
            return True, "default"
    if not cfg.api_keys and api_key.startswith("sk-hcip-"):
        return True, "default"
    return False, ""


def _verify_key(api_key: str = Depends(_API_KEY_HEADER)) -> str:
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    valid, _ = _resolve_key(api_key)
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return api_key


# ── Response models ───────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    success: bool
    document_id: str
    file_name: str
    file_type: str
    chunks_created: int
    knowledge_base_id: str
    processing_time_ms: float
    message: str


class DocumentInfo(BaseModel):
    document_id: str
    file_name: str
    file_type: str
    knowledge_base_id: str
    chunks_created: int
    uploaded_at: str
    status: str


class DocumentListResponse(BaseModel):
    success: bool
    documents: list[DocumentInfo]
    total: int


class StatusResponse(BaseModel):
    success: bool
    document_id: str
    status: str
    file_name: str
    chunks_created: int


# ── Text extraction helpers ───────────────────────────────────────────────────

def _extract_text_from_pdf(content: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        parts = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                parts.append(text.strip())
        return "\n\n".join(parts)
    except ImportError:
        raise HTTPException(
            status_code=422,
            detail="pypdf not installed on this server. Upload a .txt or .json file instead."
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"PDF parsing failed: {exc}")


def _extract_text(content: bytes, extension: str, filename: str) -> str:
    if extension == "pdf":
        return _extract_text_from_pdf(content)
    if extension in ("txt", "md", "csv"):
        for enc in ("utf-8", "latin-1", "utf-16"):
            try:
                return content.decode(enc)
            except UnicodeDecodeError:
                continue
        raise HTTPException(status_code=422, detail="Cannot decode file as text.")
    if extension == "json":
        try:
            obj = json.loads(content.decode("utf-8"))
            if isinstance(obj, list):
                return "\n".join(str(item) for item in obj)
            return json.dumps(obj, indent=2)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"JSON parse error: {exc}")
    raise HTTPException(status_code=422, detail=f"Unsupported file type: {extension}")


# ── Chunking ──────────────────────────────────────────────────────────────────

def _chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    """Simple paragraph-aware text splitter."""
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        words = para.split()
        for i in range(0, len(words), chunk_size - overlap):
            piece = " ".join(words[i: i + chunk_size])
            if len(current.split()) + len(piece.split()) < chunk_size:
                current = (current + " " + piece).strip()
            else:
                if current:
                    chunks.append(current)
                current = piece

    if current:
        chunks.append(current)

    return [c for c in chunks if len(c.split()) >= 10]  # drop tiny fragments


# ── Qdrant upsert ─────────────────────────────────────────────────────────────

def _upsert_to_qdrant(
    document_id: str,
    filename: str,
    file_type: str,
    knowledge_base_id: str,
    org_id: str,
    chunks: list[str],
    embeddings: list[list[float]],
) -> None:
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import PointStruct

        cfg = get_settings()
        client = QdrantClient(host=cfg.qdrant_host, port=cfg.qdrant_port)
        collection = cfg.qdrant_text_collection

        points = []
        for i, (chunk_text, vector) in enumerate(zip(chunks, embeddings)):
            chunk_id = f"{document_id}_chunk_{i}"
            points.append(PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk_id)),
                vector=vector,
                payload={
                    "document_id":     document_id,
                    "chunk_id":        chunk_id,
                    "chunk_index":     i,
                    "text":            chunk_text,
                    "source":          filename,
                    "document_type":   file_type,
                    "knowledge_base_id": knowledge_base_id,
                    "approval_status": "approved",
                    "organization_id": org_id,
                    "specialty":       "general",
                },
            ))

        # Upsert in batches of 64
        for batch_start in range(0, len(points), 64):
            client.upsert(
                collection_name=collection,
                points=points[batch_start: batch_start + 64],
            )
        logger.info("Upserted %d chunks for doc %s → Qdrant", len(points), document_id)
    except Exception as exc:
        logger.error("Qdrant upsert failed for %s: %s", document_id, exc)
        raise HTTPException(status_code=500, detail=f"Vector store error: {exc}")


def _delete_from_qdrant(document_id: str) -> None:
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        cfg = get_settings()
        client = QdrantClient(host=cfg.qdrant_host, port=cfg.qdrant_port)
        client.delete(
            collection_name=cfg.qdrant_text_collection,
            points_selector=Filter(must=[
                FieldCondition(key="document_id", match=MatchValue(value=document_id))
            ]),
        )
    except Exception as exc:
        logger.warning("Qdrant delete for %s failed: %s", document_id, exc)


# ── Elasticsearch index ───────────────────────────────────────────────────────
#
# IMPORTANT: the filter fields below (organization_id, knowledge_base_id,
# document_id, approval_status) must be mapped as `keyword`, not the default
# dynamically-mapped `text`. The retriever (query/services/retrieval/
# elasticsearch_retriever.py) filters on these with `term` queries, which
# silently match nothing against an analyzed `text` field — this is exactly
# the bug that made hybrid search silently fall back to vector-only for the
# index's entire lifetime until this mapping was added.
_ES_INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "document_id":       {"type": "keyword"},
            "chunk_id":          {"type": "keyword"},
            "text":              {"type": "text"},
            "source":            {"type": "keyword"},
            "knowledge_base_id": {"type": "keyword"},
            "approval_status":   {"type": "keyword"},
            "organization_id":   {"type": "keyword"},
        }
    },
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
}


def _ensure_es_index(es) -> None:
    cfg = get_settings()
    if not es.indices.exists(index=cfg.elasticsearch_chunk_index):
        es.indices.create(index=cfg.elasticsearch_chunk_index, body=_ES_INDEX_MAPPING)
        logger.info("Created Elasticsearch index %s with keyword mapping", cfg.elasticsearch_chunk_index)


def _index_to_elasticsearch(
    document_id: str,
    filename: str,
    knowledge_base_id: str,
    org_id: str,
    chunks: list[str],
) -> None:
    try:
        from elasticsearch import Elasticsearch

        cfg = get_settings()
        es = Elasticsearch(cfg.elasticsearch_url, request_timeout=10)
        _ensure_es_index(es)

        for i, chunk_text in enumerate(chunks):
            es.index(
                index=cfg.elasticsearch_chunk_index,
                id=f"{document_id}_chunk_{i}",
                document={
                    "document_id":     document_id,
                    "chunk_id":        f"{document_id}_chunk_{i}",
                    "text":            chunk_text,
                    "source":          filename,
                    "knowledge_base_id": knowledge_base_id,
                    "approval_status": "approved",
                    "organization_id": org_id,
                },
            )
        logger.info("Indexed %d chunks for doc %s → Elasticsearch", len(chunks), document_id)
    except Exception as exc:
        logger.warning("Elasticsearch index failed for %s: %s", document_id, exc)


def _delete_from_elasticsearch(document_id: str) -> None:
    try:
        from elasticsearch import Elasticsearch

        cfg = get_settings()
        es = Elasticsearch(cfg.elasticsearch_url, request_timeout=10)
        es.delete_by_query(
            index=cfg.elasticsearch_chunk_index,
            body={"query": {"term": {"document_id": document_id}}},
        )
    except Exception as exc:
        logger.warning("Elasticsearch delete for %s failed: %s", document_id, exc)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    knowledge_base_id: str = Form(default="kb-clinical-2024"),
    api_key: str = Depends(_verify_key),
) -> UploadResponse:
    _, org_id = _resolve_key(api_key)
    """
    Upload a document and index it directly into Qdrant + Elasticsearch.

    Supported formats: PDF, TXT, CSV, JSON, MD
    Max size: 50 MB
    """
    t0 = time.perf_counter()

    # ── Validate file ─────────────────────────────────────────────────────────
    filename = file.filename or "unknown"
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '.{extension}'. Allowed: {', '.join(SUPPORTED_EXTENSIONS)}",
        )

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large. Maximum 50 MB.")
    if not content:
        raise HTTPException(status_code=422, detail="Empty file.")

    document_id = f"doc-{uuid.uuid4().hex[:12]}"

    # ── Extract text ──────────────────────────────────────────────────────────
    text = _extract_text(content, extension, filename)
    if not text.strip():
        raise HTTPException(status_code=422, detail="Could not extract any text from this file.")

    # ── Chunk ─────────────────────────────────────────────────────────────────
    chunks = _chunk_text(text)
    if not chunks:
        raise HTTPException(status_code=422, detail="Document produced no usable text chunks.")

    # ── Embed ─────────────────────────────────────────────────────────────────
    embedder = _get_embedder()
    if embedder is not None:
        try:
            embeddings = embedder.embed_batch(chunks)
        except Exception as exc:
            logger.error("Embedding failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"Embedding error: {exc}")
    else:
        cfg = get_settings()
        dim = cfg.embedding_vector_dim
        embeddings = [[0.0] * dim for _ in chunks]

    # ── Store ─────────────────────────────────────────────────────────────────
    _upsert_to_qdrant(document_id, filename, extension, knowledge_base_id, org_id, chunks, embeddings)
    _index_to_elasticsearch(document_id, filename, knowledge_base_id, org_id, chunks)

    # ── Registry (Supabase — persists across restarts/workers) ────────────────
    uploaded_by = f"apikey:{hashlib.sha256(api_key.encode()).hexdigest()[:12]}"
    _insert_document_record(
        document_id, org_id, knowledge_base_id, filename, extension, len(chunks), uploaded_by,
    )

    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "Ingest complete | doc=%s file=%s chunks=%d kb=%s elapsed=%.0fms",
        document_id, filename, len(chunks), knowledge_base_id, elapsed_ms,
    )

    return UploadResponse(
        success=True,
        document_id=document_id,
        file_name=filename,
        file_type=extension.upper(),
        chunks_created=len(chunks),
        knowledge_base_id=knowledge_base_id,
        processing_time_ms=round(elapsed_ms, 1),
        message=f"Successfully indexed {len(chunks)} chunks into {knowledge_base_id}",
    )


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(api_key: str = Depends(_verify_key)) -> DocumentListResponse:
    """List all documents ingested for this org — persisted in Supabase."""
    _, org_id = _resolve_key(api_key)
    rows = _list_document_records(org_id)
    docs = [_to_document_info(row) for row in rows]
    return DocumentListResponse(success=True, documents=docs, total=len(docs))


@router.get("/status/{document_id}", response_model=StatusResponse)
async def get_status(
    document_id: str,
    api_key: str = Depends(_verify_key),
) -> StatusResponse:
    _, org_id = _resolve_key(api_key)
    doc = _get_document_record(document_id, org_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    return StatusResponse(
        success=True,
        document_id=document_id,
        status=doc.get("processing_status", "completed"),
        file_name=doc["file_name"],
        chunks_created=doc.get("chunks_created", 0),
    )


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    api_key: str = Depends(_verify_key),
) -> dict:
    _, org_id = _resolve_key(api_key)
    doc = _get_document_record(document_id, org_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    _delete_from_qdrant(document_id)
    _delete_from_elasticsearch(document_id)
    _delete_document_record(document_id, org_id)
    return {"success": True, "message": f"Document {document_id} deleted."}
