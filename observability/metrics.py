"""
Prometheus metrics for the HCIP RAG pipeline.

Metrics:
    hcip_query_total               — counter: queries processed
    hcip_query_latency_seconds     — histogram: end-to-end latency
    hcip_confidence_score          — histogram: response confidence distribution
    hcip_cache_hits_total          — counter: cache hits by layer
    hcip_safety_flags_total        — counter: safety flags by severity + type
    hcip_pipeline_errors_total     — counter: errors by stage

Exposed at GET /metrics via prometheus_client.make_asgi_app().
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram


QUERY_TOTAL = Counter(
    "hcip_query_total",
    "Total clinical queries processed",
    ["status", "cache_hit", "escalated"],
)

QUERY_LATENCY = Histogram(
    "hcip_query_latency_seconds",
    "End-to-end query latency in seconds",
    ["cache_hit"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 30.0],
)

CONFIDENCE_SCORE = Histogram(
    "hcip_confidence_score",
    "Distribution of response confidence scores",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

CACHE_HITS = Counter(
    "hcip_cache_hits_total",
    "Cache hit count by layer",
    ["layer"],
)

SAFETY_FLAGS = Counter(
    "hcip_safety_flags_total",
    "Safety flags triggered",
    ["severity", "flag_type"],
)

PIPELINE_ERRORS = Counter(
    "hcip_pipeline_errors_total",
    "Pipeline errors by stage",
    ["stage"],
)


def record_query_metrics(result: object) -> None:
    """
    Record all Prometheus metrics for a completed QueryResult.
    Accepts the QueryResult Pydantic model; uses duck-typing so this
    module has no hard import dependency on query.pipeline.
    """
    try:
        status   = "error" if result.errors else "success"  # type: ignore[union-attr]
        cache    = str(result.cache_hit).lower()              # type: ignore[union-attr]
        escalate = str(result.requires_escalation).lower()    # type: ignore[union-attr]

        QUERY_TOTAL.labels(
            status   = status,
            cache_hit = cache,
            escalated = escalate,
        ).inc()

        QUERY_LATENCY.labels(cache_hit=cache).observe(
            result.total_latency_ms / 1000.0  # type: ignore[union-attr]
        )

        CONFIDENCE_SCORE.observe(result.confidence_score)  # type: ignore[union-attr]

        if result.cache_hit and result.cache_layer:         # type: ignore[union-attr]
            CACHE_HITS.labels(layer=result.cache_layer).inc()

        for flag in result.safety_flags:                    # type: ignore[union-attr]
            SAFETY_FLAGS.labels(
                severity  = flag.get("severity",  "unknown"),
                flag_type = flag.get("flag_type", "unknown"),
            ).inc()

        for err in result.errors:                           # type: ignore[union-attr]
            # Classify the error stage from common prefixes
            stage = "pipeline"
            for prefix in ("planner", "retriever", "verifier", "safety", "response"):
                if prefix in err.lower():
                    stage = prefix
                    break
            PIPELINE_ERRORS.labels(stage=stage).inc()

    except Exception:
        pass   # metrics are best-effort; never crash the caller
