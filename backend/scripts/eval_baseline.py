"""
eval_baseline.py — Rules-only baseline F1 evaluation (Phase 1 gate).

Runs pipeline/baseline.py (structured FHIR extraction + rules.py, no LLM)
against the gold-label sets in data/synthetic/gold/{measure_id}/ and reports
precision/recall/F1 for denominator, exclusion, and numerator classification.

Numerator F1 is the headline metric — CMS eCQM logic only defines a numerator
answer for patients who are in the denominator and not excluded, so it's
scored on that subpopulation only. Denominator and exclusion are scored
independently against all cases.

Usage:
    python -m scripts.eval_baseline
"""
import json
from pathlib import Path

from pipeline.ingest import ingest_bundle
from pipeline.baseline import run_baseline

GOLD_DIR = Path(__file__).parent.parent / "data" / "synthetic" / "gold"
MEASURES = ["diabetes_hba1c", "ami_8a"]


def prf1(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4), "tp": tp, "fp": fp, "fn": fn}


def score_binary_field(pairs: list) -> dict:
    """pairs: list of (predicted: bool, gold: bool)"""
    tp = sum(1 for p, g in pairs if p and g)
    fp = sum(1 for p, g in pairs if p and not g)
    fn = sum(1 for p, g in pairs if not p and g)
    tn = sum(1 for p, g in pairs if not p and not g)
    result = prf1(tp, fp, fn)
    result["tn"] = tn
    result["n"] = len(pairs)
    result["accuracy"] = round((tp + tn) / len(pairs), 4) if pairs else 0.0
    return result


def evaluate_measure(measure_id: str) -> dict:
    measure_dir = GOLD_DIR / measure_id
    labels = json.loads((measure_dir / "labels.json").read_text())

    denom_pairs, excl_pairs, num_pairs = [], [], []
    mismatches = []

    for label in labels:
        case_id = label["case_id"]
        bundle = json.loads((measure_dir / "cases" / f"{case_id}.json").read_text())
        meta = ingest_bundle(bundle, measure_id)
        predicted = run_baseline(meta["resources"], measure_id)

        gold_denom = bool(label["denominator"])
        pred_denom = bool(predicted["denominator"])
        denom_pairs.append((pred_denom, gold_denom))

        if gold_denom:
            gold_excl = bool(label["exclusion"])
            pred_excl = bool(predicted["exclusion"])
            excl_pairs.append((pred_excl, gold_excl))

            if not gold_excl and label["numerator"] is not None:
                gold_num = bool(label["numerator"])
                pred_num = bool(predicted.get("numerator"))
                num_pairs.append((pred_num, gold_num))
                if pred_num != gold_num:
                    mismatches.append({"case_id": case_id, "case_type": label["case_type"], "field": "numerator",
                                        "predicted": pred_num, "gold": gold_num})

        if pred_denom != gold_denom:
            mismatches.append({"case_id": case_id, "case_type": label["case_type"], "field": "denominator",
                                "predicted": pred_denom, "gold": gold_denom})

    return {
        "measure_id": measure_id,
        "n_cases": len(labels),
        "denominator": score_binary_field(denom_pairs),
        "exclusion": score_binary_field(excl_pairs),
        "numerator": score_binary_field(num_pairs),
        "mismatches_by_case_type": _group_mismatches(mismatches),
        "mismatches": mismatches,
    }


def _group_mismatches(mismatches: list) -> dict:
    counts: dict = {}
    for m in mismatches:
        counts[m["case_type"]] = counts.get(m["case_type"], 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def main():
    report = {}
    for measure_id in MEASURES:
        result = evaluate_measure(measure_id)
        report[measure_id] = result

        print(f"\n=== {measure_id} (n={result['n_cases']}) — rules-only baseline ===")
        for field in ("denominator", "exclusion", "numerator"):
            s = result[field]
            print(f"  {field:12s} P={s['precision']:.3f}  R={s['recall']:.3f}  "
                  f"F1={s['f1']:.3f}  (n={s['n']}, tp={s['tp']} fp={s['fp']} fn={s['fn']} tn={s['tn']})")
        if result["mismatches_by_case_type"]:
            print("  mismatches by case_type:", result["mismatches_by_case_type"])

    out_path = GOLD_DIR / "baseline_results.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nFull report written to {out_path}")

    print("\n=== Headline numerator F1 (Phase 1 gate metric) ===")
    for measure_id in MEASURES:
        print(f"  {measure_id}: {report[measure_id]['numerator']['f1']:.3f}")


if __name__ == "__main__":
    main()
