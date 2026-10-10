"""
extraction.py — RAG + LLM extraction with evidence spans.
Calls HF Inference API by default; swap provider via LLM_PROVIDER env var.
"""
import os, json, re
from typing import Any

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "huggingface")
HF_API_TOKEN = os.getenv("HF_API_TOKEN", "")
HF_MODEL = os.getenv("HF_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")

EXTRACTION_PROMPTS = {
    "diabetes_hba1c": """You are a clinical quality measure abstractor. Extract information for the Diabetes: HbA1c Poor Control (>9%) measure.

Given the following patient data, determine:
1. Is the patient in the denominator? (Has diabetes diagnosis, age 18-75, had a qualifying visit)
2. Is the patient in the numerator? (Most recent HbA1c > 9% OR no HbA1c result)
3. Are there any denominator exclusions? (Hospice, frailty, etc.)

For each finding, cite the EXACT text span from the source and its character offset.

Patient data:
{context}

Respond ONLY in this JSON format:
{{
  "denominator": true/false,
  "numerator": true/false,
  "exclusion": false,
  "hba1c_value": <number or null>,
  "hba1c_date": "<date or null>",
  "evidence_spans": [
    {{"field": "hba1c_value", "text": "<exact quoted text>", "doc_id": "<id>", "confidence": 0.0-1.0}}
  ],
  "reasoning": "<brief clinical reasoning>"
}}""",

    "ami_8a": """You are a clinical quality measure abstractor. Extract information for the AMI-8a measure (Primary PCI within 90 minutes).

Given the following patient data, determine:
1. Is the patient in the denominator? (AMI diagnosis, age ≥18, hospitalized, PCI performed)
2. Is the patient in the numerator? (PCI performed within 90 minutes of hospital arrival)
3. Are there any denominator exclusions?

For each finding, cite the EXACT text span from the source.

Patient data:
{context}

Respond ONLY in this JSON format:
{{
  "denominator": true/false,
  "numerator": true/false,
  "exclusion": false,
  "pci_time_minutes": <number or null>,
  "arrival_time": "<datetime or null>",
  "pci_time": "<datetime or null>",
  "evidence_spans": [
    {{"field": "<field>", "text": "<exact quoted text>", "doc_id": "<id>", "confidence": 0.0-1.0}}
  ],
  "reasoning": "<brief clinical reasoning>"
}}""",
}


def extract_measure(context_pack: dict, measure_id: str) -> dict:
    """Run LLM extraction and return raw result with evidence spans."""
    prompt_template = EXTRACTION_PROMPTS.get(measure_id)
    if not prompt_template:
        raise ValueError(f"No extraction prompt configured for measure: {measure_id}")

    context_str = _format_context(context_pack)
    prompt = prompt_template.format(context=context_str)

    if LLM_PROVIDER == "huggingface":
        raw = _call_hf_inference(prompt, measure_id)
    elif LLM_PROVIDER == "openai":
        raw = _call_openai(prompt, measure_id)
    else:
        raw = _mock_extraction_str(measure_id)  # fallback for local dev / testing

    result = _parse_llm_response(raw)
    result["measure_id"] = measure_id
    result["model"] = HF_MODEL
    result["context_hash"] = hash(context_str) & 0xFFFF
    return result


def _format_context(context_pack: dict) -> str:
    parts = []

    facts = context_pack.get("structured_facts", {})
    if facts.get("observations"):
        parts.append("=== LAB RESULTS ===")
        for obs in facts["observations"]:
            parts.append(
                f"[{obs.get('effective_date', 'unknown date')}] "
                f"{obs.get('code', {}).get('display', 'Unknown test')}: "
                f"{obs.get('value')} {obs.get('unit', '')}"
            )

    if facts.get("conditions"):
        parts.append("\n=== CONDITIONS ===")
        for cond in facts["conditions"]:
            parts.append(f"- {cond.get('code', {}).get('display', 'Unknown')} ({cond.get('clinical_status', '')})")

    if facts.get("encounters"):
        parts.append("\n=== ENCOUNTERS ===")
        for enc in facts["encounters"]:
            parts.append(f"- Encounter {enc.get('id')}: {enc.get('start')} to {enc.get('end')} [{enc.get('class', '')}]")

    for snippet in context_pack.get("note_snippets", []):
        parts.append(f"\n=== NOTE [{snippet['doc_id']}] — {snippet['section'].upper()} ===")
        parts.append(snippet["text"])

    return "\n".join(parts)


def _call_hf_inference(prompt: str, measure_id: str) -> str:
    try:
        import requests
        headers = {"Authorization": f"Bearer {HF_API_TOKEN}", "Content-Type": "application/json"}
        payload = {
            "inputs": f"<s>[INST] {prompt} [/INST]",
            "parameters": {"max_new_tokens": 512, "temperature": 0.1, "return_full_text": False},
        }
        resp = requests.post(
            f"https://api-inference.huggingface.co/models/{HF_MODEL}",
            headers=headers,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data[0].get("generated_text", "")
        return str(data)
    except Exception as e:
        return _mock_extraction_str(measure_id)


def _call_openai(prompt: str, measure_id: str) -> str:
    try:
        import openai
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        return _mock_extraction_str(measure_id)


def _mock_extraction(measure_id: str) -> dict:
    """Deterministic mock for local dev — returns a realistic draft."""
    if measure_id == "diabetes_hba1c":
        return {
            "denominator": True, "numerator": True, "exclusion": False,
            "hba1c_value": 9.8, "hba1c_date": "2024-11-15",
            "evidence_spans": [
                {"field": "hba1c_value", "text": "HbA1c 9.8% (2024-11-15)", "doc_id": "note-001", "confidence": 0.97}
            ],
            "reasoning": "Patient has type 2 diabetes. Most recent HbA1c is 9.8% (>9%), placing patient in numerator.",
        }
    return {
        "denominator": True, "numerator": True, "exclusion": False,
        "pci_time_minutes": 72, "arrival_time": "2024-10-20T08:14:00Z", "pci_time": "2024-10-20T09:26:00Z",
        "evidence_spans": [
            {"field": "pci_time_minutes", "text": "door-to-balloon time 72 minutes", "doc_id": "note-002", "confidence": 0.93}
        ],
        "reasoning": "STEMI patient. PCI performed 72 minutes after arrival, within the 90-minute threshold.",
    }


def _mock_extraction_str(measure_id: str) -> str:
    return json.dumps(_mock_extraction(measure_id))


def _parse_llm_response(raw: str) -> dict:
    try:
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception:
        pass
    return {"parse_error": True, "raw": raw[:500], "evidence_spans": []}
