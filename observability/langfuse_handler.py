"""
Langfuse v4 native tracing for the HCIP RAG pipeline.

v4 is OTEL-native — the old .trace()/.span()/.generation() client methods are gone.
The correct v4 pattern:

    with propagate_attributes(trace_name=..., user_id=..., tags=[...]):
        with client.start_as_current_observation(name=..., as_type="span") as root:
            # pipeline runs here; response/nodes.py adds nested observations
            root.update(output=..., metadata=...)

Key constraints discovered:
  - start_as_current_observation() returns _AgnosticContextManager (OTEL), sync only.
    Use plain 'with', NOT 'async with', even inside async functions.
  - propagate_attributes() metadata values must be str (not int/float).
  - set_current_trace_io() is deprecated in v4.
  - OTEL context propagates automatically through the async call stack, so
    nested start_as_current_observation() calls in child functions (response/nodes.py)
    automatically become children of the root span.

Graceful degradation:
  - Keys not set / placeholder  → tracing silently disabled
  - langfuse not installed      → same
  - Any SDK error               → pipeline continues, no crash
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

_lf_client   = None          # Langfuse singleton (set on first successful init)
_lf_enabled  = None          # tri-state: None=unchecked, True=ok, False=disabled


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_or_init_client():
    """
    Initialise the Langfuse client on first call and return it.
    Returns None if Langfuse is disabled or misconfigured.
    """
    global _lf_client, _lf_enabled

    if _lf_enabled is False:
        return None
    if _lf_client is not None:
        return _lf_client

    from ingestion.config import get_settings
    cfg = get_settings()

    sk = (cfg.langfuse_secret_key or "").strip('"').strip("'")
    pk = (cfg.langfuse_public_key or "").strip('"').strip("'")
    host = (cfg.langfuse_base_url or "").strip('"').strip("'")

    if not sk or sk.startswith("REPLACE") or not pk:
        logger.info("Langfuse disabled — LANGFUSE_SECRET_KEY not configured")
        _lf_enabled = False
        return None

    try:
        import langfuse as _lf_mod  # noqa: F401 — ensures package is installed
        from langfuse import Langfuse
        _lf_client  = Langfuse(secret_key=sk, public_key=pk, host=host)
        _lf_enabled = True
        logger.info("Langfuse tracing enabled → %s", host)
    except ImportError:
        logger.warning("langfuse not installed — run: pip install 'langfuse>=4'")
        _lf_enabled = False
    except Exception as exc:
        logger.warning("Langfuse client init failed (non-fatal): %s", exc)
        _lf_enabled = False

    return _lf_client


# ── Public API ────────────────────────────────────────────────────────────────

def is_langfuse_enabled() -> bool:
    return _get_or_init_client() is not None


@contextmanager
def pipeline_trace(
    query_text: str,
    user_id:    str,
    org_id:     str,
    kb_id:      str,
    role:       Optional[str],
    trace_id:   str,
):
    """
    Context manager that wraps one pipeline invocation in a Langfuse trace.

    Usage in pipeline.py:
        with pipeline_trace(query_text, user_id, org_id, kb_id, role, trace_id) as lf_root:
            final_state = await rag_pipeline.ainvoke(initial_state)
            if lf_root:
                lf_root.update(output=answer, metadata={...})

    Yields the root LangfuseSpan object, or None if Langfuse is disabled.
    """
    client = _get_or_init_client()
    if client is None:
        yield None
        return

    try:
        from langfuse import propagate_attributes

        # propagate_attributes metadata values must be str
        meta = {
            "org_id":   org_id,
            "kb_id":    kb_id,
            "role":     role or "",
            "trace_id": trace_id,
        }

        with propagate_attributes(
            trace_name = "hcip-clinical-query",
            user_id    = user_id,
            session_id = org_id,
            tags       = ["hcip", "clinical-rag", org_id],
            metadata   = meta,
        ):
            with client.start_as_current_observation(
                name     = "clinical-query",
                as_type  = "span",
                input    = query_text,
            ) as root:
                yield root   # caller gets root to call root.update() after pipeline

    except Exception as exc:
        logger.debug("Langfuse trace creation failed (non-fatal): %s", exc)
        yield None


def log_llm_generation_ctx():
    """
    Returns (client, current_trace_id) so the caller can open its own
    start_as_current_observation() around the LLM call.
    Returns (None, None) when Langfuse is disabled or no trace is active.
    """
    client = _get_or_init_client()
    if client is None:
        return None, None
    try:
        trace_id = client.get_current_trace_id()
        return (client, trace_id) if trace_id else (None, None)
    except Exception:
        return None, None


def flush_langfuse() -> None:
    """Flush pending Langfuse events on server shutdown."""
    if _lf_client is None:
        return
    try:
        _lf_client.flush()
        logger.info("Langfuse flushed — all events sent.")
    except Exception as exc:
        logger.debug("Langfuse flush error (non-fatal): %s", exc)


# ── Compatibility shims for observability/__init__.py ─────────────────────────

def get_langfuse_handler():
    """Legacy alias — native v4 SDK uses no LangChain callback."""
    return None


def make_callback_handler():
    """Legacy alias — native v4 SDK uses no LangChain callback."""
    return None
