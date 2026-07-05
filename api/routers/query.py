"""
Clinical query endpoint — POST /api/v1/query.

Wires the HTTP boundary to query.pipeline.run_query().
Auth, rate limiting, and org-ID resolution happen here so the
pipeline stays HTTP-agnostic.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from api.dependencies import UserContext, rate_limit
from api.models.requests import QueryRequest
from api.models.responses import APIResponse
from query.pipeline import QueryResult, run_query, run_query_stream

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Query"])


def _resolve_org_id(body: QueryRequest, user: UserContext) -> str:
    org_id = body.organization_id or user.organization_id
    if not org_id:
        raise HTTPException(
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail      = (
                "organization_id is required. Pass it in the request body, "
                "or authenticate with a token/API key that carries an org identifier."
            ),
        )
    return org_id


@router.post(
    "/query",
    response_model = APIResponse[QueryResult],
    summary        = "Submit a clinical query to the HCIP RAG pipeline",
    description    = """\
Run a clinical question through the full 5-agent pipeline:

| Stage     | Agent     | Work done                                              |
|-----------|-----------|--------------------------------------------------------|
| 1         | Planner   | Intent classification, BGE-M3 embedding, cache check  |
| 2         | Retriever | Qdrant + ES + Neo4j + PubMed → RRF fusion → re-rank   |
| 3         | Verifier  | Citation scoring, contradiction detection              |
| 4         | Safety    | Risk patterns, drug-interaction flags, escalation      |
| 5         | Response  | GPT-4o-mini synthesis, citation formatting, confidence |

Cache hit path (fast ~300 ms) skips the Retriever agent.
Full path (first query) takes ~1–3 s.
""",
)
async def submit_query(
    request: Request,
    body:    QueryRequest,
    user:    UserContext = Depends(rate_limit),
) -> APIResponse[QueryResult]:
    """
    **Required auth**: X-API-Key header or Authorization: Bearer <JWT>.

    The `organization_id` field is optional in the body — if omitted, the
    value is taken from the JWT `org` claim or the API-key configuration.
    If it cannot be resolved from either source a 422 is returned.
    """
    org_id     = _resolve_org_id(body, user)
    request_id = getattr(request.state, "request_id", "-")
    logger.info(
        "Query | org=%s kb=%s user=%s req=%s",
        org_id, body.knowledge_base_id, user.user_id, request_id,
    )

    result = await run_query(
        query_text        = body.query,
        organization_id   = org_id,
        knowledge_base_id = body.knowledge_base_id,
        role              = user.role,
        user_id           = user.user_id,
    )

    logger.info(
        "Query complete | req=%s latency=%.0f ms cache=%s confidence=%.3f escalated=%s",
        request_id, result.total_latency_ms, result.cache_hit,
        result.confidence_score, result.requires_escalation,
    )

    return APIResponse(data=result)


@router.post(
    "/query/stream",
    summary     = "Submit a clinical query and stream the response as Server-Sent Events",
    description = """\
Same 5-agent pipeline as `/query`, but the Response agent's answer is streamed
token-by-token instead of returned as one blocking JSON body.

Event stream (`text/event-stream`, one JSON object per `data:` line):

| `type`  | Fields                                            | When                                    |
|---------|----------------------------------------------------|------------------------------------------|
| `stage` | `stage`, `label`                                   | After each of Planner/Retriever/Verifier/Safety completes, and once more before synthesis starts |
| `token` | `text`                                             | Repeated — one chunk of the answer, in order |
| `meta`  | All `QueryResult` fields except `final_response`/`query_text` | Once, after the answer finishes streaming |
| `error` | `message`                                          | Only on pipeline failure                 |
| `done`  | —                                                   | Always sent last                         |

Concatenate `token.text` in arrival order to reconstruct the full answer text.
""",
)
async def submit_query_stream(
    request: Request,
    body:    QueryRequest,
    user:    UserContext = Depends(rate_limit),
) -> StreamingResponse:
    """**Required auth**: X-API-Key header or Authorization: Bearer <JWT>."""
    org_id     = _resolve_org_id(body, user)
    request_id = getattr(request.state, "request_id", "-")
    logger.info(
        "Query (stream) | org=%s kb=%s user=%s req=%s",
        org_id, body.knowledge_base_id, user.user_id, request_id,
    )

    async def event_source():
        async for event in run_query_stream(
            query_text        = body.query,
            organization_id   = org_id,
            knowledge_base_id = body.knowledge_base_id,
            role              = user.role,
            user_id           = user.user_id,
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type = "text/event-stream",
        headers    = {
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )
