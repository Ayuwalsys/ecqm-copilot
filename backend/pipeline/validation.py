"""
validation.py — Hallucination guard, type checks, PHI sweep on draft.
"""
import re

PHI_SWEEP_PATTERNS = [
    r"\b\d{3}-\d{2}-\d{4}\b",
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
]

REQUIRED_EVIDENCE_FIELDS = {
    "diabetes_hba1c": ["hba1c_value"],
    "ami_8a": ["pci_time_minutes"],
}


def validate_draft(draft: dict) -> dict:
    """Run all safety checks. Returns draft with safe=True/False and issues list."""
    issues = []
    measure_id = draft.get("measure_id", "")

    # 1. Hallucination guard — numerator/denominator claims must have evidence spans
    issues += _check_evidence_spans(draft, measure_id)

    # 2. PHI sweep on reasoning text
    issues += _phi_sweep(draft)

    # 3. Parse error guard
    if draft.get("parse_error"):
        issues.append({
            "type": "parse_error",
            "severity": "critical",
            "message": "LLM response could not be parsed as JSON",
        })

    # 4. Confidence floor — flag low-confidence spans
    issues += _check_confidence(draft)

    draft["validation_issues"] = issues
    critical = [i for i in issues if i.get("severity") == "critical"]
    draft["safe"] = len(critical) == 0

    return draft


def _check_evidence_spans(draft: dict, measure_id: str) -> list:
    issues = []
    required = REQUIRED_EVIDENCE_FIELDS.get(measure_id, [])
    spans = draft.get("evidence_spans", [])
    spanned_fields = {s.get("field") for s in spans}

    for field in required:
        if field not in spanned_fields and draft.get(field) is not None:
            issues.append({
                "type": "missing_evidence_span",
                "severity": "critical",
                "field": field,
                "message": f"Field '{field}' has a value but no evidence span — possible hallucination",
            })

    if not spans and (draft.get("numerator") or draft.get("denominator")):
        issues.append({
            "type": "no_evidence_spans",
            "severity": "critical",
            "message": "Numerator/denominator set but no evidence spans provided",
        })

    return issues


def _phi_sweep(draft: dict) -> list:
    issues = []
    text_to_check = str(draft.get("reasoning", "")) + str(draft.get("evidence_spans", ""))
    for pattern in PHI_SWEEP_PATTERNS:
        if re.search(pattern, text_to_check):
            issues.append({
                "type": "phi_detected",
                "severity": "critical",
                "message": "Possible PHI pattern detected in draft reasoning or evidence spans",
            })
    return issues


def _check_confidence(draft: dict) -> list:
    issues = []
    for span in draft.get("evidence_spans", []):
        conf = span.get("confidence", 1.0)
        if conf < 0.7:
            issues.append({
                "type": "low_confidence_span",
                "severity": "warning",
                "field": span.get("field"),
                "confidence": conf,
                "message": f"Evidence span for '{span.get('field')}' has low confidence ({conf:.0%})",
            })
    return issues
