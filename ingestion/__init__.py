"""
HCIP Ingestion Pipeline
Healthcare Knowledge Intelligence Platform — converts raw documents into
governed, searchable, retrieval-optimized knowledge assets.

Import directly to avoid loading the full ingestion stack (Celery, spacy, etc.)
when only the config or storage clients are needed:

    from ingestion.config import get_settings
    from ingestion.pipeline import IngestionPipeline, IngestionResult, PipelineStatus
"""

# Lazy: do NOT import IngestionPipeline here — it pulls in Celery, spacy,
# paddleocr and other heavy ingestion-only deps that the query API must not load.

__version__ = "0.1.0"
