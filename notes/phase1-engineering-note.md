# Phase 1 Engineering Note — Foundation

**Scope covered:** the four Phase 1 roadmap items that are engineering work (schema lock, gold labeling, rules-only baseline, Label Studio/IRR setup). MIMIC-IV DUA + BigQuery access is administrative and out of scope for this session — still owned by the user.

## What shipped

### 1. FHIR bundle schema lock (v1.0)
- `backend/schemas/fhir_bundle.schema.v1.0.yaml` — structural contract for accepted bundles: required resource types (Patient, Encounter, DocumentReference always; Condition/Observation/Procedure per measure), required fields per resource, and per-measure `required_resource_types` for `diabetes_hba1c` and `ami_8a`.
- Value sets (ICD-10/LOINC/CPT codes) are **not** duplicated in the schema — they stay single-sourced in `backend/measures/{id}.yaml`. The schema only checks bundle *shape*.
- `backend/schemas/lock.py` — computes/verifies a SHA-256 lock (`fhir_bundle.schema.v1.0.yaml.sha256`). `verify_lock()` raises if the schema file drifts without a version bump; `validate_bundle()` does the structural check.
- Wired into `pipeline/ingest.py`: every ingested bundle now runs through schema validation before PHI guard, and `ingest_bundle()` takes an optional `measure_id` for measure-specific checks. `main.py` passes `measure_id` through.

### 2. Rules-only baseline (no LLM)
- `backend/pipeline/baseline.py` — derives denominator/numerator/exclusion **directly from structured FHIR resources** (Condition codes, Observation values, Procedure timing vs. Encounter period), bypassing the LLM/extraction.py path entirely. This is the deterministic floor Phase 2's RAG+LLM pipeline needs to beat.
- Extended `backend/measures/diabetes_hba1c.yaml` and `ami_8a.yaml` with concrete, structurally-checkable exclusion codes (`exclusion_value_sets`) and qualifying-encounter-class fields, since the original YAMLs only had exclusion *labels* with no codes.

### 3. Gold-label dataset (100–150/measure gate)
- `backend/scripts/generate_gold_cases.py` — seeded (seed=42), reproducible generator. **130 cases each** for `diabetes_hba1c` and `ami_8a` (260 total), output to `backend/data/synthetic/gold/{measure_id}/cases/*.json` + `labels.json`.
- Deliberate design: ~20% of cases are "gap" cases — the true clinical fact (a diagnosis, a lab value, an exclusion) is documented **only in the free-text note**, not in a structured resource. This is what makes the recorded baseline F1 meaningful rather than trivially 1.0.
- All 260 cases pass schema validation and the PHI guard (verified by running every case through `ingest_bundle`).

### 4. Baseline F1 (gate: "baseline F1 recorded")
- `backend/scripts/eval_baseline.py` — runs the structured baseline against gold labels, scores denominator/exclusion/numerator as separate binary classification problems (numerator only scored on the denominator-eligible, non-excluded subpopulation, per standard eCQM logic).
- **Results** (`backend/data/synthetic/gold/baseline_results.json`):

  | Measure | Numerator F1 | Denominator F1 | Exclusion F1 |
  |---|---|---|---|
  | diabetes_hba1c | **0.930** | 0.959 | 0.930 |
  | ami_8a | **0.923** | 0.932 | 0.941 |

  Every mismatch traces exactly to the deliberately-planted "gap" cases (`gap_dx_note_only`, `gap_hba1c_good_control_note_only`, `gap_pci_time_note_only`, `gap_ami_dx_note_only`) — confirming the harness and generator are internally consistent, not just coincidentally scoring well.

### 5. Label Studio + IRR (gate: κ ≥ 0.80)
- `backend/labeling/label_studio_config.xml` — labeling interface: denominator/numerator/exclusion choices + optional evidence-span highlighting (reusable later for the Phase 2 hallucination-guard eval).
- `backend/scripts/build_irr_batch.py` — samples 30 cases (15/measure), stratified across all case types so the batch isn't all easy cases. Output: `backend/labeling/irr_batch/tasks.json` (Label Studio import format, no gold labels included — blind annotation).
- `backend/scripts/compute_irr.py` — Cohen's kappa calculator, parses two Label Studio JSON exports, reports per-field + overall kappa against the 0.80 gate. Verified against synthetic near-agreement data (`--demo` mode): kappa ≈ 0.91, confirming the math is correct.
- **Not yet run for real** — needs two human annotators in an actual Label Studio instance. This is infrastructure, not a completed measurement.

## Housekeeping
- Deleted a stray empty `{backend/...}` directory tree left by a botched `mkdir -p {backend/pipeline,backend/measures,...}` (brace expansion didn't fire, likely run under `sh` not `bash`). No real work was in it.

## Known issue (flagged, not fixed — out of scope for Phase 1 gate work)
`backend/pipeline/extraction.py`'s `_mock_extraction_str()` fallback always returns the diabetes mock regardless of which measure was requested, so local dev runs of the LLM path currently mislabel `ami_8a` when the mock path is hit (e.g., no `HF_API_TOKEN` set). Doesn't affect anything above since the baseline bypasses the LLM entirely. Worth a one-line fix (`_mock_extraction(measure_id)` instead of hardcoded `"diabetes_hba1c"`) whenever Phase 2 extraction work starts.

## Phase 1 gate status

| Gate item | Status |
|---|---|
| IRR κ ≥ 0.80 | Tooling ready, not yet run (needs real annotators) |
| PHI guard passing | ✅ Verified on all 260 gold cases + both demo bundles |
| Baseline F1 recorded | ✅ 0.930 / 0.923 |
| MIMIC DUA signed | Outstanding — administrative, owned by user |

## Next steps
1. Get two annotators labeling `backend/labeling/irr_batch/tasks.json` in Label Studio; run `compute_irr.py` on their real exports.
2. File the MIMIC-IV DUA + BigQuery access request.
3. When ready, re-point the gold-case pipeline at de-identified MIMIC-IV-Note data once DUA is signed (generator was deliberately kept separate/swappable for this).
4. Fix the `extraction.py` mock-measure bug before starting Phase 2 RAG extraction work.
