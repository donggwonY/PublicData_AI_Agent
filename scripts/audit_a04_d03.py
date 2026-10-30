"""Independent arithmetic audit of saved D03 evidence; no training or DB writes."""
import json
import math
from pathlib import Path
from snapshot_hashes import snapshot_sha256
ROOT = Path(__file__).resolve().parents[1]

def main():
    source = ROOT / "docs/d03"
    names = ["area_calibration", "area_subgroups", "group_calibration"]
    data = {n: json.loads((source / (n + ".json")).read_text(encoding="utf-8")) for n in names}
    checks = 0
    def check(condition):
        nonlocal checks
        if not condition:
            raise AssertionError("Saved evidence is inconsistent")
        checks += 1
    def near(a, b):
        check(math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-10))
    cal, sub, grp = (data[n] for n in names)
    for name, score in cal["scores"].items():
        check((score["n"], score["events"]) == (1608, 168))
        near(score["actual_pct"], score["events"] / score["n"] * 100)
        for key in ["n", "events", "actual_pct", "predicted_pct", "brier", "log_loss", "roc_auc"]:
            near(score[key], sub["scores"][name][key])
    grouped = []
    for field in sorted({r["field"] for r in sub["subgroups"]}):
        rows = [r for r in sub["subgroups"] if r["field"] == field]
        for side, model in [("before", "calibration_base_rf"), ("after", "sigmoid_rf")]:
            target = cal["scores"][model]
            check(sum(r[side]["n"] for r in rows) == target["n"])
            check(sum(r[side]["events"] for r in rows) == target["events"])
            for metric in ["brier", "log_loss", "actual_pct", "predicted_pct"]:
                near(sum(r[side][metric] * r[side]["n"] for r in rows) / target["n"], target[metric])
        grouped.append({"field": field, "groups": len(rows), "brier_worse": sum(r["after"]["brier"] > r["before"]["brier"] for r in rows)})
    comparisons = []
    for w in grp["windows"]:
        base = w["scores"]["global"]
        for name, score in w["scores"].items():
            check((score["n"], score["events"]) == (base["n"], base["events"]))
            near(score["actual_pct"], score["events"] / score["n"] * 100)
            for field in ["gu", "category"]:
                rows = [r for r in grp["subgroups"] if r["window"] == w["window"] and r["model"] == name and r["field"] == field]
                check(sum(r["n"] for r in rows) == score["n"])
                check(sum(r["events"] for r in rows) == score["events"])
                for metric in ["brier", "log_loss", "actual_pct", "predicted_pct"]:
                    near(sum(r[metric] * r["n"] for r in rows) / score["n"], score[metric])
        comparisons.append({"window": w["window"], "n": base["n"], "events": base["events"], "improved_vs_global": [name for name in ["gu", "category", "gu_category"] if all(w["scores"][name][m] < base[m] for m in ["brier", "log_loss"])]})
    passed = [name for name in ["gu", "category", "gu_category"] if all(w["scores"][name][m] < w["scores"][b][m] for w in grp["windows"] for b in ["global", "global_regularized"] for m in ["brier", "log_loss"])]
    check(passed == grp["passed"] == [])
    for metric, interval in cal["bootstrap_vs_same_base"]["metrics"].items():
        near(interval["difference"], cal["scores"]["sigmoid_rf"][metric] - cal["scores"]["calibration_base_rf"][metric])
        check(interval["lower95"] <= 0 <= interval["upper95"])
    result = {"date": "2026-10-30", "scope": "saved aggregate arithmetic audit, not independent model refit or future evaluation", "checks_passed": checks, "subgroup_summary": grouped, "historical_windows": comparisons, "passed_candidates": passed, "input_hashes": {n: snapshot_sha256(source / (n + ".json")) for n in names}}
    out = ROOT / "docs/a04"
    out.mkdir(exist_ok=True)
    (out / "d03_review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
if __name__ == "__main__":
    main()
