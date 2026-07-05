"""
OpenTelemetry distributed tracing for the HCIP RAG pipeline.

Initialization is done once on first call to get_tracer() or setup_tracing().
If OTEL_ENDPOINT is not configured, a no-op tracer is used — zero overhead,
no errors, no network calls.

Usage in run_query():
    tracer = get_tracer()
    with tracer.start_as_current_span("hcip.run_query") as span:
        span.set_attribute("hcip.org_id", org_id)
        result = await rag_pipeline.ainvoke(...)
        span.set_attribute("hcip.confidence", result.confidence_score)
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_tracer: Optional[object] = None


def setup_tracing() -> None:
    """Call once at application startup (from FastAPI lifespan)."""
    get_tracer()


def get_tracer():
    """Return the module-level OpenTelemetry tracer (initialised once)."""
    global _tracer
    if _tracer is not None:
        return _tracer

    from ingestion.config import get_settings
    cfg = get_settings()

    if not cfg.otel_endpoint:
        from opentelemetry.trace import NoOpTracer
        _tracer = NoOpTracer()
        logger.debug("OTEL_ENDPOINT not set — using no-op tracer")
        return _tracer

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({
            "service.name":    "hcip-api",
            "service.version": "1.0.0",
            "deployment.environment": cfg.environment,
        })

        provider = TracerProvider(resource=resource)
        exporter  = OTLPSpanExporter(endpoint=cfg.otel_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        _tracer = trace.get_tracer("hcip.rag_pipeline", "1.0.0")
        logger.info("OpenTelemetry tracer → %s", cfg.otel_endpoint)

    except Exception as exc:
        logger.warning("OTEL init failed (%s) — falling back to no-op", exc)
        from opentelemetry.trace import NoOpTracer
        _tracer = NoOpTracer()

    return _tracer
