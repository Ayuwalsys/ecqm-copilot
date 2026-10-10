"""
ingest.py — Bundle validation, PHI guard, provenance seed.
"""
import hashlib, json, time, re
from typing import Any, Optional

from schemas.lock import validate_bundle as validate_bundle_schema, verify_lock

PHI_PATTERNS = [
    r"\b\d{3}-\d{2}-\d{4}\b",          # SSN
    r"\b\d{10,}\b",                      # MRN-like long numbers
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # email
]


def ingest_bundle(bundle: dict, measure_id: Optional[str] = None) -> dict:
    """Validate against the locked schema, hash, PHI-guard, and create provenance seed."""
    _validate_bundle(bundle, measure_id)
    bundle_hash = _hash_bundle(bundle)
    resources = _index_resources(bundle)
    notes = _extract_notes(resources)
    _phi_guard_notes(notes)

    provenance = {
        "bundle_hash": bundle_hash,
        "ingested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "resource_types": list(resources.keys()),
        "resource_counts": {k: len(v) for k, v in resources.items()},
        "note_count": len(notes),
        "phi_check": "passed",
    }

    return {
        "bundle": bundle,
        "bundle_hash": bundle_hash,
        "resources": resources,
        "notes": notes,
        "provenance": provenance,
    }


def _validate_bundle(bundle: dict, measure_id: Optional[str] = None):
    verify_lock()  # fail fast if the locked schema file has drifted
    errors = validate_bundle_schema(bundle, measure_id)
    if errors:
        raise ValueError(f"Bundle failed schema validation: {'; '.join(errors)}")


def _hash_bundle(bundle: dict) -> str:
    raw = json.dumps(bundle, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _index_resources(bundle: dict) -> dict:
    index: dict = {}
    for entry in bundle.get("entry", []):
        r = entry.get("resource", {})
        rt = r.get("resourceType", "Unknown")
        index.setdefault(rt, []).append(r)
    return index


def _extract_notes(resources: dict) -> list:
    notes = []
    for doc_ref in resources.get("DocumentReference", []):
        for content in doc_ref.get("content", []):
            attachment = content.get("attachment", {})
            text = attachment.get("data", "") or attachment.get("url", "")
            if text:
                notes.append({
                    "doc_id": doc_ref.get("id", "unknown"),
                    "text": text,
                    "type": doc_ref.get("type", {}).get("text", "Clinical Note"),
                })
    return notes


def _phi_guard_notes(notes: list):
    """Raise if obvious PHI patterns detected in note text."""
    for note in notes:
        for pattern in PHI_PATTERNS:
            if re.search(pattern, note["text"]):
                raise ValueError(
                    f"PHI pattern detected in note {note['doc_id']} — "
                    "de-identify before ingestion"
                )
