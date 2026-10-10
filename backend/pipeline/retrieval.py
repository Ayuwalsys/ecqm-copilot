"""
retrieval.py — Section-aware chunker + context pack builder.
"""
import re
from typing import Any

CLINICAL_SECTIONS = [
    "chief complaint", "history of present illness", "hpi",
    "past medical history", "medications", "allergies",
    "review of systems", "physical examination", "assessment",
    "plan", "assessment and plan", "discharge summary",
    "laboratory", "labs", "procedures", "impression",
]

# Which sections matter per measure (extend as measures are added)
MEASURE_SECTION_MAP = {
    "diabetes_hba1c": ["laboratory", "labs", "assessment", "plan", "assessment and plan"],
    "ami_8a": ["procedures", "assessment", "plan", "discharge summary", "history of present illness"],
}


def build_context_pack(bundle_meta: dict, measure_id: str) -> dict:
    """Build a context pack: structured facts + relevant note snippets."""
    resources = bundle_meta["resources"]
    notes = bundle_meta["notes"]

    structured = _extract_structured_facts(resources, measure_id)
    snippets = _retrieve_note_snippets(notes, measure_id)

    return {
        "measure_id": measure_id,
        "structured_facts": structured,
        "note_snippets": snippets,
        "bundle_hash": bundle_meta["bundle_hash"],
    }


def _extract_structured_facts(resources: dict, measure_id: str) -> dict:
    facts: dict = {}

    # Patient demographics
    for patient in resources.get("Patient", []):
        facts["patient_id"] = patient.get("id")
        facts["birth_date"] = patient.get("birthDate")
        facts["gender"] = patient.get("gender")

    # Conditions
    facts["conditions"] = []
    for cond in resources.get("Condition", []):
        facts["conditions"].append({
            "code": _first_coding(cond.get("code", {})),
            "onset": cond.get("onsetDateTime"),
            "clinical_status": cond.get("clinicalStatus", {}).get("coding", [{}])[0].get("code"),
        })

    # Observations (lab values, vitals)
    facts["observations"] = []
    for obs in resources.get("Observation", []):
        value = obs.get("valueQuantity") or obs.get("valueCodeableConcept") or {}
        facts["observations"].append({
            "code": _first_coding(obs.get("code", {})),
            "value": value.get("value"),
            "unit": value.get("unit"),
            "effective_date": obs.get("effectiveDateTime"),
            "status": obs.get("status"),
        })

    # Medications
    facts["medications"] = []
    for med in resources.get("MedicationRequest", []):
        facts["medications"].append({
            "code": _first_coding(med.get("medicationCodeableConcept", {})),
            "status": med.get("status"),
            "authored_on": med.get("authoredOn"),
        })

    # Encounter timing
    facts["encounters"] = []
    for enc in resources.get("Encounter", []):
        period = enc.get("period", {})
        facts["encounters"].append({
            "id": enc.get("id"),
            "status": enc.get("status"),
            "start": period.get("start"),
            "end": period.get("end"),
            "class": enc.get("class", {}).get("code"),
        })

    return facts


def _retrieve_note_snippets(notes: list, measure_id: str) -> list:
    target_sections = MEASURE_SECTION_MAP.get(measure_id, CLINICAL_SECTIONS[:4])
    snippets = []

    for note in notes:
        sections = _chunk_by_section(note["text"])
        for section_name, section_text in sections.items():
            if any(t in section_name.lower() for t in target_sections):
                snippets.append({
                    "doc_id": note["doc_id"],
                    "section": section_name,
                    "text": section_text[:800],  # cap at 800 chars per section
                    "char_start": note["text"].lower().find(section_name.lower()),
                })

    return snippets


def _chunk_by_section(text: str) -> dict:
    """Split clinical note text into named sections."""
    pattern = r"(?i)(?:^|\n)(" + "|".join(re.escape(s) for s in CLINICAL_SECTIONS) + r")[:\s]*\n"
    parts = re.split(pattern, text)
    sections: dict = {}

    if len(parts) <= 1:
        sections["full_note"] = text
        return sections

    i = 1
    while i < len(parts) - 1:
        section_name = parts[i].strip().lower()
        section_body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        sections[section_name] = section_body
        i += 2

    return sections


def _first_coding(codeable_concept: dict) -> dict:
    codings = codeable_concept.get("coding", [{}])
    if codings:
        c = codings[0]
        return {"system": c.get("system"), "code": c.get("code"), "display": c.get("display")}
    return {"display": codeable_concept.get("text", "")}
