"""
LLM classification prompt, Pydantic response schema, and rule-based fallback
for the Planner Agent's query classification node.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ingestion.config import get_settings

# ── LLM response schema ───────────────────────────────────────────────────────

class QueryClassification(BaseModel):
    """Structured output from the LLM query classifier."""

    intent: Literal[
        "diagnosis", "treatment", "drug_info", "protocol", "research", "general"
    ] = Field(description="Primary clinical intent of the query")

    specialty: Literal[
        "cardiology", "oncology", "neurology", "endocrinology",
        "infectious_disease", "pharmacology", "radiology",
        "surgery", "pediatrics", "general",
    ] = Field(description="Primary medical specialty most relevant to this query")

    risk_signals: list[str] = Field(
        default_factory=list,
        description=(
            "High-stakes clinical terms detected in the query that require "
            "careful safety review (e.g. dosing, overdose, contraindication, "
            "drug interaction, emergency, allergy, maximum dose, toxicity)"
        ),
    )

    include_pubmed: bool = Field(
        default=False,
        description="True when recent research literature would materially improve the answer",
    )


# ── Prompt templates ──────────────────────────────────────────────────────────

_SYSTEM = """\
You are a clinical query classifier for an enterprise healthcare knowledge platform.
Analyze the query and return a structured classification.

Intent definitions:
  diagnosis  — identifying a disease, condition, or differential diagnosis
  treatment  — therapeutic approaches, medications, or interventions
  drug_info  — drug dosing, interactions, contraindications, or pharmacology
  protocol   — clinical protocols, guidelines, care pathways, or SOPs
  research   — scientific evidence, clinical trials, or literature review
  general    — general medical information, definitions, or explanations

Medical specialties:
  cardiology, oncology, neurology, endocrinology, infectious_disease,
  pharmacology, radiology, surgery, pediatrics, general

Risk signals are terms suggesting high-stakes clinical decisions that require
safety review before the answer is delivered to the clinician.
Examples: dosing, overdose, contraindication, drug interaction, allergy,
emergency, lethal dose, maximum dose, renal adjustment, hepatic adjustment,
pediatric dosing, toxicity, black box warning, narrow therapeutic index.

Set include_pubmed=true when: the intent is research or treatment AND the user
would benefit from recent primary literature or systematic reviews.
"""

_HUMAN = "Query: {query_text}"


def build_messages(query_text: str) -> list:
    return [
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=_HUMAN.format(query_text=query_text)),
    ]


# ── Lazy LLM initialisation ───────────────────────────────────────────────────

_llm_classifier = None


def get_llm_classifier():
    """
    Returns a LangChain structured-output chain, or None if:
      - langchain_openai is not installed
      - OPENAI_API_KEY is missing / placeholder
    In either case the caller should use classify_rule_based() as fallback.
    """
    global _llm_classifier
    if _llm_classifier is not None:
        return _llm_classifier

    cfg = get_settings()
    if not cfg.openai_api_key or cfg.openai_api_key.startswith("REPLACE"):
        return None

    try:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model       = cfg.llm_model,
            temperature = 0,
            api_key     = cfg.openai_api_key,
        )
        _llm_classifier = llm.with_structured_output(QueryClassification)
    except Exception:
        _llm_classifier = None

    return _llm_classifier


# ── Rule-based fallback ───────────────────────────────────────────────────────

_DRUG_RE      = re.compile(r'\b(dose|dosing|mg|mcg|drug|medication|interaction|contraindication|pharmacol|rxnorm|prescription)\b', re.I)
_TREATMENT_RE = re.compile(r'\b(treat|therap|intervention|management|prescri|medic)\b', re.I)
_DIAGNOSIS_RE = re.compile(r'\b(diagnos|symptom|present|manifest|differential|icd|sign)\b', re.I)
_PROTOCOL_RE  = re.compile(r'\b(protocol|guideline|pathway|procedure|sop|standard of care|algorithm|checklist)\b', re.I)
_RESEARCH_RE  = re.compile(r'\b(study|research|evidence|trial|paper|systematic|meta.analysis|literature|review)\b', re.I)

_RISK_RE = re.compile(
    r'\b(dose|dosing|overdose|contraindication|emergency|interaction|allerg|lethal|'
    r'critical|pediatric dose|renal|hepatic|maximum dose|toxicity|black.?box|narrow.?therapeutic)\b',
    re.I,
)

_SPECIALTY_RE = {
    "cardiology":         re.compile(r'\b(cardiac|heart|coronary|arrhythmia|hypertension|ecg|ekg)\b', re.I),
    "oncology":           re.compile(r'\b(cancer|tumor|chemotherapy|oncol|malignant|metastasis)\b', re.I),
    "neurology":          re.compile(r'\b(neuro|stroke|seizure|epileps|dementia|parkinson|alzheimer|ms)\b', re.I),
    "pharmacology":       re.compile(r'\b(drug|medication|pharma|dose|dosing|interaction|contraindication)\b', re.I),
    "infectious_disease": re.compile(r'\b(infect|bacteria|virus|antibiotic|sepsis|hiv|covid|pneumonia)\b', re.I),
    "endocrinology":      re.compile(r'\b(diabetes|insulin|thyroid|hormone|endocrin|glucose)\b', re.I),
    "pediatrics":         re.compile(r'\b(pediatric|child|infant|neonatal|newborn|adolescent)\b', re.I),
}


def classify_rule_based(query_text: str) -> QueryClassification:
    """Keyword-based fallback when LLM is unavailable."""
    if _DRUG_RE.search(query_text):
        intent = "drug_info"
    elif _TREATMENT_RE.search(query_text):
        intent = "treatment"
    elif _DIAGNOSIS_RE.search(query_text):
        intent = "diagnosis"
    elif _PROTOCOL_RE.search(query_text):
        intent = "protocol"
    elif _RESEARCH_RE.search(query_text):
        intent = "research"
    else:
        intent = "general"

    specialty = "general"
    for sp, pattern in _SPECIALTY_RE.items():
        if pattern.search(query_text):
            specialty = sp
            break

    risk_signals = list({m.lower() for m in _RISK_RE.findall(query_text)})
    include_pubmed = intent in ("research", "treatment")

    return QueryClassification(
        intent         = intent,
        specialty      = specialty,
        risk_signals   = risk_signals,
        include_pubmed = include_pubmed,
    )
