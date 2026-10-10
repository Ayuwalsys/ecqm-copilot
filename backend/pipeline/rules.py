"""
rules.py — Deterministic eCQM logic layer.
Loads measure config from measures/*.yaml and applies time/value/threshold checks.
"""
import os, yaml
from pathlib import Path

MEASURES_DIR = Path(__file__).parent.parent / "measures"


def apply_measure_logic(extraction: dict, measure_id: str) -> dict:
    """Apply deterministic rules on top of LLM extraction."""
    config = _load_measure_config(measure_id)
    draft = dict(extraction)
    draft["logic_version"] = config.get("version", "0.1")
    draft["measure_id"] = measure_id
    draft["populations"] = []

    checks = []

    if measure_id == "diabetes_hba1c":
        checks = _apply_hba1c_rules(draft, config)
    elif measure_id == "ami_8a":
        checks = _apply_ami_rules(draft, config)
    else:
        checks.append({"rule": "no_rule_set", "passed": None, "note": f"No rules for {measure_id}"})

    draft["rule_checks"] = checks
    draft["auto_suggest"] = all(c["passed"] is not False for c in checks)

    # Build FHIR-style populations list
    if draft.get("denominator"):
        draft["populations"].append({"code": "denominator", "count": 1})
    if draft.get("numerator"):
        draft["populations"].append({"code": "numerator", "count": 1})
    if draft.get("exclusion"):
        draft["populations"].append({"code": "denominator-exclusion", "count": 1})

    return draft


def _apply_hba1c_rules(draft: dict, config: dict) -> list:
    checks = []
    threshold = config.get("numerator_threshold", 9.0)
    hba1c = draft.get("hba1c_value")

    # Rule 1: HbA1c value type check
    if hba1c is not None:
        try:
            val = float(hba1c)
            checks.append({"rule": "hba1c_numeric", "passed": True, "value": val})
            # Rule 2: Threshold check
            if val > threshold:
                checks.append({"rule": "hba1c_above_threshold", "passed": True,
                               "note": f"{val} > {threshold}"})
                draft["numerator"] = True
            else:
                checks.append({"rule": "hba1c_above_threshold", "passed": False,
                               "note": f"{val} ≤ {threshold}"})
                draft["numerator"] = False
        except (ValueError, TypeError):
            checks.append({"rule": "hba1c_numeric", "passed": False, "note": "Non-numeric HbA1c value"})
    else:
        # No result counts as numerator (poor control by absence)
        checks.append({"rule": "hba1c_missing", "passed": True, "note": "No HbA1c → numerator"})
        draft["numerator"] = True

    return checks


def _apply_ami_rules(draft: dict, config: dict) -> list:
    checks = []
    max_minutes = config.get("pci_window_minutes", 90)
    pci_minutes = draft.get("pci_time_minutes")

    if pci_minutes is not None:
        try:
            mins = float(pci_minutes)
            checks.append({"rule": "pci_time_numeric", "passed": True, "value": mins})
            if mins <= max_minutes:
                checks.append({"rule": "pci_within_window", "passed": True,
                               "note": f"{mins} min ≤ {max_minutes} min threshold"})
                draft["numerator"] = True
            else:
                checks.append({"rule": "pci_within_window", "passed": False,
                               "note": f"{mins} min > {max_minutes} min threshold"})
                draft["numerator"] = False
        except (ValueError, TypeError):
            checks.append({"rule": "pci_time_numeric", "passed": False, "note": "Non-numeric PCI time"})
    else:
        checks.append({"rule": "pci_time_missing", "passed": False, "note": "No PCI time found"})
        draft["numerator"] = False

    return checks


def _load_measure_config(measure_id: str) -> dict:
    config_path = MEASURES_DIR / f"{measure_id}.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}
