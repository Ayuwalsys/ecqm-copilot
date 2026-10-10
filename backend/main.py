from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uuid, time, json
from pipeline.ingest import ingest_bundle
from pipeline.retrieval import build_context_pack
from pipeline.extraction import extract_measure
from pipeline.rules import apply_measure_logic
from pipeline.validation import validate_draft

app = FastAPI(title="eCQM Copilot API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job store (swap for Redis/Postgres in prod)
jobs: dict = {}
cases: dict = {}


class ExtractionRequest(BaseModel):
    measure_id: str          # e.g. "diabetes_hba1c" or "ami_8a"
    encounter_id: str
    fhir_bundle: dict        # raw FHIR bundle JSON


class ReviewDecision(BaseModel):
    decision: str            # "accept" | "reject" | "edit"
    rationale: Optional[str] = None
    edited_fields: Optional[dict] = None


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


@app.post("/measures/{measure_id}/extract")
async def extract_sync(measure_id: str, req: ExtractionRequest, background_tasks: BackgroundTasks):
    """Synchronous extraction — returns draft within timeout."""
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "running", "started_at": time.time()}

    try:
        bundle_meta = ingest_bundle(req.fhir_bundle, measure_id)
        context_pack = build_context_pack(bundle_meta, measure_id)
        raw_extraction = extract_measure(context_pack, measure_id)
        draft = apply_measure_logic(raw_extraction, measure_id)
        validated = validate_draft(draft)

        case_id = str(uuid.uuid4())
        case = {
            "case_id": case_id,
            "job_id": job_id,
            "measure_id": measure_id,
            "encounter_id": req.encounter_id,
            "status": "pending_review" if validated["safe"] else "flagged",
            "draft": validated,
            "provenance": bundle_meta["provenance"],
            "created_at": time.time(),
        }
        cases[case_id] = case
        jobs[job_id] = {"status": "complete", "case_id": case_id}
        return {"job_id": job_id, "case_id": case_id, "case": case}

    except Exception as e:
        jobs[job_id] = {"status": "error", "error": str(e)}
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/jobs")
async def extract_async(req: ExtractionRequest):
    """Async job submission — returns job_id immediately."""
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "queued", "queued_at": time.time()}
    # In production: push to Celery/RQ queue
    return {"job_id": job_id, "status": "queued"}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@app.get("/cases/{case_id}")
def get_case(case_id: str):
    if case_id not in cases:
        raise HTTPException(status_code=404, detail="Case not found")
    return cases[case_id]


@app.post("/cases/{case_id}/review")
def submit_review(case_id: str, review: ReviewDecision):
    if case_id not in cases:
        raise HTTPException(status_code=404, detail="Case not found")
    case = cases[case_id]
    if case["status"] == "committed":
        raise HTTPException(status_code=409, detail="Case already committed")

    review_record = {
        "decision": review.decision,
        "rationale": review.rationale,
        "edited_fields": review.edited_fields,
        "reviewed_at": time.time(),
        "override": review.decision in ("reject", "edit"),
    }
    case["review"] = review_record
    case["status"] = "committed"

    # Emit MeasureReport + Provenance (stub — wire to FHIR server in prod)
    case["measure_report"] = _build_measure_report(case)
    cases[case_id] = case
    return {"case_id": case_id, "status": "committed", "measure_report": case["measure_report"]}


@app.get("/cases")
def list_cases(measure_id: Optional[str] = None, status: Optional[str] = None):
    result = list(cases.values())
    if measure_id:
        result = [c for c in result if c["measure_id"] == measure_id]
    if status:
        result = [c for c in result if c["status"] == status]
    return {"cases": result, "total": len(result)}


def _build_measure_report(case: dict) -> dict:
    return {
        "resourceType": "MeasureReport",
        "id": case["case_id"],
        "status": "complete",
        "type": "individual",
        "measure": f"http://ecqm-copilot/measures/{case['measure_id']}",
        "subject": {"reference": f"Patient/{case['encounter_id']}"},
        "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "group": [{"population": case["draft"].get("populations", [])}],
        "evaluatedResource": case["draft"].get("evidence_spans", []),
    }
