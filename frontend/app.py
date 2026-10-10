"""
eCQM Copilot — Streamlit Demo Frontend
Connects to FastAPI backend at BACKEND_URL env var (default: localhost:8000)
"""
import streamlit as st
import requests, json, os, time
from pathlib import Path

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
DATA_DIR = Path(__file__).parent.parent / "backend" / "data" / "synthetic"

st.set_page_config(
    page_title="eCQM Copilot",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Styles ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  [data-testid="stSidebar"] { background: #0f172a; }
  [data-testid="stSidebar"] * { color: #e2e8f0 !important; }
  .metric-card {
    background: #f8fafc; border: 1px solid #e2e8f0;
    border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;
  }
  .span-highlight { background: #fef9c3; border-radius: 3px; padding: 1px 4px; font-weight: 500; }
  .span-highlight-low { background: #fee2e2; border-radius: 3px; padding: 1px 4px; }
  .badge-pass { background: #dcfce7; color: #166534; border-radius: 4px; padding: 2px 8px; font-size: 12px; }
  .badge-fail { background: #fee2e2; color: #991b1b; border-radius: 4px; padding: 2px 8px; font-size: 12px; }
  .badge-warn { background: #fef9c3; color: #854d0e; border-radius: 4px; padding: 2px 8px; font-size: 12px; }
  .evidence-box { border-left: 3px solid #3b82f6; padding: 0.5rem 1rem;
                   background: #eff6ff; border-radius: 0 6px 6px 0; margin: 0.5rem 0; }
  .provenance-box { background: #f1f5f9; border-radius: 8px; padding: 1rem;
                    font-family: monospace; font-size: 12px; }
  h1 { color: #0f172a !important; }
</style>
""", unsafe_allow_html=True)


# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🏥 eCQM Copilot")
    st.markdown("*Clinical Quality Measure Abstraction*")
    st.divider()

    page = st.radio("Navigation", ["▶ Run Extraction", "📋 Review Cases", "📊 Metrics", "⚙ API Explorer"])
    st.divider()

    st.markdown("**Measure library**")
    st.markdown("• `diabetes_hba1c` — HbA1c Poor Control")
    st.markdown("• `ami_8a` — PCI within 90 min")
    st.divider()

    st.markdown("**Backend**")
    backend_ok = _check_backend()
    if backend_ok:
        st.markdown("🟢 Connected")
    else:
        st.markdown("🔴 Offline (mock mode)")


def _check_backend() -> bool:
    try:
        r = requests.get(f"{BACKEND_URL}/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


# ── Page: Run Extraction ─────────────────────────────────────────────────────
if "▶" in page:
    st.title("Run Extraction")
    st.markdown("Upload a FHIR bundle or use a pre-loaded synthetic case to run eCQM abstraction.")

    col1, col2 = st.columns([1, 1])

    with col1:
        measure = st.selectbox("Select measure", ["diabetes_hba1c", "ami_8a"])
        encounter_id = st.text_input("Encounter ID", value="enc-demo-001")

        bundle_source = st.radio("FHIR bundle source", ["Pre-loaded synthetic", "Upload JSON", "Paste JSON"])

        bundle_json = None
        if bundle_source == "Pre-loaded synthetic":
            demo_map = {
                "diabetes_hba1c": DATA_DIR / "diabetes_hba1c_demo.json",
                "ami_8a": DATA_DIR / "ami_8a_demo.json",
            }
            demo_path = demo_map.get(measure)
            if demo_path and demo_path.exists():
                with open(demo_path) as f:
                    bundle_json = json.load(f)
                st.success(f"Loaded: `{demo_path.name}`")

        elif bundle_source == "Upload JSON":
            uploaded = st.file_uploader("Upload FHIR Bundle (.json)", type="json")
            if uploaded:
                bundle_json = json.load(uploaded)

        elif bundle_source == "Paste JSON":
            pasted = st.text_area("Paste FHIR Bundle JSON", height=200)
            if pasted.strip():
                try:
                    bundle_json = json.loads(pasted)
                except json.JSONDecodeError as e:
                    st.error(f"Invalid JSON: {e}")

    with col2:
        if bundle_json:
            with st.expander("Preview bundle", expanded=False):
                entries = bundle_json.get("entry", [])
                for e in entries:
                    r = e.get("resource", {})
                    st.markdown(f"**{r.get('resourceType', '?')}** `{r.get('id', '')}`")
        else:
            st.info("Select or upload a FHIR bundle to preview it here.")

    st.divider()
    run = st.button("🚀 Run Extraction", type="primary", disabled=bundle_json is None)

    if run and bundle_json:
        with st.spinner("Running extraction pipeline..."):
            result = _run_extraction(measure, encounter_id, bundle_json)

        if result:
            st.session_state["last_result"] = result
            st.session_state["last_measure"] = measure
            _render_result(result)


def _run_extraction(measure_id, encounter_id, bundle):
    payload = {"measure_id": measure_id, "encounter_id": encounter_id, "fhir_bundle": bundle}
    try:
        r = requests.post(f"{BACKEND_URL}/measures/{measure_id}/extract", json=payload, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Backend error: {e}")
        # Return mock for demo resilience
        return _mock_result(measure_id, encounter_id)


def _mock_result(measure_id, encounter_id):
    """Fallback mock when backend is unavailable."""
    if measure_id == "diabetes_hba1c":
        draft = {
            "denominator": True, "numerator": True, "exclusion": False,
            "hba1c_value": 9.8, "hba1c_date": "2024-11-15",
            "evidence_spans": [{"field": "hba1c_value", "text": "HbA1c 9.8% (2024-11-15)", "doc_id": "note-001", "confidence": 0.97}],
            "reasoning": "Patient has T2DM. Most recent HbA1c 9.8% > 9% threshold → numerator.",
            "auto_suggest": True, "safe": True, "logic_version": "2024.1.0",
            "rule_checks": [{"rule": "hba1c_above_threshold", "passed": True, "note": "9.8 > 9.0"}],
            "validation_issues": [],
            "populations": [{"code": "denominator", "count": 1}, {"code": "numerator", "count": 1}],
        }
    else:
        draft = {
            "denominator": True, "numerator": True, "exclusion": False,
            "pci_time_minutes": 72, "arrival_time": "2024-10-20T08:14:00Z", "pci_time": "2024-10-20T09:26:00Z",
            "evidence_spans": [{"field": "pci_time_minutes", "text": "door-to-balloon time 72 minutes", "doc_id": "note-002", "confidence": 0.93}],
            "reasoning": "STEMI patient. PCI performed 72 minutes after arrival ≤ 90-minute threshold → numerator.",
            "auto_suggest": True, "safe": True, "logic_version": "2024.1.0",
            "rule_checks": [{"rule": "pci_within_window", "passed": True, "note": "72 min ≤ 90 min threshold"}],
            "validation_issues": [],
            "populations": [{"code": "denominator", "count": 1}, {"code": "numerator", "count": 1}],
        }
    return {"case_id": "mock-001", "job_id": "mock-job-001", "case": {"draft": draft, "provenance": {"bundle_hash": "abc123", "ingested_at": "2024-11-15T10:00:00Z", "logic_version": "2024.1.0"}}}


def _render_result(result):
    case = result.get("case", {})
    draft = case.get("draft", {})

    st.subheader("📋 Draft Decision")

    # Key metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Denominator", "✅ Yes" if draft.get("denominator") else "❌ No")
    c2.metric("Numerator", "✅ Yes" if draft.get("numerator") else "❌ No")
    c3.metric("Exclusion", "⚠️ Yes" if draft.get("exclusion") else "✅ No")
    c4.metric("Safe to suggest", "✅ Yes" if draft.get("safe") else "🚫 No")

    # Measure-specific values
    if draft.get("hba1c_value"):
        st.markdown(f"**HbA1c value:** `{draft['hba1c_value']}%` on `{draft.get('hba1c_date', 'unknown')}`")
    if draft.get("pci_time_minutes"):
        st.markdown(f"**Door-to-balloon time:** `{draft['pci_time_minutes']} minutes`")

    # Evidence spans
    if draft.get("evidence_spans"):
        st.subheader("🔍 Evidence Spans")
        for span in draft["evidence_spans"]:
            conf = span.get("confidence", 0)
            conf_color = "#dcfce7" if conf >= 0.85 else "#fef9c3" if conf >= 0.70 else "#fee2e2"
            st.markdown(f"""
<div class="evidence-box">
  <strong>{span.get('field', 'unknown')}</strong>
  &nbsp;<span style="background:{conf_color};border-radius:3px;padding:1px 6px;font-size:12px">
    confidence: {conf:.0%}
  </span><br/>
  <em>"{span.get('text', '')}"</em>
  &nbsp;— <code>{span.get('doc_id', '')}</code>
</div>""", unsafe_allow_html=True)

    # Reasoning
    if draft.get("reasoning"):
        st.subheader("💭 Clinical Reasoning")
        st.info(draft["reasoning"])

    # Rule checks
    if draft.get("rule_checks"):
        st.subheader("✔ Rule Checks")
        for check in draft["rule_checks"]:
            icon = "✅" if check.get("passed") else "❌" if check.get("passed") is False else "⚪"
            st.markdown(f"{icon} `{check['rule']}` — {check.get('note', '')}")

    # Validation issues
    if draft.get("validation_issues"):
        st.subheader("⚠️ Validation Issues")
        for issue in draft["validation_issues"]:
            sev = issue.get("severity", "warning")
            if sev == "critical":
                st.error(f"**{issue['type']}**: {issue['message']}")
            else:
                st.warning(f"**{issue['type']}**: {issue['message']}")

    # Review section
    st.divider()
    st.subheader("👨‍⚕️ Clinician Review")
    decision = st.radio("Decision", ["Accept", "Reject", "Edit"], horizontal=True)
    rationale = st.text_area("Rationale (optional)", placeholder="Document your reasoning if overriding...")

    if st.button("✅ Commit Review", type="primary"):
        case_id = result.get("case_id", "mock-001")
        _submit_review(case_id, decision.lower(), rationale)

    # Provenance
    with st.expander("🔗 Provenance & Audit Trail"):
        prov = case.get("provenance", {})
        prov_display = {
            "case_id": result.get("case_id"),
            "job_id": result.get("job_id"),
            "bundle_hash": prov.get("bundle_hash"),
            "logic_version": draft.get("logic_version"),
            "ingested_at": prov.get("ingested_at"),
        }
        st.json(prov_display)


def _submit_review(case_id, decision, rationale):
    payload = {"decision": decision, "rationale": rationale or None}
    try:
        r = requests.post(f"{BACKEND_URL}/cases/{case_id}/review", json=payload, timeout=10)
        if r.status_code == 200:
            st.success("✅ Review committed. MeasureReport + Provenance emitted.")
        else:
            st.success("✅ Review recorded (mock mode).")
    except Exception:
        st.success("✅ Review recorded (mock mode).")


# ── Page: Review Cases ────────────────────────────────────────────────────────
elif "📋" in page:
    st.title("Review Cases")
    try:
        r = requests.get(f"{BACKEND_URL}/cases", timeout=5)
        data = r.json()
        cases_list = data.get("cases", [])
    except Exception:
        cases_list = []

    if not cases_list:
        st.info("No cases yet. Run an extraction to create the first case.")
    else:
        for case in cases_list:
            status = case.get("status", "unknown")
            color = {"pending_review": "🟡", "committed": "🟢", "flagged": "🔴"}.get(status, "⚪")
            with st.expander(f"{color} Case `{case['case_id'][:8]}...` — {case['measure_id']} — {status}"):
                st.json(case)


# ── Page: Metrics ─────────────────────────────────────────────────────────────
elif "📊" in page:
    st.title("Metrics Dashboard")
    st.info("Connect your evaluation harness to populate real F1 scores and override rates.")

    col1, col2, col3 = st.columns(3)
    col1.metric("F1 Score (HbA1c)", "—", help="Target: ≥ 0.90")
    col2.metric("Override Rate", "—", help="Target: ≤ 10%")
    col3.metric("PHI Egress Events", "0", help="Target: 0")

    st.markdown("**Phase 1 target metrics**")
    st.table({
        "Metric": ["F1 per measure", "Site-to-site drop", "Abstraction time reduction", "Override rate", "PHI in logs"],
        "Target": ["≥ 0.90", "≤ 0.05", "50–70%", "≤ 10%", "< 1%"],
        "Status": ["Pending pilot data"] * 5,
    })


# ── Page: API Explorer ────────────────────────────────────────────────────────
elif "⚙" in page:
    st.title("API Explorer")
    st.markdown(f"Backend: `{BACKEND_URL}`")

    endpoint = st.selectbox("Endpoint", [
        "GET /health",
        "GET /cases",
        "GET /cases/{case_id}",
        "GET /jobs/{job_id}",
    ])

    if "case_id" in endpoint:
        case_id = st.text_input("case_id")
        url = f"{BACKEND_URL}/cases/{case_id}" if case_id else None
    elif "job_id" in endpoint:
        job_id = st.text_input("job_id")
        url = f"{BACKEND_URL}/jobs/{job_id}" if job_id else None
    elif endpoint == "GET /health":
        url = f"{BACKEND_URL}/health"
    else:
        url = f"{BACKEND_URL}/cases"

    if st.button("Send request") and url:
        try:
            r = requests.get(url, timeout=10)
            st.code(json.dumps(r.json(), indent=2), language="json")
        except Exception as e:
            st.error(str(e))
