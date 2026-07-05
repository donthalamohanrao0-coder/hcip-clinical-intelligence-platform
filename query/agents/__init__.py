"""
HCIP LangGraph agents — five-agent RAG query pipeline.

Agents (Phases 16–20):
    PlannerAgent    (16) — intent classification, embedding, cache check, source selection
    RetrieverAgent  (17) — multi-source retrieval execution + re-ranking
    VerifierAgent   (18) — citation validation, contradiction detection
    SafetyAgent     (19) — high-risk detection, escalation routing
    ResponseAgent   (20) — final answer synthesis + citation formatting

Full workflow graph assembled in Phase 21.
"""
