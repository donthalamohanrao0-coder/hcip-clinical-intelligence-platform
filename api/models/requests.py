"""
Inbound request models for the HCIP API.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class QueryRequest(BaseModel):
    """Body for POST /api/v1/query."""

    query:             str           = Field(..., min_length=3, max_length=2000,
                                            description="Clinical question (free text)")
    knowledge_base_id: str           = Field(..., min_length=1, max_length=128,
                                            description="Target knowledge base ID")
    organization_id:   Optional[str] = Field(default=None, max_length=128,
                                            description="Tenant org ID (falls back to JWT claim)")

    model_config = {"json_schema_extra": {
        "example": {
            "query":             "First-line treatment for type 2 diabetes in CKD stage 3?",
            "knowledge_base_id": "kb-clinical-2024",
            "organization_id":   "org-abc",
        }
    }}

    @field_validator("query")
    @classmethod
    def strip_query(cls, v: str) -> str:
        return v.strip()
