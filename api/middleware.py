"""
HCIP API Middleware — Phase 22.

RequestIDMiddleware:
  - Reads X-Request-ID from inbound request (or generates a UUID).
  - Stores it on request.state.request_id for use inside route handlers.
  - Echoes it back as X-Request-ID on every response.
  - Appends X-Latency-Ms to every response.
"""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        request.state.start_time = time.monotonic()

        response = await call_next(request)

        elapsed_ms = (time.monotonic() - request.state.start_time) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Latency-Ms"] = f"{elapsed_ms:.1f}"
        return response
