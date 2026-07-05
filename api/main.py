"""
HCIP FastAPI Application — Phase 22 / Phase 24 Observability.

Entry points:
  uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

API surface:
  POST /api/v1/query     — clinical query (auth required, rate-limited)
  GET  /health           — liveness probe
  GET  /health/ready     — readiness probe (all backends)
  GET  /metrics          — Prometheus metrics
  GET  /api/docs         — Swagger UI
  GET  /api/redoc        — ReDoc

Authentication:
  X-API-Key: <key>                   (service-to-service)
  Authorization: Bearer <JWT>        (user sessions)

Rate limiting:
  60 req/min per credential (configurable via RATE_LIMIT_PER_MINUTE).
  In-process sliding window — replace with Redis-backed limiter for
  multi-replica deployments.

Observability (Phase 24):
  - Prometheus metrics at /metrics (scraped by prometheus container)
  - OpenTelemetry traces exported to Grafana Tempo (OTEL_ENDPOINT)
  - Langfuse LLM call tracing (LANGFUSE_SECRET_KEY)
"""

from __future__ import annotations

import logging
import logging.config
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ingestion.config import get_settings

logging.config.dictConfig({
    "version":    1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "format": '{"time":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","msg":%(message)r}',
        },
    },
    "handlers": {
        "console": {
            "class":     "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
})

logger = logging.getLogger(__name__)


# ── Lifespan: warm up the pipeline on startup ─────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("HCIP API starting — compiling RAG pipeline...")
    from query.pipeline import rag_pipeline      # noqa: F401  triggers LangGraph compile
    from observability import setup_tracing
    setup_tracing()

    # Pre-warm the BGE embedding model so the first query is not penalised
    # with a 3-6 second cold-start model load.
    import asyncio
    async def _warm_embedder():
        try:
            from query.agents.planner.nodes import _get_embedder
            import asyncio as _aio
            embedder = _get_embedder()
            if embedder:
                await _aio.to_thread(embedder.embed, "warm")
                logger.info("BGE embedder pre-warmed.")
        except Exception as exc:
            logger.warning("Embedder pre-warm failed (non-fatal): %s", exc)
    asyncio.ensure_future(_warm_embedder())

    logger.info("RAG pipeline compiled and ready.")
    yield
    from observability import flush_langfuse
    flush_langfuse()
    logger.info("HCIP API shutting down.")


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    from api.middleware import RequestIDMiddleware
    from api.routers import (
        health,
        query as query_router,
        ingest as ingest_router,
        auth as auth_router,
        admin as admin_router,
    )

    cfg = get_settings()

    app = FastAPI(
        title       = "HCIP Clinical Intelligence API",
        description = (
            "Healthcare Clinical Intelligence Platform — "
            "RAG-powered clinical decision support for licensed healthcare professionals."
        ),
        version  = "1.0.0",
        docs_url = "/api/docs",
        redoc_url= "/api/redoc",
        lifespan = lifespan,
        contact  = {"name": "HCIP Engineering", "email": "support@hcip.ai"},
        license_info = {"name": "Proprietary"},
    )

    # ── CORS ─────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins     = cfg.cors_origins,
        allow_credentials = True,
        allow_methods     = ["GET", "POST", "OPTIONS"],
        allow_headers     = ["*"],
    )

    # ── Request ID + response timing ─────────────────────────────────────────
    app.add_middleware(RequestIDMiddleware)

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(health.router)
    app.include_router(query_router.router, prefix="/api/v1")
    app.include_router(ingest_router.router, prefix="/api/v1")
    app.include_router(auth_router.router, prefix="/api/v1")
    app.include_router(admin_router.router, prefix="/api/v1")

    # ── Prometheus metrics endpoint ───────────────────────────────────────────
    from prometheus_client import make_asgi_app
    app.mount("/metrics", make_asgi_app())

    # ── Global exception handler ──────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code = 500,
            content     = {
                "success": False,
                "error":   "Internal server error",
                "detail":  str(exc),
            },
        )

    return app


app = create_app()
