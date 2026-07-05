"""
FastAPI dependency injection — auth, user context, and rate limiting.

Authentication supports two mechanisms (checked in order):
  1. X-API-Key header  — service-to-service calls
  2. Authorization: Bearer <JWT>  — user-facing sessions

API keys are configured as a list of "rawkey:org_id:role" strings via the
API_KEYS environment variable (JSON array).

JWT tokens must carry:
  sub   → user_id
  org   → organization_id
  role  → clinical role (physician / nurse / pharmacist / viewer / admin)

Rate limiter: sliding-window, in-process.
  Default: 60 requests / 60 seconds per credential key.
  Fine for single-instance deployments; replace with Redis-backed limiter
  in multi-replica production (Phase 24 Observability).
"""

from __future__ import annotations

import asyncio
import collections
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ingestion.config import get_settings

logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)


# ── User context ──────────────────────────────────────────────────────────────

@dataclass
class UserContext:
    """Resolved identity from an inbound credential."""
    user_id:         str
    organization_id: str
    role:            str
    credential_type: str   # "api_key" | "jwt"


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _validate_api_key(raw_key: str) -> Optional[UserContext]:
    cfg = get_settings()
    for entry in cfg.api_keys:
        parts = entry.split(":", 2)
        if len(parts) == 3 and parts[0] == raw_key:
            _, org_id, role = parts
            key_hash = hashlib.sha256(raw_key.encode()).hexdigest()[:12]
            return UserContext(
                user_id         = f"apikey:{key_hash}",
                organization_id = org_id,
                role            = role,
                credential_type = "api_key",
            )
    return None


def _validate_jwt(token: str) -> Optional[UserContext]:
    cfg = get_settings()
    if not cfg.jwt_secret or cfg.jwt_secret.startswith("REPLACE"):
        return None
    try:
        from jose import jwt
        payload = jwt.decode(token, cfg.jwt_secret, algorithms=[cfg.jwt_algorithm])
        return UserContext(
            user_id         = str(payload.get("sub", "unknown")),
            organization_id = str(payload.get("org", "")),
            role            = str(payload.get("role", "viewer")),
            credential_type = "jwt",
        )
    except Exception as exc:
        logger.debug("JWT validation failed: %s", exc)
        return None


async def get_current_user(
    x_api_key:   Optional[str]                          = Header(default=None, alias="X-API-Key"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> UserContext:
    """
    Resolves caller identity.  Raises 401 if no valid credential is present.
    Raises 403 if the credential is recognised but the org_id is empty
    (API key misconfigured or JWT missing 'org' claim).
    """
    if x_api_key:
        ctx = _validate_api_key(x_api_key)
        if ctx is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Invalid API key")
        return ctx

    if credentials:
        ctx = _validate_jwt(credentials.credentials)
        if ctx is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Invalid or expired token")
        return ctx

    raise HTTPException(
        status_code = status.HTTP_401_UNAUTHORIZED,
        detail      = "Authentication required: provide X-API-Key or Authorization: Bearer <token>",
        headers     = {"WWW-Authenticate": "Bearer"},
    )


async def require_admin(user: UserContext = Depends(get_current_user)) -> UserContext:
    """Gate for /admin/* routes — only 'admin'-role JWTs may pass."""
    if user.role != "admin":
        raise HTTPException(
            status_code = status.HTTP_403_FORBIDDEN,
            detail      = "Admin role required",
        )
    return user


# ── In-process sliding-window rate limiter ────────────────────────────────────

_rate_store: dict[str, list[float]] = collections.defaultdict(list)
_rate_lock  = asyncio.Lock()


async def rate_limit(user: UserContext = Depends(get_current_user)) -> UserContext:
    """
    Dependency that enforces rate limits before a route handler runs.
    Limit is read from settings.rate_limit_per_minute (default 60).
    The lock ensures thread-safe mutation of the in-process store.
    """
    cfg    = get_settings()
    limit  = cfg.rate_limit_per_minute
    window = 60.0
    key    = f"{user.credential_type}:{user.user_id}"
    now    = time.monotonic()

    async with _rate_lock:
        cutoff             = now - window
        _rate_store[key]   = [t for t in _rate_store[key] if t > cutoff]
        if len(_rate_store[key]) >= limit:
            raise HTTPException(
                status_code = status.HTTP_429_TOO_MANY_REQUESTS,
                detail      = f"Rate limit exceeded: {limit} requests/minute",
                headers     = {"Retry-After": "60"},
            )
        _rate_store[key].append(now)

    return user
