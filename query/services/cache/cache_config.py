from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from typing import Optional

import redis.asyncio as aioredis

from ingestion.config import get_settings

# ── Cache key builders ────────────────────────────────────────────────────────

class CacheKeys:

    @staticmethod
    def exact(org_id: str, kb_id: str, query_text: str) -> str:
        digest = hashlib.sha256(query_text.lower().strip().encode()).hexdigest()
        return f"hcip:q:exact:{org_id}:{kb_id}:{digest}"

    @staticmethod
    def semantic(cache_id: str) -> str:
        return f"hcip:q:semantic:{cache_id}"

    @staticmethod
    def retrieval(org_id: str, kb_id: str, embedding: list[float]) -> str:
        packed = struct.pack(f"{len(embedding)}f", *embedding)
        digest = hashlib.sha256(packed).hexdigest()[:32]
        return f"hcip:q:retrieval:{org_id}:{kb_id}:{digest}"

    @staticmethod
    def embedding(query_text: str) -> str:
        digest = hashlib.sha256(query_text.lower().strip().encode()).hexdigest()
        return f"hcip:q:embed:{digest}"


# ── Shared async Redis client (one pool per process) ──────────────────────────

_async_redis: Optional[aioredis.Redis] = None


async def get_async_redis() -> aioredis.Redis:
    global _async_redis
    if _async_redis is None:
        _async_redis = aioredis.from_url(
            get_settings().redis_url,
            decode_responses=False,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
    return _async_redis


# ── Result type returned by every cache layer ─────────────────────────────────

@dataclass
class CacheHit:
    fused_result: "FusedResult"       # noqa: F821  (resolved at runtime)
    layer:        str                  # "exact" | "semantic" | "retrieval"
    latency_ms:   float
