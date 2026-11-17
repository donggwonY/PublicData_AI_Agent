"""Measure how selective comparison messages perform on saved A-07 predictions."""

import csv
import hashlib
import json
from collections import defaultdict
from itertools import combinations

from evaluate_a07_baselines import DATA, sign


CUTOFFS = (0, 10, 25, 50, 75, 100, 150, 200)
METHODS = ("model_change", "baseline_change")
MIN_ACCURACY = 0.90
MIN_COVERAGE = 0.25
COVERAGE_PERCENTAGES = (25, 50, 55, 75, 90)


def summarize(pairs, accepts):
    shown = [correct for gap, correct in pairs if accepts(gap)]
    return {
        "shown": len(shown),
        "correct": sum(shown),
        "coverage": len(shown) / len(pairs),
        "accuracy": sum(shown) / len(shown) if shown else None,
    }


def collect(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return collect_rows(csv.DictReader(handle))


def collect_rows(records):
    months = defaultdict(list)
    for row in records:
        months[row["base_month"]].append(row)
    pairs = {method: {} for method in METHODS}
    for month, rows in sorted(months.items()):
        rows.sort(key=lambda row: row["admin_code"])
        for method in METHODS:
            pairs[method][month] = []
        for left, right in combinations(rows, 2):
            actual = sign(int(left["actual_change"]) - int(right["actual_change"]))
            for method in METHODS:
                predicted = int(left[method]) - int(right[method])
                pairs[method][month].append((abs(predicted), actual != 0 and sign(predicted) == actual))
    return pairs


def evaluate(pairs, cutoffs=CUTOFFS):
    pairs = [pair for month_pairs in pairs.values() for pair in month_pairs]
    return {
        "total_pairs": len(pairs),
        "cutoffs": {
            str(cutoff): summarize(pairs, lambda gap: gap > 0 and gap >= cutoff)
            for cutoff in cutoffs
        },
        "bands": {
            f"{low}-{high}": summarize(pairs, lambda gap: low <= gap < high)
            for low, high in zip(cutoffs, cutoffs[1:] + (float("inf"),))
        },
    }


def equal_coverage(pairs, cutoff):
    model_months = pairs["model_change"]
    baseline_months = pairs["baseline_change"]
    sizes = {month: len(rows) for month, rows in model_months.items()}
    if sizes != {month: len(rows) for month, rows in baseline_months.items()}:
        raise ValueError("Both methods must evaluate the same monthly cohorts")
    budgets = {
        str(percentage): {month: size * percentage // 100 for month, size in sizes.items()}
        for percentage in COVERAGE_PERCENTAGES
    }
    if cutoff is not None:
        budgets["model_display_rule"] = {
            month: sum(gap > 0 and gap >= cutoff for gap, _ in rows)
            for month, rows in model_months.items()
        }
    ranked = {
        method: {month: sorted(rows, key=lambda pair: -pair[0]) for month, rows in months.items()}
        for method, months in pairs.items()
    }
    results = {}
    for label, budget in budgets.items():
        shown = sum(budget.values())
        correct = {
            method: {
                month: sum(hit for _, hit in rows[:budget[month]])
                for month, rows in months.items()
            }
            for method, months in ranked.items()
        }
        results[label] = {
            "shown_per_method": shown,
            "coverage": shown / sum(sizes.values()),
            "monthly_budgets": budget,
            "correct_by_method_and_month": correct,
            "accuracy": {method: sum(counts.values()) / shown for method, counts in correct.items()},
        }
    return results


def main():
    inputs = {split: DATA / f"model_predictions_{split}.csv" for split in ("development", "final")}
    cohorts = {split: collect(path) for split, path in inputs.items()}
    development = {method: evaluate(pairs) for method, pairs in cohorts["development"].items()}
    chosen = next((
        cutoff for cutoff in CUTOFFS
        if (development["model_change"]["cutoffs"][str(cutoff)]["accuracy"] or 0) >= MIN_ACCURACY
        and development["model_change"]["cutoffs"][str(cutoff)]["coverage"] >= MIN_COVERAGE
    ), None)
    final = {method: evaluate(pairs) for method, pairs in cohorts["final"].items()}
    result = {
        "prediction_sha256": {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in inputs.items()},
        "selection": {"min_accuracy": MIN_ACCURACY, "min_coverage": MIN_COVERAGE, "cutoff": chosen},
        "development": development, "final": final,
        "equal_coverage": {split: equal_coverage(pairs, chosen) for split, pairs in cohorts.items()},
    }
    (DATA / "comparison_evaluation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("cutoff", chosen)
    for split in ("development", "final"):
        for method in METHODS:
            print(split, method, result[split][method]["total_pairs"])
            for cutoff, metrics in result[split][method]["cutoffs"].items():
                print(cutoff, metrics)


if __name__ == "__main__":
    main()
