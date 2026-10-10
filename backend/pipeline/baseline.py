"""
baseline.py — Rules-only measure extraction, no LLM in the loop.

Pulls denominator/numerator/exclusion facts directly from structured FHIR
resources (Condition, Observation, Procedure, Encounter) using each measure's
value sets in measures/*.yaml. Used to establish the Phase 1 baseline F1
(deterministic floor that the RAG+LLM pipeline in Phase 2 must beat).
"""
from datetime import datetime
from typing import Optional

from pipeline.rules import _load_measure_config, apply_measure_logic


def extract_structured(resources: dict, measure_id: str) -> dict:
    """Deterministically derive denominator/numerator/exclusion inputs from FHIR resources."""
    config = _load_measure_config(measure_id)
    if measure_id == "diabetes_hba1c":
        return _extract_hba1c(resources, config)
    if measure_id == "ami_8a":
        return _extract_ami(resources, config)
    raise ValueError(f"No structured extractor for measure: {measure_id}")


def run_baseline(resources: dict, measure_id: str) -> dict:
    """Structured extraction + rules.py logic, entirely without an LLM."""
    structured = extract_structured(resources, measure_id)
    return apply_measure_logic(structured, measure_id)


def _extract_hba1c(resources: dict, config: dict) -> dict:
    patient = _first(resources.get("Patient", []))
    encounter = _first(resources.get("Encounter", []))
    conditions = resources.get("Condition", [])
    observations = resources.get("Observation", [])

    age_min, age_max = config.get("age_range", [18, 75])
    diabetes_prefixes = config["value_sets"]["diabetes"]
    hba1c_codes = set(config["value_sets"]["hba1c_loinc"])
    qualifying_class = config.get("qualifying_visit_encounter_class", "AMB")
    exclusion_sets = config.get("exclusion_value_sets", {})

    age = _age_at(patient, encounter)
    has_diabetes_dx = _has_matching_condition(conditions, diabetes_prefixes, prefix=True)
    has_qualifying_visit = _encounter_class_is(encounter, qualifying_class)

    denominator = bool(
        has_diabetes_dx and has_qualifying_visit and age is not None and age_min <= age <= age_max
    )

    exclusion, exclusion_reason = _check_condition_exclusions(conditions, exclusion_sets)

    hba1c_obs = _most_recent_matching_observation(observations, hba1c_codes)
    hba1c_value = hba1c_obs["value"] if hba1c_obs else None
    hba1c_date = hba1c_obs["date"] if hba1c_obs else None

    return {
        "denominator": denominator,
        "exclusion": exclusion,
        "exclusion_reason": exclusion_reason,
        "hba1c_value": hba1c_value,
        "hba1c_date": hba1c_date,
        "evidence_spans": [],
        "reasoning": "Derived deterministically from structured FHIR resources (rules-only baseline).",
    }


def _extract_ami(resources: dict, config: dict) -> dict:
    patient = _first(resources.get("Patient", []))
    encounter = _first(resources.get("Encounter", []))
    conditions = resources.get("Condition", [])
    procedures = resources.get("Procedure", [])

    age_min = config.get("age_min", 18)
    ami_prefixes = config["value_sets"]["ami_icd10"]
    pci_codes = set(config["value_sets"]["pci_cpt"])
    hospitalized_class = config.get("hospitalized_encounter_class", "IMP")
    transfer_code = config.get("transfer_admit_source_code", "hosp-trans")
    exclusion_sets = config.get("exclusion_value_sets", {})

    age = _age_at(patient, encounter)
    has_ami_dx = _has_matching_condition(conditions, ami_prefixes, prefix=True)
    is_hospitalized = _encounter_class_is(encounter, hospitalized_class)
    pci = _first_matching_procedure(procedures, pci_codes)
    pci_performed = pci is not None

    denominator = bool(
        has_ami_dx and pci_performed and is_hospitalized and age is not None and age >= age_min
    )

    exclusion, exclusion_reason = _check_condition_exclusions(conditions, exclusion_sets)

    if not exclusion and pci and encounter:
        arrival = _parse_dt(encounter.get("period", {}).get("start"))
        pci_time = _parse_dt(pci.get("performedDateTime"))
        if arrival and pci_time and pci_time < arrival:
            exclusion, exclusion_reason = True, "pci_prior_to_arrival"

    if not exclusion and encounter:
        admit_source = (
            encounter.get("hospitalization", {}).get("admitSource", {}).get("coding", [{}])[0].get("code")
        )
        if admit_source == transfer_code:
            exclusion, exclusion_reason = True, "transfer_from_other_facility_with_pci"

    pci_time_minutes = None
    arrival_time = pci_time_str = None
    if pci and encounter:
        arrival = _parse_dt(encounter.get("period", {}).get("start"))
        pci_time = _parse_dt(pci.get("performedDateTime"))
        arrival_time = encounter.get("period", {}).get("start")
        pci_time_str = pci.get("performedDateTime")
        if arrival and pci_time:
            pci_time_minutes = round((pci_time - arrival).total_seconds() / 60)

    return {
        "denominator": denominator,
        "exclusion": exclusion,
        "exclusion_reason": exclusion_reason,
        "pci_time_minutes": pci_time_minutes,
        "arrival_time": arrival_time,
        "pci_time": pci_time_str,
        "evidence_spans": [],
        "reasoning": "Derived deterministically from structured FHIR resources (rules-only baseline).",
    }


# ── helpers ──────────────────────────────────────────────────────────────

def _first(items: list) -> Optional[dict]:
    return items[0] if items else None


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_at(patient: Optional[dict], encounter: Optional[dict]) -> Optional[int]:
    if not patient or not patient.get("birthDate"):
        return None
    reference = None
    if encounter:
        reference = _parse_dt(encounter.get("period", {}).get("start"))
    birth = _parse_dt(patient["birthDate"])
    if not birth:
        return None
    reference = reference or datetime.now(birth.tzinfo)
    years = reference.year - birth.year
    if (reference.month, reference.day) < (birth.month, birth.day):
        years -= 1
    return years


def _has_matching_condition(conditions: list, code_prefixes: list, prefix: bool = True) -> bool:
    for cond in conditions:
        for coding in cond.get("code", {}).get("coding", []):
            code = coding.get("code", "")
            if prefix and any(code.startswith(p) for p in code_prefixes):
                return True
            if not prefix and code in code_prefixes:
                return True
    return False


def _encounter_class_is(encounter: Optional[dict], class_code: str) -> bool:
    if not encounter:
        return False
    return encounter.get("class", {}).get("code") == class_code


def _first_matching_procedure(procedures: list, cpt_codes: set) -> Optional[dict]:
    for proc in procedures:
        for coding in proc.get("code", {}).get("coding", []):
            if coding.get("code") in cpt_codes:
                return proc
    return None


def _most_recent_matching_observation(observations: list, loinc_codes: set) -> Optional[dict]:
    matches = []
    for obs in observations:
        for coding in obs.get("code", {}).get("coding", []):
            if coding.get("code") in loinc_codes:
                value = (obs.get("valueQuantity") or {}).get("value")
                date = obs.get("effectiveDateTime")
                if value is not None:
                    matches.append({"value": value, "date": date, "_dt": _parse_dt(date)})
                break
    if not matches:
        return None
    matches.sort(key=lambda m: m["_dt"] or datetime.min.replace(tzinfo=None), reverse=True)
    return matches[0]


def _check_condition_exclusions(conditions: list, exclusion_sets: dict):
    for reason, codes in exclusion_sets.items():
        if _has_matching_condition(conditions, codes, prefix=True):
            return True, reason
    return False, None
