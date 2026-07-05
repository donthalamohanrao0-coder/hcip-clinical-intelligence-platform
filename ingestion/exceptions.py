"""
Custom exception hierarchy for the HCIP Ingestion Pipeline.
Every service raises a specific subclass so callers can handle errors
at the right granularity without catching bare Exception.
"""


# ── Base ─────────────────────────────────────────────────────────────────────

class IngestionError(Exception):
    """Root exception for all ingestion pipeline errors."""


# ── Storage layer ─────────────────────────────────────────────────────────────

class StorageError(IngestionError):
    """Failed read/write to any external storage system."""

class S3Error(StorageError):
    """boto3 / S3 operation failed."""

class DatabaseError(StorageError):
    """Supabase / PostgreSQL operation failed."""

class VectorStoreError(StorageError):
    """Qdrant operation failed."""

class GraphStoreError(StorageError):
    """Neo4j operation failed."""

class CacheError(StorageError):
    """Redis operation failed."""


# ── Pipeline stages ───────────────────────────────────────────────────────────

class UploadError(IngestionError):
    """File upload or validation failed."""

class FileTooLargeError(UploadError):
    """Uploaded file exceeds the configured size limit."""

class UnsupportedFileTypeError(UploadError):
    """File extension or MIME type is not supported."""

class VirusScanError(UploadError):
    """Virus / malware detected in uploaded file."""

class ClassificationError(IngestionError):
    """Document type classification failed."""

class ParseError(IngestionError):
    """Document parsing (Docling / OCR / ColQwen) failed."""

class OCRError(ParseError):
    """PaddleOCR failed or returned confidence below threshold."""

class MetadataError(IngestionError):
    """Metadata extraction or ontology enrichment failed."""

class ChunkingError(IngestionError):
    """Chunking engine failed to produce valid chunks."""

class EmbeddingError(IngestionError):
    """Embedding model call failed."""

class KnowledgeGraphError(IngestionError):
    """Entity extraction or Neo4j graph update failed."""

class ValidationError(IngestionError):
    """Document failed one or more quality validation checks."""

class GovernanceError(IngestionError):
    """Invalid governance state transition attempted."""

class IndexingError(IngestionError):
    """Indexing to Qdrant or Supabase failed."""
