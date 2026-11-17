"""Compare A-07 baselines on fixed, identical monthly cohorts."""

import csv
import hashlib
import itertools
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

from prepare_a07_population import shift_month


DATA = Path(__file__).resolve().parents[1] / "data/raw/a07_population"
PERIODS = {
    "development": ("2023-11", "2024-10"),
    "final": ("2024-11", "2025-10"),
}


def sign(value):
    return (value > 0) - (value < 0)


def evaluate(records, prediction_index):
    errors = [abs(row[prediction_index] - row[0]) for row in records]
    directions = [sign(row[prediction_index]) == sign(row[0]) for row in records]
    by_month = defaultdict(list)
    for row in records:
        by_month[row[3]].append(row)
    pair_hits = pair_count = 0
    for month_rows in by_month.values():
        for left, right in itertools.combinations(month_rows, 2):
            actual = sign(left[0] - right[0])
            if actual:
                pair_count += 1
                pair_hits += sign(left[prediction_index] - right[prediction_index]) == actual
    return {
        "mae_people": mean(errors),
        "direction_accuracy": mean(directions),
        "pair_hits": pair_hits,
        "pair_count": pair_count,
        "pair_accuracy": pair_hits / pair_count,
    }


def main():
    panel = DATA / "monthly_panel.csv"
    with panel.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    history = {(row["admin_code"], row["base_month"]): int(row["population_0_9"]) for row in rows}
    if len(history) != len(rows):
        raise ValueError("Duplicate administrative code and month")
    results = {}
    for label, (start, end) in PERIODS.items():
        selected = [
            row for row in rows
            if start <= row["base_month"] <= end and row["usable_for_baseline_comparison"] == "1"
        ]
        records = []
        for row in selected:
            month = row["base_month"]
            current = int(row["population_0_9"])
            previous = history[row["admin_code"], shift_month(month, -12)]
            actual = int(row["change_after_12m"])
            repeated_change = max(0, current + current - previous) - current
            records.append((actual, 0, repeated_change, month))
        results[label] = {
            "base_months": [start, end],
            "target_months": [shift_month(start, 12), shift_month(end, 12)],
            "rows": len(records),
            "areas": len({row["admin_code"] for row in selected}),
            "monthly_rows": dict(sorted((month, sum(row[3] == month for row in records))
                                        for month in {row[3] for row in records})),
            "persistence": evaluate(records, 1),
            "repeat_change": evaluate(records, 2),
        }
    results["panel_sha256"] = hashlib.sha256(panel.read_bytes()).hexdigest()
    output = json.dumps(results, indent=2)
    (DATA / "baseline_evaluation.json").write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
