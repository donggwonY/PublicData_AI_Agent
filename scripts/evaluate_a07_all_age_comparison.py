"""Calibrate age-specific display rules on development data, then evaluate them."""

import csv
import hashlib
import json
from collections import defaultdict

from evaluate_a07_baselines import DATA
from evaluate_a07_comparison import (
    CUTOFFS,
    METHODS,
    MIN_ACCURACY,
    MIN_COVERAGE,
    collect_rows,
    equal_coverage,
    evaluate,
)


EXTENDED_CUTOFFS = (0, 1, 2, 3, 5, 10, 15, 25, 35, 50, 75, 100, 150, 200,
                    250, 300, 400, 500, 750, 1000, 1500, 2000)


def meets_objective(result):
    return (result["accuracy"] or 0) >= MIN_ACCURACY and result["coverage"] >= MIN_COVERAGE


def assess_band(splits, cutoffs):
    development_pairs = collect_rows(splits["development"])
    development = {method: evaluate(pairs, cutoffs) for method, pairs in development_pairs.items()}
    chosen = {
        method: next((cutoff for cutoff in cutoffs
                      if meets_objective(development[method]["cutoffs"][str(cutoff)])), None)
        for method in METHODS
    }
    recent_pairs = collect_rows(splits["final"])
    recent = {method: evaluate(pairs, cutoffs) for method, pairs in recent_pairs.items()}
    rules = {}
    for method, cutoff in chosen.items():
        if cutoff is None:
            rules[method] = {"cutoff": None, "recent_meets_objective": False}
            continue
        metrics = recent[method]["cutoffs"][str(cutoff)]
        rules[method] = {
            "cutoff": cutoff,
            "development": development[method]["cutoffs"][str(cutoff)],
            "recent": metrics,
            "recent_meets_objective": meets_objective(metrics),
        }
    ridge_cutoff = chosen["model_change"]
    same_count = (equal_coverage(recent_pairs, ridge_cutoff)["model_display_rule"]
                  if ridge_cutoff is not None else None)
    return {"rules": rules, "same_count_as_ridge": same_count,
            "development": development, "recent": recent}


def main():
    directory = DATA / "all_ages"
    path = directory / "model_predictions_all_ages.csv"
    by_band = defaultdict(lambda: defaultdict(list))
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            by_band[row["band"]][row["split"]].append(row)
    results = {
        band: assess_band(splits, CUTOFFS if band == "age_00_09" else EXTENDED_CUTOFFS)
        for band, splits in by_band.items()
    }
    prior = json.loads((DATA / "comparison_evaluation.json").read_text(encoding="utf-8"))
    children = results["age_00_09"]["rules"]["model_change"]
    prior_cutoff = prior["selection"]["cutoff"]
    if (children["cutoff"] != prior_cutoff
            or children["recent"] != prior["final"]["model_change"]["cutoffs"][str(prior_cutoff)]):
        raise ValueError("The existing 0–9 rule did not reproduce")
    output = {
        "prediction_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "min_accuracy": MIN_ACCURACY, "min_coverage": MIN_COVERAGE, "bands": results,
    }
    (directory / "comparison_evaluation_all_ages.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    for band, result in results.items():
        print(band, result["rules"])
        if result["same_count_as_ridge"]:
            print("equal count", result["same_count_as_ridge"]["accuracy"])


if __name__ == "__main__":
    main()
