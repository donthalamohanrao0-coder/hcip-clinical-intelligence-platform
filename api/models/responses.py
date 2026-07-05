"""
Outbound response envelope for the HCIP API.
"""

from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """Standard JSON envelope for all successful responses."""
    success: bool = True
    data:    T


class ErrorResponse(BaseModel):
    """Standard JSON envelope for all error responses."""
    success: bool
    error:   str
    detail:  Optional[str] = None
    trace_id: Optional[str] = None
