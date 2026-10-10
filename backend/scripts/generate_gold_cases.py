"""
generate_gold_cases.py — Synthetic gold-label case generator (Phase 1).

Produces 100-150 FHIR bundles per measure with known denominator/numerator/
exclusion labels, all validated against the locked bundle schema
(schemas/fhir_bundle.schema.v1.0.yaml). Zero real PHI — every value is
synthetically generated.

A deliberate fraction of cases are "gap" cases: the clinically true fact
(diagnosis, lab value, or exclusion) is documented only in the free-text
note, not in a structured resource. The rules-only baseline in
pipeline/baseline.py reads structured resources only, so it is *expected*
to mislabel these — that's what makes the recorded baseline F1 meaningful
as a floor for the Phase 2 RAG+LLM pipeline to beat.

Usage:
    python -m scripts.generate_gold_cases
"""
import json
import random
from pathlib import Path

from schemas.lock import validate_bundle

SEED = 42
OUT_DIR = Path(__file__).parent.parent / "data" / "synthetic" / "gold"

DIABETES_COUNTS = {
    "numerator_true_high": 30,
    "numerator_false_controlled": 25,
    "numerator_true_missing": 10,
    "denominator_false_age": 10,
    "denominator_false_no_dx": 10,
    "denominator_false_no_visit": 8,
    "exclusion_hospice": 7,
    "exclusion_pregnancy": 7,
    "exclusion_frailty": 6,
    "gap_dx_note_only": 8,
    "gap_hba1c_good_control_note_only": 6,
    "gap_exclusion_note_only": 3,
}

AMI_COUNTS = {
    "numerator_true_fast_pci": 30,
    "numerator_false_slow_pci": 25,
    "denominator_false_no_ami_dx": 10,
    "denominator_false_no_pci": 10,
    "denominator_false_not_hospitalized": 8,
    "denominator_false_age": 8,
    "exclusion_comfort_measures": 8,
    "exclusion_transfer": 8,
    "exclusion_pci_prior_to_arrival": 8,
    "gap_ami_dx_note_only": 6,
    "gap_pci_time_note_only": 6,
    "gap_exclusion_note_only": 3,
}

FIRST_NAMES = ["Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Drew", "Sam", "Robin"]


# ── FHIR resource builders ──────────────────────────────────────────────

def patient(rng, pid, age_years, gender=None):
    birth_year = 2024 - age_years
    birth = f"{birth_year}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
    return {"resourceType": "Patient", "id": pid, "birthDate": birth,
            "gender": gender or rng.choice(["male", "female"])}


def encounter(eid, start, end, enc_class, admit_source=None):
    res = {
        "resourceType": "Encounter", "id": eid, "status": "finished",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": enc_class},
        "period": {"start": start, "end": end},
    }
    if admit_source:
        res["hospitalization"] = {
            "admitSource": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/admit-source",
                "code": admit_source,
            }]}
        }
    return res


def condition(cid, code, display, onset):
    return {
        "resourceType": "Condition", "id": cid,
        "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": code, "display": display}],
                  "text": display},
        "clinicalStatus": {"coding": [{"code": "active"}]},
        "onsetDateTime": onset,
    }


def observation(oid, code, display, value, unit, date):
    return {
        "resourceType": "Observation", "id": oid, "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": code, "display": display}], "text": display},
        "effectiveDateTime": date,
        "valueQuantity": {"value": value, "unit": unit, "system": "http://unitsofmeasure.org", "code": unit},
    }


def procedure(pid, code, display, performed_dt):
    return {
        "resourceType": "Procedure", "id": pid, "status": "completed",
        "code": {"coding": [{"system": "http://www.ama-assn.org/go/cpt", "code": code, "display": display}],
                  "text": display},
        "performedDateTime": performed_dt,
    }


def document_reference(doc_id, doc_type, text):
    return {
        "resourceType": "DocumentReference", "id": doc_id, "status": "current",
        "type": {"text": doc_type},
        "content": [{"attachment": {"data": text}}],
    }


def bundle(bundle_id, resources):
    return {"resourceType": "Bundle", "id": bundle_id, "type": "collection",
            "entry": [{"resource": r} for r in resources]}


# ── diabetes_hba1c case builder ─────────────────────────────────────────

def build_diabetes_case(rng, case_id, case_type):
    name = rng.choice(FIRST_NAMES)
    age = rng.randint(30, 70)
    month, day = rng.randint(1, 11), rng.randint(1, 28)
    visit_date = f"2024-{month:02d}-{day:02d}"
    enc_start = f"{visit_date}T09:00:00Z"
    enc_end = f"{visit_date}T10:00:00Z"

    resources = [patient(rng, f"pt-{case_id}", age)]
    note_lines = [f"ASSESSMENT AND PLAN:\n{name} is a {age}-year-old patient presenting for follow-up."]

    enc_class = "AMB"
    dx_in_structured = True
    hba1c_in_structured = True
    hba1c_value = round(rng.uniform(6.0, 8.9), 1)
    exclusion_code = None
    gold = {"denominator": None, "numerator": None, "exclusion": False, "exclusion_reason": None}

    if case_type == "numerator_true_high":
        hba1c_value = round(rng.uniform(9.1, 14.0), 1)
        gold.update(denominator=True, numerator=True)
    elif case_type == "numerator_false_controlled":
        hba1c_value = round(rng.uniform(6.0, 9.0), 1)
        gold.update(denominator=True, numerator=(hba1c_value > 9.0))
    elif case_type == "numerator_true_missing":
        hba1c_in_structured = False
        note_lines.append("LABORATORY:\nNo HbA1c on file for this measurement period.")
        gold.update(denominator=True, numerator=True)
    elif case_type == "denominator_false_age":
        age = rng.choice([12, 16, 78, 82])
        resources[0] = patient(rng, f"pt-{case_id}", age)
        gold.update(denominator=False, numerator=None)
    elif case_type == "denominator_false_no_dx":
        dx_in_structured = False
        gold.update(denominator=False, numerator=None)
    elif case_type == "denominator_false_no_visit":
        enc_class = "EMER"
        gold.update(denominator=False, numerator=None)
    elif case_type in ("exclusion_hospice", "exclusion_pregnancy", "exclusion_frailty"):
        exclusion_code = {"exclusion_hospice": "Z51.5", "exclusion_pregnancy": "Z33.1",
                           "exclusion_frailty": "R54"}[case_type]
        gold.update(denominator=True, exclusion=True, exclusion_reason=case_type.replace("exclusion_", ""))
    elif case_type == "gap_dx_note_only":
        dx_in_structured = False
        note_lines.append(f"HISTORY OF PRESENT ILLNESS:\n{name} has a documented history of type 2 diabetes "
                           "managed with metformin, per outside records not yet coded in this chart.")
        gold.update(denominator=True, numerator=None)  # baseline predicts False (structural gap) — mismatch by design
    elif case_type == "gap_hba1c_good_control_note_only":
        hba1c_in_structured = False
        true_value = round(rng.uniform(6.5, 8.8), 1)
        note_lines.append(f"LABORATORY:\nHbA1c drawn at outside lab on {visit_date}: {true_value}% "
                           "(result relayed verbally, not yet resulted in this EHR).")
        gold.update(denominator=True, numerator=False)  # baseline defaults missing HbA1c to True — mismatch by design
    elif case_type == "gap_exclusion_note_only":
        note_lines.append("ASSESSMENT AND PLAN:\nFamily meeting held; patient enrolled in hospice care "
                           "effective this visit, comfort-focused management going forward.")
        gold.update(denominator=True, exclusion=True, exclusion_reason="hospice_care")  # not coded structurally
    else:
        raise ValueError(case_type)

    if dx_in_structured:
        resources.append(condition(f"cond-{case_id}", "E11.9", "Type 2 diabetes mellitus without complications",
                                    f"{2024 - rng.randint(1, 15)}-01-01"))
    else:
        resources.append(condition(f"cond-{case_id}", "I10", "Essential hypertension", visit_date))
    if exclusion_code:
        resources.append(condition(f"cond-excl-{case_id}", exclusion_code, "Exclusion condition", visit_date))

    resources.append(encounter(f"enc-{case_id}", enc_start, enc_end, enc_class))

    if hba1c_in_structured:
        resources.append(observation(f"obs-{case_id}", "4548-4", "Hemoglobin A1c", hba1c_value, "%", enc_start))
        note_lines.append(f"LABORATORY:\nHbA1c {hba1c_value}% ({visit_date}).")

    note_lines.append("PLAN:\nContinue current management, follow up as scheduled.")
    resources.append(document_reference(f"note-{case_id}", "Progress Note", "\n\n".join(note_lines)))

    if gold["numerator"] is None and case_type not in (
        "denominator_false_age", "denominator_false_no_dx", "denominator_false_no_visit",
    ):
        gold["numerator"] = hba1c_value > 9.0

    return bundle(f"gold-{case_id}", resources), gold


# ── ami_8a case builder ──────────────────────────────────────────────────

def build_ami_case(rng, case_id, case_type):
    name = rng.choice(FIRST_NAMES)
    age = rng.randint(40, 85)
    month, day = rng.randint(1, 11), rng.randint(1, 28)
    arrival = f"2024-{month:02d}-{day:02d}T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00Z"

    resources = [patient(rng, f"pt-{case_id}", age)]
    note_lines = [f"HISTORY OF PRESENT ILLNESS:\n{name} is a {age}-year-old presenting with acute chest pain "
                  "and ST-elevation on ECG, consistent with STEMI."]

    enc_class = "IMP"
    admit_source = None
    ami_dx_in_structured = True
    pci_in_structured = True
    door_to_balloon = rng.randint(30, 89)
    gold = {"denominator": None, "numerator": None, "exclusion": False, "exclusion_reason": None}

    if case_type == "numerator_true_fast_pci":
        door_to_balloon = rng.randint(20, 90)
        gold.update(denominator=True, numerator=True)
    elif case_type == "numerator_false_slow_pci":
        door_to_balloon = rng.randint(91, 240)
        gold.update(denominator=True, numerator=False)
    elif case_type == "denominator_false_no_ami_dx":
        ami_dx_in_structured = False
        gold.update(denominator=False, numerator=None)
    elif case_type == "denominator_false_no_pci":
        pci_in_structured = False
        gold.update(denominator=False, numerator=None)
    elif case_type == "denominator_false_not_hospitalized":
        enc_class = "AMB"
        gold.update(denominator=False, numerator=None)
    elif case_type == "denominator_false_age":
        age = rng.randint(10, 17)
        resources[0] = patient(rng, f"pt-{case_id}", age)
        gold.update(denominator=False, numerator=None)
    elif case_type == "exclusion_comfort_measures":
        gold.update(denominator=True, exclusion=True, exclusion_reason="comfort_measures_only")
    elif case_type == "exclusion_transfer":
        admit_source = "hosp-trans"
        gold.update(denominator=True, exclusion=True, exclusion_reason="transfer_from_other_facility_with_pci")
    elif case_type == "exclusion_pci_prior_to_arrival":
        gold.update(denominator=True, exclusion=True, exclusion_reason="pci_prior_to_arrival")
    elif case_type == "gap_ami_dx_note_only":
        ami_dx_in_structured = False
        note_lines.append(f"{name} has a history documented only in the transfer paperwork narrative of "
                           "anterior STEMI diagnosed at the outside facility prior to transfer.")
        gold.update(denominator=True, numerator=None)
    elif case_type == "gap_pci_time_note_only":
        pci_in_structured = False
        true_minutes = rng.randint(30, 85)
        note_lines.append(f"PROCEDURES:\nDoor-to-balloon time was {true_minutes} minutes; primary PCI performed "
                           "with stent placement (procedure not yet coded in this record).")
        gold.update(denominator=True, numerator=(true_minutes <= 90))
    elif case_type == "gap_exclusion_note_only":
        note_lines.append("PROCEDURES:\nNote: patient was transferred from an outside hospital where primary "
                           "PCI had already been performed prior to arrival here.")
        gold.update(denominator=True, exclusion=True, exclusion_reason="transfer_from_other_facility_with_pci")
    else:
        raise ValueError(case_type)

    if ami_dx_in_structured:
        resources.append(condition(f"cond-{case_id}", "I21.0", "ST elevation (STEMI) myocardial infarction",
                                    arrival))
    else:
        resources.append(condition(f"cond-{case_id}", "R07.9", "Chest pain, unspecified", arrival))
    if case_type == "exclusion_comfort_measures":
        resources.append(condition(f"cond-excl-{case_id}", "Z51.5", "Encounter for palliative care", arrival))

    admit_end = f"2024-{month:02d}-{min(day + 4, 28):02d}T14:00:00Z"
    resources.append(encounter(f"enc-{case_id}", arrival, admit_end, enc_class, admit_source))

    if pci_in_structured:
        if case_type == "exclusion_pci_prior_to_arrival":
            performed = _shift_minutes(arrival, -30)
        else:
            performed = _shift_minutes(arrival, door_to_balloon)
        resources.append(procedure(f"proc-{case_id}", "92928", "Primary PCI", performed))
        note_lines.append(f"PROCEDURES:\nDoor-to-balloon time was {door_to_balloon} minutes; "
                           "primary PCI performed with drug-eluting stent placement.")
    else:
        resources.append(procedure(f"proc-{case_id}", "93000", "Diagnostic ECG", arrival))

    note_lines.append("DISCHARGE SUMMARY:\nPatient tolerated procedure well; discharged on guideline-directed "
                       "medical therapy.")
    resources.append(document_reference(f"note-{case_id}", "Discharge Summary", "\n\n".join(note_lines)))

    if gold["numerator"] is None and case_type not in (
        "denominator_false_no_ami_dx", "denominator_false_no_pci", "denominator_false_not_hospitalized",
        "denominator_false_age",
    ) and not gold["exclusion"]:
        gold["numerator"] = door_to_balloon <= 90

    return bundle(f"gold-{case_id}", resources), gold


def _shift_minutes(iso_dt, minutes):
    from datetime import datetime, timedelta
    dt = datetime.fromisoformat(iso_dt.replace("Z", "+00:00"))
    dt = dt + timedelta(minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ── driver ────────────────────────────────────────────────────────────────

def generate(measure_id: str, counts: dict, build_fn, rng: random.Random) -> list:
    cases = []
    idx = 0
    for case_type, n in counts.items():
        for _ in range(n):
            idx += 1
            case_id = f"{idx:03d}"
            b, gold = build_fn(rng, case_id, case_type)
            errors = validate_bundle(b, measure_id)
            if errors:
                raise RuntimeError(f"Generated bundle {b['id']} failed schema validation: {errors}")
            cases.append({
                "case_id": b["id"],
                "case_type": case_type,
                "bundle": b,
                "gold": gold,
            })
    return cases


def write_dataset(measure_id: str, cases: list):
    measure_dir = OUT_DIR / measure_id
    case_dir = measure_dir / "cases"
    case_dir.mkdir(parents=True, exist_ok=True)

    labels = []
    for case in cases:
        (case_dir / f"{case['case_id']}.json").write_text(json.dumps(case["bundle"], indent=2))
        labels.append({"case_id": case["case_id"], "case_type": case["case_type"], **case["gold"]})

    (measure_dir / "labels.json").write_text(json.dumps(labels, indent=2))
    return len(cases)


def main():
    rng = random.Random(SEED)
    diabetes_cases = generate("diabetes_hba1c", DIABETES_COUNTS, build_diabetes_case, rng)
    ami_cases = generate("ami_8a", AMI_COUNTS, build_ami_case, rng)

    n_diabetes = write_dataset("diabetes_hba1c", diabetes_cases)
    n_ami = write_dataset("ami_8a", ami_cases)

    manifest = {
        "generator": "scripts/generate_gold_cases.py",
        "seed": SEED,
        "schema_version": "1.0",
        "counts": {"diabetes_hba1c": n_diabetes, "ami_8a": n_ami},
        "case_type_distribution": {"diabetes_hba1c": DIABETES_COUNTS, "ami_8a": AMI_COUNTS},
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Generated {n_diabetes} diabetes_hba1c cases and {n_ami} ami_8a cases -> {OUT_DIR}")


if __name__ == "__main__":
    main()
