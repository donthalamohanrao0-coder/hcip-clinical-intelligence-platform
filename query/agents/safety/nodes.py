"""
Async node functions for the Safety Agent.

Graph:
    START → detect_risks → evaluate_escalation → END
"""

from __future__ import annotations

import re
import time
from typing import Any, Optional

from query.agents.state import RAGState
from query.models.result import RetrievedChunk

# ── Clinical risk pattern library ─────────────────────────────────────────────

_EMERGENCY_RE = re.compile(
    r'\b('
    r'stemi|myocardial infarction|\bmi\b|cardiac arrest|'
    r'stroke|cva|tia|'
    r'sepsis|septic shock|bacteremia|'
    r'anaphylaxis|anaphylactic shock|'
    r'status epilepticus|'
    r'respiratory arrest|respiratory failure|'
    r'pulmonary embolism|\bpe\b|dvt|'
    r'aortic dissection|ruptured aneurysm|'
    r'diabetic ketoacidosis|dka|hyperosmolar|'
    r'hypertensive crisis|hypertensive urgency|'
    r'eclampsia|preeclampsia|hellp|'
    r'massive hemorrhage|gastrointestinal bleed|'
    r'acute liver failure|hepatic encephalopathy|'
    r'tension pneumothorax|cardiac tamponade|'
    r'meningitis|encephalitis|'
    r'epiglottitis|airway obstruction'
    r')\b',
    re.I,
)

_HIGH_RISK_DRUG_RE = re.compile(
    r'\b('
    r'warfarin|coumadin|'
    r'digoxin|lanoxin|'
    r'lithium|'
    r'phenytoin|dilantin|'
    r'gentamicin|tobramycin|amikacin|'
    r'vancomycin|'
    r'methotrexate|'
    r'cyclosporine|tacrolimus|sirolimus|'
    r'amiodarone|'
    r'heparin|enoxaparin|apixaban|rivaroxaban|dabigatran|'
    r'insulin|'
    r'potassium chloride|kcl|concentrated potassium|'
    r'hypertonic saline|'
    r'chemotherapy|cytotoxic|'
    r'neuromuscular blocking|succinylcholine|vecuronium|rocuronium|'
    r'thalidomide|lenalidomide|'
    r'clozapine|'
    r'isotretinoin|accutane|'
    r'fentanyl|morphine|oxycodone|hydromorphone|methadone'
    r')\b',
    re.I,
)

_DOSING_RISK_RE = re.compile(
    r'\b('
    r'overdose|toxicity|toxic dose|lethal dose|ld50|'
    r'maximum dose|max dose|dose limit|'
    r'supratherapeutic|above therapeutic|'
    r'dose reduction|renal dose|hepatic dose|'
    r'loading dose|bolus dose'
    r')\b',
    re.I,
)

_PEDIATRIC_RE = re.compile(
    r'\b('
    r'pediatric|paediatric|neonatal|neonate|'
    r'infant|newborn|toddler|'
    r'child dose|weight.based|mg/kg|mcg/kg|'
    r'age.adjusted|body surface area|bsa'
    r')\b',
    re.I,
)

_PREGNANCY_RE = re.compile(
    r'\b('
    r'pregnancy|pregnant|lactation|breastfeeding|'
    r'teratogenic|fetal risk|category [abcdx]|'
    r'trimester|gestational'
    r')\b',
    re.I,
)

# ── Known dangerous drug interaction pairs ────────────────────────────────────

_DRUG_INTERACTIONS: list[dict[str, Any]] = [
    {
        "name":      "Warfarin + NSAID",
        "re_a":      re.compile(r'\b(warfarin|coumadin)\b', re.I),
        "re_b":      re.compile(r'\b(nsaid|aspirin|ibuprofen|naproxen|celecoxib|indomethacin|diclofenac)\b', re.I),
        "severity":  "high",
        "description": "Warfarin + NSAID: significantly increased bleeding risk",
    },
    {
        "name":      "MAOI + SSRI/SNRI",
        "re_a":      re.compile(r'\b(maoi|phenelzine|tranylcypromine|selegiline|isocarboxazid)\b', re.I),
        "re_b":      re.compile(r'\b(ssri|snri|fluoxetine|sertraline|paroxetine|venlafaxine|duloxetine|tramadol)\b', re.I),
        "severity":  "critical",
        "description": "MAOI + SSRI/SNRI: risk of fatal serotonin syndrome",
    },
    {
        "name":      "Methotrexate + NSAID",
        "re_a":      re.compile(r'\bmethotrexate\b', re.I),
        "re_b":      re.compile(r'\b(nsaid|aspirin|ibuprofen|naproxen|trimethoprim)\b', re.I),
        "severity":  "high",
        "description": "Methotrexate + NSAID/Trimethoprim: severe methotrexate toxicity risk",
    },
    {
        "name":      "QT-prolonging drugs",
        "re_a":      re.compile(r'\b(amiodarone|sotalol|dofetilide|haloperidol|droperidol)\b', re.I),
        "re_b":      re.compile(r'\b(azithromycin|clarithromycin|fluoroquinolone|ciprofloxacin|levofloxacin|ondansetron)\b', re.I),
        "severity":  "high",
        "description": "QT-prolonging drug combination: risk of torsades de pointes / fatal arrhythmia",
    },
    {
        "name":      "ACE inhibitor / ARB + Potassium",
        "re_a":      re.compile(r'\b(ace inhibitor|arb|lisinopril|enalapril|losartan|valsartan|spironolactone)\b', re.I),
        "re_b":      re.compile(r'\b(potassium|kcl|potassium chloride|hyperkalemia)\b', re.I),
        "severity":  "high",
        "description": "ACE inhibitor/ARB + potassium supplement: risk of life-threatening hyperkalemia",
    },
    {
        "name":      "Opioid + Benzodiazepine",
        "re_a":      re.compile(r'\b(opioid|morphine|fentanyl|oxycodone|hydromorphone|codeine|hydrocodone)\b', re.I),
        "re_b":      re.compile(r'\b(benzodiazepine|diazepam|lorazepam|alprazolam|midazolam|clonazepam)\b', re.I),
        "severity":  "critical",
        "description": "Opioid + Benzodiazepine: FDA black box warning — risk of fatal respiratory depression",
    },
]

# ── LLM safety assessor (lazy, optional) ─────────────────────────────────────

_llm_safety = None


def _get_llm_safety():
    global _llm_safety
    if _llm_safety is not None:
        return None if _llm_safety == "unavailable" else _llm_safety

    from ingestion.config import get_settings
    cfg = get_settings()
    if not cfg.openai_api_key or cfg.openai_api_key.startswith("REPLACE"):
        _llm_safety = "unavailable"
        return None

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI
        from pydantic import BaseModel, Field

        class _AdditionalFlag(BaseModel):
            flag_type:   str
            severity:    str
            description: str

        class _SafetyJudgement(BaseModel):
            additional_flags:      list[_AdditionalFlag] = []
            requires_escalation:   bool
            escalation_reason:     str = ""
            clinical_disclaimer:   str

        llm = ChatOpenAI(
            model       = cfg.llm_model,
            temperature = 0,
            api_key     = cfg.openai_api_key,
        )
        _llm_safety = llm.with_structured_output(_SafetyJudgement)
    except Exception:
        _llm_safety = "unavailable"
        return None

    return _llm_safety


_SAFETY_SYSTEM = """\
You are a clinical safety officer for an enterprise healthcare AI platform.
Your role is to protect patients and clinicians by identifying safety concerns.

Review the clinical query, detected risk signals, and existing safety flags.

Escalate when:
  1. The query involves direct patient care decisions with life-threatening implications
  2. Information could cause harm even with good intent (e.g., dosing without context)
  3. High-risk medications are involved without appropriate clinical safeguards
  4. Emergency conditions require immediate clinical intervention, not AI advice

For clinical_disclaimer, write a single, actionable sentence appropriate to the risk level.
  Low risk:      "This information is for educational purposes; consult a licensed clinician."
  Medium risk:   "Clinical judgment required — verify dosing and interactions before use."
  High/Critical: "⚠️ HIGH-RISK CLINICAL CONTENT — review with a licensed physician or pharmacist before application."
"""


async def _llm_safety_check(
    query_text: str,
    risk_signals: list[str],
    existing_flags: list[dict],
) -> Optional[dict]:
    llm = _get_llm_safety()
    if llm is None:
        return None

    flags_summary = "; ".join(
        f"{f.get('flag_type')} [{f.get('severity')}]: {f.get('description', '')[:80]}"
        for f in existing_flags
    ) or "none detected"

    from langchain_core.messages import HumanMessage, SystemMessage
    try:
        result = await llm.ainvoke([
            SystemMessage(content=_SAFETY_SYSTEM),
            HumanMessage(content=(
                f"Clinical query: {query_text}\n"
                f"Detected risk signals: {', '.join(risk_signals) or 'none'}\n"
                f"Pattern-based safety flags: {flags_summary}"
            )),
        ])
        return {
            "additional_flags":    [f.__dict__ if hasattr(f, '__dict__') else dict(f) for f in result.additional_flags],
            "requires_escalation": result.requires_escalation,
            "escalation_reason":   result.escalation_reason,
            "clinical_disclaimer": result.clinical_disclaimer,
        }
    except Exception:
        return None


# ── Node 1: Detect all risk patterns ─────────────────────────────────────────

async def detect_risks_node(state: RAGState) -> dict:
    start      = time.monotonic()
    query_text = state.get("raw_query", "")
    raw_chunks = state.get("verified_chunks", []) or state.get("retrieved_chunks", [])

    chunks    = [RetrievedChunk(**c) for c in raw_chunks]
    all_texts = [query_text] + [c.content for c in chunks]
    combined  = " ".join(all_texts)

    flags: list[dict[str, Any]] = []

    # ── Emergency conditions ──────────────────────────────────────────────────
    emergency_hits = list({m.group().lower() for m in _EMERGENCY_RE.finditer(combined)})
    if emergency_hits:
        flags.append({
            "flag_type":             "emergency_condition",
            "severity":              "critical",
            "description":           f"Emergency clinical condition detected: {', '.join(emergency_hits[:5])}",
            "affected_terms":        emergency_hits,
            "recommendation":        "Do not rely on AI for emergency clinical decisions. Contact emergency services or a physician immediately.",
            "requires_human_review": True,
        })

    # ── High-risk drugs ───────────────────────────────────────────────────────
    drug_hits = list({m.group().lower() for m in _HIGH_RISK_DRUG_RE.finditer(combined)})
    if drug_hits:
        flags.append({
            "flag_type":             "high_risk_medication",
            "severity":              "high",
            "description":           f"Narrow therapeutic index or high-alert medication: {', '.join(drug_hits[:5])}",
            "affected_terms":        drug_hits,
            "recommendation":        "Dosing, monitoring, and administration must be verified by a clinical pharmacist or prescribing physician.",
            "requires_human_review": True,
        })

    # ── Dosing risk ───────────────────────────────────────────────────────────
    dose_hits = list({m.group().lower() for m in _DOSING_RISK_RE.finditer(combined)})
    if dose_hits:
        flags.append({
            "flag_type":             "dosing_risk",
            "severity":              "high",
            "description":           f"Dosing risk terms present: {', '.join(dose_hits[:5])}",
            "affected_terms":        dose_hits,
            "recommendation":        "Verify dose against current formulary and patient-specific factors (weight, renal function, age).",
            "requires_human_review": True,
        })

    # ── Pediatric dosing ──────────────────────────────────────────────────────
    ped_hits = list({m.group().lower() for m in _PEDIATRIC_RE.finditer(combined)})
    if ped_hits:
        flags.append({
            "flag_type":             "pediatric_population",
            "severity":              "high",
            "description":           "Pediatric or weight-based dosing context detected",
            "affected_terms":        ped_hits,
            "recommendation":        "Pediatric dosing requires specialist review. Consult pediatric formulary and attending physician.",
            "requires_human_review": True,
        })

    # ── Pregnancy / lactation ─────────────────────────────────────────────────
    preg_hits = list({m.group().lower() for m in _PREGNANCY_RE.finditer(combined)})
    if preg_hits:
        flags.append({
            "flag_type":             "pregnancy_lactation",
            "severity":              "medium",
            "description":           "Pregnancy or lactation context detected",
            "affected_terms":        preg_hits,
            "recommendation":        "Verify safety in pregnancy/lactation with current guidelines (FDA categories, LactMed).",
            "requires_human_review": False,
        })

    # ── Drug interactions ─────────────────────────────────────────────────────
    for interaction in _DRUG_INTERACTIONS:
        if interaction["re_a"].search(combined) and interaction["re_b"].search(combined):
            flags.append({
                "flag_type":             "drug_interaction",
                "severity":              interaction["severity"],
                "description":           interaction["description"],
                "interaction_name":      interaction["name"],
                "recommendation":        "Review this drug combination with a clinical pharmacist before prescribing.",
                "requires_human_review": interaction["severity"] in ("critical", "high"),
            })

    return {
        "safety_flags":  flags,
        "agent_timings": {"safety.detect_ms": (time.monotonic() - start) * 1000},
    }


# ── Node 2: Evaluate escalation + LLM deep check ─────────────────────────────

async def evaluate_escalation_node(state: RAGState) -> dict:
    start        = time.monotonic()
    flags        = state.get("safety_flags", [])
    query_text   = state.get("raw_query", "")
    risk_signals = state.get("query_risk_signals", [])

    # ── Rule-based escalation decision ───────────────────────────────────────
    critical_flags = [f for f in flags if f.get("severity") == "critical"]
    high_flags     = [f for f in flags if f.get("severity") == "high"]

    auto_escalate   = bool(critical_flags) or len(high_flags) >= 2
    escalation_reason: str = ""

    if critical_flags:
        escalation_reason = f"Critical risk: {critical_flags[0]['description']}"
    elif len(high_flags) >= 2:
        escalation_reason = f"Multiple high-risk signals ({len(high_flags)}): requires clinical review"

    # ── Optional LLM deep assessment for borderline cases ────────────────────
    llm_result: Optional[dict] = None
    if flags and not auto_escalate:   # only call LLM when outcome is uncertain
        llm_result = await _llm_safety_check(query_text, risk_signals, flags)

    if llm_result:
        # Merge LLM additional flags
        for af in llm_result.get("additional_flags", []):
            flags.append({
                "flag_type":             af.get("flag_type", "llm_detected"),
                "severity":              af.get("severity", "medium"),
                "description":           af.get("description", ""),
                "requires_human_review": af.get("severity") in ("critical", "high"),
                "source":                "llm",
            })
        if llm_result.get("requires_escalation"):
            auto_escalate     = True
            escalation_reason = llm_result.get("escalation_reason", escalation_reason)

    # ── Build clinical disclaimer ─────────────────────────────────────────────
    if llm_result and llm_result.get("clinical_disclaimer"):
        disclaimer = llm_result["clinical_disclaimer"]
    elif auto_escalate:
        disclaimer = (
            "⚠️ HIGH-RISK CLINICAL CONTENT — This response contains information about "
            "high-risk medications, emergency conditions, or critical dosing thresholds. "
            "Do not apply this information clinically without review by a licensed physician "
            "or clinical pharmacist."
        )
    elif flags:
        disclaimer = (
            "Clinical judgment required — verify dosing, interactions, and contraindications "
            "with current guidelines before clinical application."
        )
    else:
        disclaimer = (
            "This information is provided for educational purposes only and does not "
            "constitute medical advice. Consult a licensed healthcare professional."
        )

    # Add the disclaimer as a special informational flag
    flags.append({
        "flag_type":   "clinical_disclaimer",
        "severity":    "info",
        "description": disclaimer,
    })

    return {
        "safety_flags":        flags,
        "requires_escalation": auto_escalate,
        "escalation_reason":   escalation_reason if auto_escalate else None,
        "agent_timings":       {"safety.escalate_ms": (time.monotonic() - start) * 1000},
    }
