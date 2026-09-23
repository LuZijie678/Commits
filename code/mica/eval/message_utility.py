from __future__ import annotations

import re
from typing import Any


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
UNSUPPORTED_CLAIMS = {
    "security": ["security", "secure", "vulnerability"],
    "performance": ["performance", "latency", "throughput"],
    "memory leak": ["memory leak"],
    "race condition": ["race", "deadlock"],
    "bug fix": ["bug fix", "fix bug"],
    "refactor": ["refactor"],
    "breaking change": ["breaking change"],
}


def intent_coverage(plan: dict[str, Any], message: str) -> dict[str, Any]:
    intents = list(plan.get("intents", []))
    normalized_message = message.lower()
    covered = 0
    for intent in intents:
        cues = _intent_cues(intent)
        if cues and any(cue in normalized_message for cue in cues):
            covered += 1
    fraction = (covered / len(intents)) if intents else 0.0
    return {
        "covered_intent_fraction": fraction,
        "covered_intent_count": covered,
        "intent_count": len(intents),
        "proxy_only": True,
    }


def missing_intent_rate(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {"missing_intent_rate": 0.0}
    missing = [1.0 - float(row.get("covered_intent_fraction", 0.0)) for row in rows]
    return {"missing_intent_rate": sum(missing) / len(missing)}


def extra_intent_rate(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {"extra_intent_rate": 0.0}
    extras = [float(row.get("extra_intent_fraction", 0.0)) for row in rows]
    return {"extra_intent_rate": sum(extras) / len(extras)}


def hallucination_proxy(message: str, evidence_terms: list[str]) -> dict[str, Any]:
    tokens = [token.lower() for token in TOKEN_RE.findall(message)]
    evidence = {term.lower() for term in evidence_terms}
    unsupported = [token for token in tokens if token not in evidence]
    fraction = (len(unsupported) / len(tokens)) if tokens else 0.0
    return {
        "unsupported_term_fraction": fraction,
        "unsupported_terms": unsupported,
        "proxy_only": True,
    }


def specificity_proxy(message: str, evidence_terms: list[str]) -> dict[str, Any]:
    tokens = [token.lower() for token in TOKEN_RE.findall(message)]
    evidence = {term.lower() for term in evidence_terms}
    matched = [token for token in tokens if token in evidence]
    fraction = (len(matched) / len(tokens)) if tokens else 0.0
    return {
        "specificity_proxy": fraction,
        "matched_terms": matched,
        "proxy_only": True,
    }


def extract_evidence_terms(plan: dict[str, Any]) -> set[str]:
    terms: set[str] = set()
    for intent in plan.get("intents", []):
        for key in ("subject", "body", "type", "scope"):
            value = intent.get(key)
            if value:
                terms.update(token.lower() for token in TOKEN_RE.findall(str(value)))
        for unit in intent.get("evidence_units", []):
            if isinstance(unit, dict):
                file_path = str(unit.get("file_path", ""))
                file_role = str(unit.get("file_role", ""))
                identifiers = unit.get("changed_identifiers", []) or []
            else:
                file_path = str(getattr(unit, "file_path", ""))
                file_role = str(getattr(unit, "file_role", ""))
                identifiers = getattr(unit, "changed_identifiers", []) or []
            terms.update(token.lower() for token in TOKEN_RE.findall(file_path))
            terms.update(token.lower() for token in TOKEN_RE.findall(file_role))
            terms.update(str(item).lower() for item in identifiers if item)
    for term in plan.get("evidence_terms", []):
        terms.add(str(term).lower())
    return terms


def compute_entity_copy_rate(message: str, evidence_terms: set[str]) -> dict[str, Any]:
    tokens = [token.lower() for token in TOKEN_RE.findall(message)]
    copied = [token for token in tokens if token in evidence_terms]
    rate = (len(copied) / len(tokens)) if tokens else 0.0
    return {"entity_copy_rate": rate, "copied_terms": copied}


def compute_entity_coverage_loss_or_score(message: str, evidence_terms: set[str], required_terms: set[str] | None = None) -> dict[str, Any]:
    tokens = {token.lower() for token in TOKEN_RE.findall(message)}
    required = {term.lower() for term in (required_terms or evidence_terms)}
    if not required:
        return {"required_term_coverage": 1.0, "missing_required_terms": [], "loss_or_penalty": 0.0, "proxy_only": True}
    matched = sorted(term for term in required if term in tokens)
    missing = sorted(term for term in required if term not in tokens)
    coverage = len(matched) / len(required)
    return {
        "required_term_coverage": coverage,
        "matched_required_terms": matched,
        "missing_required_terms": missing,
        "loss_or_penalty": 1.0 - coverage,
        "proxy_only": True,
    }


def compute_unsupported_claim_flags(message: str, plan: dict[str, Any]) -> dict[str, Any]:
    lowered = message.lower()
    evidence_terms = extract_evidence_terms(plan)
    flags = {}
    for claim_name, triggers in UNSUPPORTED_CLAIMS.items():
        claim_present = any(trigger in lowered for trigger in triggers)
        claim_supported = any(trigger in evidence_terms for trigger in triggers)
        flags[claim_name] = bool(claim_present and not claim_supported)
    return {"unsupported_claims": flags}


def check_message_supported_by_evidence(message: str, plan: dict[str, Any]) -> dict[str, Any]:
    evidence_terms = extract_evidence_terms(plan)
    hallucination = hallucination_proxy(message, sorted(evidence_terms))
    flags = compute_unsupported_claim_flags(message, plan)
    supported = hallucination["unsupported_term_fraction"] < 0.5 and not any(flags["unsupported_claims"].values())
    return {
        "supported_by_evidence": supported,
        "unsupported_term_fraction": hallucination["unsupported_term_fraction"],
        "unsupported_claims": flags["unsupported_claims"],
    }


def compare_oracle_vs_predicted_rendering(oracle_rows: list[dict[str, Any]], predicted_rows: list[dict[str, Any]]) -> dict[str, Any]:
    oracle_by_sample = {str(row.get("sample_id")): row for row in oracle_rows}
    deltas_coverage: list[float] = []
    deltas_unsupported: list[float] = []
    for predicted in predicted_rows:
        sample_id = str(predicted.get("sample_id"))
        oracle = oracle_by_sample.get(sample_id)
        if oracle is None:
            continue
        deltas_coverage.append(float(predicted.get("covered_intent_fraction", 0.0)) - float(oracle.get("covered_intent_fraction", 0.0)))
        deltas_unsupported.append(float(predicted.get("unsupported_term_fraction", 0.0)) - float(oracle.get("unsupported_term_fraction", 0.0)))
    paired_count = len(deltas_coverage)
    return {
        "paired_count": paired_count,
        "delta_covered_intent_fraction_mean": (sum(deltas_coverage) / paired_count) if paired_count else 0.0,
        "delta_unsupported_term_fraction_mean": (sum(deltas_unsupported) / paired_count) if paired_count else 0.0,
        "proxy_not_human_eval": True,
    }


def build_renderer_ablation_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    coverage_values = [float(row.get("covered_intent_fraction", 0.0)) for row in rows]
    unsupported_values = [float(row.get("unsupported_term_fraction", 0.0)) for row in rows]
    return {
        "row_count": len(rows),
        "mean_covered_intent_fraction": (sum(coverage_values) / len(coverage_values)) if coverage_values else 0.0,
        "mean_unsupported_term_fraction": (sum(unsupported_values) / len(unsupported_values)) if unsupported_values else 0.0,
        "proxy_not_human_eval": True,
    }


def _intent_cues(intent: dict[str, Any]) -> list[str]:
    cues: list[str] = []
    for key in ("subject", "body", "type", "scope"):
        value = intent.get(key)
        if value:
            cues.append(str(value).lower())
    for key in ("core_units", "support_units", "auxiliary_units"):
        for value in intent.get(key, []) or []:
            cues.append(str(value).lower())
    return cues
