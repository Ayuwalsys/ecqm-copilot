# eCQM Copilot

**FHIR-native clinical quality measure abstraction with clinician-verifiable evidence.**

A privacy-preserving service that automates eCQM/HEDIS abstraction using a hybrid RAG + deterministic rules engine, with full provenance and clinician-in-the-loop review.

---

## Quick start (local)

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend (new terminal)
cd frontend
pip install -r requirements.txt
BACKEND_URL=http://localhost:8000 streamlit run app.py
```

Then open `http://localhost:8501` and run an extraction with a pre-loaded synthetic case.

---

## Phase 1 measures

| ID | Name | Logic version |
|---|---|---|
| `diabetes_hba1c` | Diabetes: HbA1c Poor Control (>9%) | 2024.1.0 |
| `ami_8a` | AMI-8a: Primary PCI within 90 minutes | 2024.1.0 |

---

## Architecture

```
POST /measures/{id}/extract
  → ingest.py      — bundle validation, SHA-256 hash, PHI guard, provenance seed
  → retrieval.py   — section-aware chunker, context pack builder
  → extraction.py  — RAG + LLM (HF Inference API), evidence spans with char offsets
  → rules.py       — deterministic eCQM logic from measures/*.yaml
  → validation.py  — hallucination guard, PHI sweep, confidence floor
  → draft case     — stored with full provenance
  → reviewer UI    — accept / reject / edit + rationale
  → MeasureReport  — FHIR MeasureReport + Provenance on commit
```

---

## Deployment

### Render.com (recommended)
1. Push repo to GitHub
2. Connect repo in Render dashboard → `render.yaml` auto-configures both services
3. Set `HF_API_TOKEN` secret in Render dashboard
4. Done — two public URLs for API and UI

### Streamlit Community Cloud (UI only, no backend)
The frontend runs in mock mode when `BACKEND_URL` is unreachable — suitable for static demos.

---

## Data & privacy

- All synthetic data generated with Synthea — **zero real PHI**
- PHI guard runs on every bundle at ingest — blocks SSN patterns, email addresses
- De-identification required before ingestion of real data
- Logs contain only hashed bundle IDs and timing metadata

---

## Model card

| Attribute | Value |
|---|---|
| Base model | `mistralai/Mistral-7B-Instruct-v0.3` (swappable) |
| Task | Clinical NLP — eCQM abstraction |
| Input | FHIR Bundle (JSON) |
| Output | Draft decision + evidence spans + FHIR MeasureReport |
| Validation | Hallucination guard (evidence span requirement), rule-based cross-check |
| Bias monitoring | Not yet implemented (Phase 2) |
| Drift monitoring | Not yet implemented (Phase 2) |

---

## Target metrics (Phase 1)

| Metric | Target |
|---|---|
| F1 per measure | ≥ 0.90 vs expert abstractors |
| Site-to-site F1 drop | ≤ 0.05 |
| Abstraction time reduction | 50–70% |
| Reviewer override rate | ≤ 10% |
| PHI egress events | 0 |

---

## Roadmap

- **Days 0–30:** Label 100–200 cases/measure, metrics harness, baseline rules
- **Days 31–60:** RAG extraction, reviewer UI, evaluation dashboard
- **Days 61–90:** Limited pilot, time-and-motion study, technical report
- **6 months:** 8–10 measures, multi-site generalization study, preprint
- **12 months:** Multi-hospital rollout, open measure logic library specification
