"""
compute_irr.py — Cohen's kappa for the 30-case IRR overlap batch
(Phase 1 gate: kappa >= 0.80).

Consumes two Label Studio JSON exports (one per annotator) of the project
built from labeling/label_studio_config.xml + labeling/irr_batch/tasks.json,
matches them by case_id, and reports per-field and overall kappa.

Usage:
    python -m scripts.compute_irr annotator_a_export.json annotator_b_export.json
    python -m scripts.compute_irr --demo   # sanity-checks the calculation itself
"""
import json
import sys
from collections import Counter
from pathlib import Path

FIELDS = ["denominator", "numerator", "exclusion"]
KAPPA_GATE = 0.80


def cohen_kappa(labels_a: list, labels_b: list) -> float:
    n = len(labels_a)
    if n == 0:
        return float("nan")
    categories = sorted(set(labels_a) | set(labels_b))
    confusion = Counter(zip(labels_a, labels_b))

    po = sum(confusion[(c, c)] for c in categories) / n

    row_totals = Counter(labels_a)
    col_totals = Counter(labels_b)
    pe = sum((row_totals[c] / n) * (col_totals[c] / n) for c in categories)

    if pe == 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def parse_label_studio_export(path: Path) -> dict:
    """Returns {case_id: {field: value}} from a Label Studio JSON export."""
    raw = json.loads(path.read_text())
    out = {}
    for task in raw:
        case_id = task.get("data", {}).get("case_id")
        annotations = task.get("annotations") or []
        if not case_id or not annotations:
            continue
        fields = {}
        for result in annotations[0].get("result", []):
            name = result.get("from_name")
            if name in FIELDS:
                choices = result.get("value", {}).get("choices", [])
                if choices:
                    fields[name] = choices[0]
        out[case_id] = fields
    return out


def evaluate(export_a: dict, export_b: dict) -> dict:
    shared_ids = sorted(set(export_a) & set(export_b))
    missing_a = sorted(set(export_b) - set(export_a))
    missing_b = sorted(set(export_a) - set(export_b))

    report = {"n_shared_cases": len(shared_ids), "missing_from_a": missing_a, "missing_from_b": missing_b,
              "per_field": {}}

    kappas = []
    for field in FIELDS:
        labels_a, labels_b = [], []
        for case_id in shared_ids:
            va, vb = export_a[case_id].get(field), export_b[case_id].get(field)
            if va is None or vb is None:
                continue
            labels_a.append(va)
            labels_b.append(vb)
        kappa = cohen_kappa(labels_a, labels_b)
        report["per_field"][field] = {"kappa": round(kappa, 4) if kappa == kappa else None, "n": len(labels_a)}
        if kappa == kappa:
            kappas.append(kappa)

    report["overall_kappa"] = round(sum(kappas) / len(kappas), 4) if kappas else None
    report["gate"] = KAPPA_GATE
    report["gate_passed"] = bool(report["overall_kappa"] is not None and report["overall_kappa"] >= KAPPA_GATE)
    return report


def _demo():
    """Sanity-check the kappa math with a synthetic near-agreement pair. Not a real IRR result."""
    import random
    rng = random.Random(0)
    case_ids = [f"demo-{i:03d}" for i in range(30)]
    export_a, export_b = {}, {}
    for cid in case_ids:
        base = {f: rng.choice(["Yes", "No"]) for f in FIELDS}
        export_a[cid] = dict(base)
        export_b[cid] = {f: (v if rng.random() > 0.1 else rng.choice(["Yes", "No"])) for f, v in base.items()}
    report = evaluate(export_a, export_b)
    print("DEMO ONLY — synthetic annotators, not a real IRR measurement.")
    print(json.dumps(report, indent=2))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        _demo()
        return
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    export_a = parse_label_studio_export(Path(sys.argv[1]))
    export_b = parse_label_studio_export(Path(sys.argv[2]))
    report = evaluate(export_a, export_b)

    print(f"Shared cases: {report['n_shared_cases']}")
    for field, stats in report["per_field"].items():
        print(f"  {field:12s} kappa={stats['kappa']} (n={stats['n']})")
    print(f"Overall kappa: {report['overall_kappa']} "
          f"({'PASS' if report['gate_passed'] else 'FAIL'} — gate is {KAPPA_GATE})")

    out_path = Path("labeling/irr_batch/irr_results.json")
    out_path.write_text(json.dumps(report, indent=2))
    print(f"Report written to {out_path}")


if __name__ == "__main__":
    main()
