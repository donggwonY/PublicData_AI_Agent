"""Independent saved-aggregate audit; no refitting, DB, or held-out data access."""
import json
import math
from pathlib import Path
from snapshot_hashes import snapshot_sha256

ROOT = Path(__file__).resolve().parents[1]

def audit(data):
    checks = 0
    def check(ok):
        nonlocal checks
        if not ok:
            raise ValueError("D03 ensemble aggregate inconsistency")
        checks += 1
    def near(a, b):
        check(math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-10))
    summaries = []
    candidates = ["constant", "logistic", "blend_logistic", "extra_trees", "blend_extra_trees"]
    for window in data["windows"]:
        scores = window["scores"]
        base = scores["global_regularized"]
        # Whole-year splits leave a full observation year before the next stage.
        check(window["calibration_year"] >= window["train_end"] + 2)
        check(int(window["window"].split("-")[0]) >= window["calibration_year"] + 2)
        for model, score in scores.items():
            check((score["n"], score["events"]) == (base["n"], base["events"]))
            near(score["actual_pct"], 100 * score["events"] / score["n"])
            for field in ["gu", "category"]:
                rows = [r for r in data["subgroups"] if (r["window"], r["model"], r["field"]) == (window["window"], model, field)]
                check(bool(rows))
                check(len({r["group"] for r in rows}) == len(rows))
                check(sum(r["n"] for r in rows) == score["n"])
                check(sum(r["events"] for r in rows) == score["events"])
                for r in rows:
                    near(r["actual_pct"], 100 * r["events"] / r["n"])
                for metric in ["actual_pct", "predicted_pct", "brier", "log_loss"]:
                    near(sum(r[metric] * r["n"] for r in rows) / score["n"], score[metric])
        item = {"window": window["window"], "n": base["n"], "events": base["events"],
                "blend_brier_delta": scores["blend_logistic"]["brier"] - base["brier"],
                "blend_log_loss_delta": scores["blend_logistic"]["log_loss"] - base["log_loss"]}
        for field in ["gu", "category"]:
            rows = [r for r in data["subgroups"] if r["window"] == window["window"] and r["field"] == field]
            before = {r["group"]: r for r in rows if r["model"] == "global_regularized"}
            after = {r["group"]: r for r in rows if r["model"] == "blend_logistic"}
            check(before.keys() == after.keys())
            item[field] = {"groups": len(before), "brier_worse": sum(after[g]["brier"] > before[g]["brier"] for g in before)}
        summaries.append(item)
    passed = [m for m in candidates if all(w["scores"][m][metric] < w["scores"][b][metric] for w in data["windows"] for b in ["global", "global_regularized"] for metric in ["brier", "log_loss"])]
    check(passed == data["passed"])
    return {"checks_passed": checks, "windows": summaries, "passed_candidates": passed}

def main():
    source = ROOT / "docs/d03/ensemble_results.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    result = audit(data)
    # Make sure an inconsistent event count is actually rejected.
    import copy
    broken = copy.deepcopy(data)
    broken["subgroups"][0]["events"] += 1
    try:
        audit(broken)
    except ValueError:
        result["mutation_check"] = "altered subgroup event count rejected"
    else:
        raise AssertionError("audit failed to reject changed evidence")
    result.update(date="2026-11-02", scope="saved historical aggregate audit, not independent refit or new-cutoff validation", input_sha256=snapshot_sha256(source))
    (ROOT / "docs/a04/ensemble_review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
