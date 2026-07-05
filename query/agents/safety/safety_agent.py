"""
Safety Agent — LangGraph compiled subgraph.

Scans verified chunks and the original query for clinical safety signals,
flags high-risk content, detects dangerous drug interactions, and decides
whether the query requires escalation to human clinical review.

Graph topology:
    START
      │
      ▼
  detect_risks ──── pattern library scan across query + all verified chunks
      │             Emergency conditions  → critical flag (always escalate)
      │             High-alert drugs     → high flag (narrow therapeutic index list)
      │             Dosing risk terms    → high flag
      │             Pediatric dosing     → high flag
      │             Pregnancy/lactation  → medium flag
      │             6 known drug-interaction pairs → critical / high flags
      │             → safety_flags (list)
      ▼
  evaluate_escalation ── rule-based escalation:
      │                  critical flag present        → escalate
      │                  2+ high flags present        → escalate
      │                  LLM deep-check (optional)    → borderline cases only
      │                  Builds clinical_disclaimer text
      │                  → requires_escalation, escalation_reason
      │                  → clinical_disclaimer flag appended to safety_flags
      ▼
     END

Escalation means (used by Phase 21 workflow router):
    • Mandatory enhanced disclaimer prepended to response
    • Query flagged for audit log human-review queue
    • Response Agent uses conservative synthesis template

Usage (standalone):
    from query.agents.safety import safety_graph

    result = await safety_graph.ainvoke(state)
    # result["safety_flags"]         → list of risk flags
    # result["requires_escalation"]  → bool
    # result["escalation_reason"]    → str | None
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from query.agents.state import RAGState

from .nodes import detect_risks_node, evaluate_escalation_node


def build_safety_graph():
    """Build and compile the Safety Agent subgraph."""
    builder = StateGraph(RAGState)

    builder.add_node("detect_risks",         detect_risks_node)
    builder.add_node("evaluate_escalation",  evaluate_escalation_node)

    builder.set_entry_point("detect_risks")
    builder.add_edge("detect_risks",         "evaluate_escalation")
    builder.add_edge("evaluate_escalation",  END)

    return builder.compile()


# Module-level compiled graph
safety_graph = build_safety_graph()
