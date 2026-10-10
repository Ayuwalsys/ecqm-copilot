"""
lock.py — SHA-256 content lock + structural validator for the FHIR bundle
schema (fhir_bundle.schema.v1.0.yaml).

CLI:
    python -m backend.schemas.lock write    # (re)generate the .sha256 lock file
    python -m backend.schemas.lock verify    # check the schema file hasn't drifted
"""
import hashlib
import sys
from pathlib import Path

import yaml

SCHEMA_DIR = Path(__file__).parent
MEASURES_DIR = SCHEMA_DIR.parent / "measures"
CURRENT_SCHEMA_FILE = SCHEMA_DIR / "fhir_bundle.schema.v1.0.yaml"


def compute_hash(schema_path: Path = CURRENT_SCHEMA_FILE) -> str:
    return hashlib.sha256(schema_path.read_bytes()).hexdigest()


def lock_path_for(schema_path: Path = CURRENT_SCHEMA_FILE) -> Path:
    return schema_path.with_suffix(schema_path.suffix + ".sha256")


def write_lock(schema_path: Path = CURRENT_SCHEMA_FILE) -> str:
    digest = compute_hash(schema_path)
    lock_path_for(schema_path).write_text(digest + "\n")
    return digest


def verify_lock(schema_path: Path = CURRENT_SCHEMA_FILE) -> None:
    """Raise if the schema file's content no longer matches its recorded lock hash."""
    lock_file = lock_path_for(schema_path)
    if not lock_file.exists():
        raise RuntimeError(
            f"No lock file for {schema_path.name} — run "
            f"'python -m backend.schemas.lock write' to create it."
        )
    recorded = lock_file.read_text().strip()
    actual = compute_hash(schema_path)
    if recorded != actual:
        raise RuntimeError(
            f"Schema drift detected in {schema_path.name}: content no longer "
            f"matches its SHA-256 lock ({recorded[:12]}... != {actual[:12]}...). "
            f"Locked schema versions must not be edited in place — bump "
            f"schema_version and create a new file instead."
        )


def _load_schema(schema_path: Path = CURRENT_SCHEMA_FILE) -> dict:
    return yaml.safe_load(schema_path.read_text())


def _get_path(resource: dict, dotted_path: str):
    node = resource
    for key in dotted_path.split("."):
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def validate_bundle(bundle: dict, measure_id: str | None = None, schema_path: Path = CURRENT_SCHEMA_FILE) -> list[str]:
    """
    Structural validation against the locked FHIR bundle schema.
    Returns a list of human-readable error strings (empty list == valid).
    Does not raise — callers decide whether errors are fatal.
    """
    schema = _load_schema(schema_path)
    errors: list[str] = []

    bundle_spec = schema["bundle"]
    if bundle.get("resourceType") != bundle_spec["resourceType"]:
        errors.append(f"resourceType must be '{bundle_spec['resourceType']}'")
    if bundle.get("type") != bundle_spec["type"]:
        errors.append(f"Bundle.type must be '{bundle_spec['type']}'")

    entries = bundle.get("entry", [])
    if len(entries) < bundle_spec["min_entries"]:
        errors.append(f"Bundle must contain at least {bundle_spec['min_entries']} entries")

    by_type: dict[str, list[dict]] = {}
    for entry in entries:
        resource = entry.get("resource", {})
        by_type.setdefault(resource.get("resourceType", "Unknown"), []).append(resource)

    for resource_type, spec in schema["resources"].items():
        occurrences = by_type.get(resource_type, [])
        if spec.get("required") and not occurrences:
            errors.append(f"Missing required resource type: {resource_type}")
        if spec.get("max_occurs") and len(occurrences) > spec["max_occurs"]:
            errors.append(f"{resource_type} occurs {len(occurrences)} times, max {spec['max_occurs']}")
        for resource in occurrences:
            for field_path, field_spec in spec.get("fields", {}).items():
                value = _get_path(resource, field_path)
                if field_spec.get("required") and (value is None or value == []):
                    errors.append(f"{resource_type}/{resource.get('id', '?')} missing required field '{field_path}'")

    if measure_id:
        measure_spec = schema.get("measures", {}).get(measure_id)
        if measure_spec is None:
            errors.append(f"No schema entry for measure '{measure_id}'")
        else:
            for required_type in measure_spec["required_resource_types"]:
                if not by_type.get(required_type):
                    errors.append(f"Measure '{measure_id}' requires resource type '{required_type}', none found")

    return errors


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if action == "write":
        digest = write_lock()
        print(f"Wrote lock for {CURRENT_SCHEMA_FILE.name}: {digest}")
    elif action == "verify":
        verify_lock()
        print(f"OK — {CURRENT_SCHEMA_FILE.name} matches its recorded SHA-256 lock.")
    else:
        print(f"Unknown action '{action}'. Use 'write' or 'verify'.", file=sys.stderr)
        sys.exit(1)
