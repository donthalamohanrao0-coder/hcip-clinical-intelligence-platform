"""
Health and readiness probes.

GET /health        — liveness: confirms the process is up
GET /health/ready  — readiness: checks connectivity to all backends
                     Returns 200 if all pass, 503 if any are degraded.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    status:    str
    version:   str
    timestamp: str


class ReadinessResponse(BaseModel):
    status: str          # "ready" | "degraded"
    checks: dict[str, str]


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def liveness() -> HealthResponse:
    return HealthResponse(
        status    = "healthy",
        version   = "1.0.0",
        timestamp = datetime.now(timezone.utc).isoformat(),
    )


# ── Individual backend checks (run concurrently) ──────────────────────────────

async def _check_qdrant() -> str:
    try:
        from ingestion.config import get_settings
        from qdrant_client import QdrantClient

        cfg    = get_settings()
        client = QdrantClient(
            host    = cfg.qdrant_host,
            port    = cfg.qdrant_port,
            api_key = cfg.qdrant_api_key or None,
            timeout = 3,
        )
        await asyncio.to_thread(client.get_collections)
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


async def _check_redis() -> str:
    try:
        from query.services.cache.cache_config import get_async_redis

        redis = await get_async_redis()
        await redis.ping()
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


async def _check_elasticsearch() -> str:
    try:
        from elasticsearch import AsyncElasticsearch
        from ingestion.config import get_settings

        cfg = get_settings()
        es  = AsyncElasticsearch(cfg.elasticsearch_url, request_timeout=3)
        ok  = await es.ping()
        await es.close()
        return "ok" if ok else "error: ping returned False"
    except Exception as exc:
        return f"error: {exc}"


async def _check_neo4j() -> str:
    try:
        from ingestion.config import get_settings
        from neo4j import GraphDatabase

        cfg    = get_settings()
        driver = GraphDatabase.driver(
            cfg.neo4j_uri,
            auth            = (cfg.neo4j_user, cfg.neo4j_password),
            connection_timeout = 3,
        )
        await asyncio.to_thread(driver.verify_connectivity)
        await asyncio.to_thread(driver.close)
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


@router.get(
    "/health/ready",
    summary        = "Readiness probe — checks all backend connectivity",
    response_model = ReadinessResponse,
    responses      = {503: {"description": "One or more backends degraded"}},
)
async def readiness() -> JSONResponse:
    qdrant_ok, redis_ok, es_ok, neo4j_ok = await asyncio.gather(
        _check_qdrant(),
        _check_redis(),
        _check_elasticsearch(),
        _check_neo4j(),
    )

    checks = {
        "qdrant":         qdrant_ok,
        "redis":          redis_ok,
        "elasticsearch":  es_ok,
        "neo4j":          neo4j_ok,
    }

    all_ok      = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503

    return JSONResponse(
        status_code = status_code,
        content     = {
            "status": "ready" if all_ok else "degraded",
            "checks": checks,
        },
    )
