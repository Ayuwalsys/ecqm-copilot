"""
build_irr_batch.py — Build the 30-case inter-rater reliability (IRR) overlap
batch for Label Studio double-annotation (Phase 1 gate: kappa >= 0.80).

Samples 15 cases per measure, stratified across case_type so the batch
exercises both "clean" and "structural gap" scenarios rather than only easy
cases. Does NOT include gold labels in the exported tasks — annotators label
blind; gold is only used afterward to sanity-check the batch composition.

Usage:
    python -m scripts.build_irr_batch
"""
import json
import random
from collections import defaultdict
from pathlib import Path

GOLD_DIR = Path(__file__).parent.parent / "data" / "synthetic" / "gold"
OUT_DIR = Path(__file__).parent.parent / "labeling" / "irr_batch"
PER_MEASURE = 15
SAMPLE_SEED = 1337


def stratified_sample(labels: list, n: int, rng: random.Random) -> list:
    by_type = defaultdict(list)
    for label in labels:
        by_type[label["case_type"]].append(label)
    for cases in by_type.values():
        rng.shuffle(cases)

    types = sorted(by_type.keys())
    selected = []
    i = 0
    while len(selected) < n and any(by_type[t] for t in types):
        t = types[i % len(types)]
        if by_type[t]:
            selected.append(by_type[t].pop())
        i += 1
    return selected[:n]


def format_structured_summary(bundle: dict) -> str:
    by_type = defaultdict(list)
    for entry in bundle.get("entry", []):
        r = entry.get("resource", {})
        by_type[r.get("resourceType")].append(r)

    lines = []
    for p in by_type.get("Patient", []):
        lines.append(f"Patient: birthDate={p.get('birthDate')}, gender={p.get('gender')}")
    for e in by_type.get("Encounter", []):
        cls = e.get("class", {}).get("code")
        period = e.get("period", {})
        lines.append(f"Encounter: class={cls}, {period.get('start')} -> {period.get('end')}")
        admit = e.get("hospitalization", {}).get("admitSource", {}).get("coding", [{}])[0].get("code")
        if admit:
            lines.append(f"  admitSource={admit}")
    for c in by_type.get("Condition", []):
        coding = (c.get("code", {}).get("coding") or [{}])[0]
        lines.append(f"Condition: {coding.get('code')} {coding.get('display')}")
    for o in by_type.get("Observation", []):
        coding = (o.get("code", {}).get("coding") or [{}])[0]
        value = o.get("valueQuantity", {})
        lines.append(f"Observation: {coding.get('display')} = {value.get('value')} {value.get('unit', '')} "
                      f"({o.get('effectiveDateTime')})")
    for pr in by_type.get("Procedure", []):
        coding = (pr.get("code", {}).get("coding") or [{}])[0]
        lines.append(f"Procedure: {coding.get('display')} at {pr.get('performedDateTime')}")

    return "\n".join(lines)


def format_note_text(bundle: dict) -> str:
    parts = []
    for entry in bundle.get("entry", []):
        r = entry.get("resource", {})
        if r.get("resourceType") == "DocumentReference":
            for content in r.get("content", []):
                text = content.get("attachment", {}).get("data", "")
                if text:
                    parts.append(f"[{r.get('type', {}).get('text', 'Note')} — {r.get('id')}]\n{text}")
    return "\n\n---\n\n".join(parts)


def main():
    rng = random.Random(SAMPLE_SEED)
    tasks = []
    manifest_cases = []

    for measure_id in ["diabetes_hba1c", "ami_8a"]:
        measure_dir = GOLD_DIR / measure_id
        labels = json.loads((measure_dir / "labels.json").read_text())
        sample = stratified_sample(labels, PER_MEASURE, rng)

        for label in sample:
            bundle = json.loads((measure_dir / "cases" / f"{label['case_id']}.json").read_text())
            tasks.append({
                "data": {
                    "case_id": label["case_id"],
                    "measure_id": measure_id,
                    "structured_summary": format_structured_summary(bundle),
                    "note_text": format_note_text(bundle),
                }
            })
            manifest_cases.append({"case_id": label["case_id"], "measure_id": measure_id,
                                    "case_type": label["case_type"]})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "tasks.json").write_text(json.dumps(tasks, indent=2))
    (OUT_DIR / "manifest.json").write_text(json.dumps({
        "n_cases": len(manifest_cases),
        "per_measure": PER_MEASURE,
        "sample_seed": SAMPLE_SEED,
        "cases": manifest_cases,
    }, indent=2))

    print(f"Wrote {len(tasks)} IRR tasks to {OUT_DIR / 'tasks.json'}")
    print(f"Case type coverage: {sorted({c['case_type'] for c in manifest_cases})}")


if __name__ == "__main__":
    main()
