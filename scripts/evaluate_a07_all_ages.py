"""Evaluate the fixed A-07 ridge model separately for every published age band."""

import csv
import hashlib
import json
from collections import defaultdict

from threadpoolctl import threadpool_limits

from evaluate_a07_baselines import DATA, PERIODS
from evaluate_a07_models import CANDIDATES, backtest
from prepare_a07_population import shift_month


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def prepare_panel(reference, age_rows, bands):
    history = {(row["admin_code"], row["month"]): row for row in age_rows}
    expected = {(row["admin_code"], row["base_month"]) for row in reference}
    if len(history) != len(age_rows) or len(expected) != len(reference) or history.keys() != expected:
        raise ValueError("The all-age data and reference panel must have the same unique keys")
    panel = []
    for row in reference:
        code, month, target = (row[key] for key in ("admin_code", "base_month", "target_month"))
        current = history[code, month]
        if (current["admin_area"], current["age_00_09"]) != (row["admin_area"], row["population_0_9"]):
            raise ValueError(f"Reference data mismatch for {code} {month}")
        observed = history[code, target] if row["target_status"] == "matched" else None
        if observed is not None and observed["age_00_09"] != row["population_0_9_after_12m"]:
            raise ValueError(f"Reference target mismatch for {code} {target}")
        panel.append({
            "admin_code": code, "admin_area": row["admin_area"],
            "base_month": month, "target_month": target, "target_status": row["target_status"],
            "usable_for_baseline_comparison": row["usable_for_baseline_comparison"],
            **{band: int(current[band]) for band in bands},
            **{f"{band}_after_12m": int(observed[band]) if observed else None for band in bands},
        })
    return panel, history


def make_examples(panel, history, band):
    examples = defaultdict(list)
    for row in panel:
        if row["usable_for_baseline_comparison"] != "1":
            continue
        code, month = row["admin_code"], row["base_month"]
        current = row[band]
        changes = [current - int(history[code, shift_month(month, -lag)][band]) for lag in (3, 6, 12)]
        examples[month].append((code, [current, *changes], row[f"{band}_after_12m"] - current))
    return examples


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    directory = DATA / "all_ages"
    age_path = directory / "monthly_all_ages.csv"
    reference_path = DATA / "monthly_panel.csv"
    age_rows = read_csv(age_path)
    bands = [key for key in age_rows[0] if key == "total" or key.startswith("age_")]
    if len(bands) != 12:
        raise ValueError("Expected total population and 11 age groups")
    panel, history = prepare_panel(read_csv(reference_path), age_rows, bands)
    results = {}
    predictions = []
    with threadpool_limits(limits=2):
        for band in bands:
            examples = make_examples(panel, history, band)
            results[band] = {}
            for split, period in PERIODS.items():
                summary, rows = backtest(examples, period, CANDIDATES["ridge"])
                results[band][split] = summary
                predictions.extend({"band": band, "split": split, **row} for row in rows)
    prior = json.loads((DATA / "model_evaluation.json").read_text(encoding="utf-8"))
    for split in PERIODS:
        for method in ("model", "repeat_change"):
            if results["age_00_09"][split][method] != prior[split][method]:
                raise ValueError(f"The expanded 0–9 results do not reproduce {split} {method}")
    write_csv(directory / "monthly_panel_all_ages.csv", panel)
    write_csv(directory / "model_predictions_all_ages.csv", predictions)
    output = {
        "model": "ridge", "ridge_alpha": 10,
        "age_input_sha256": hashlib.sha256(age_path.read_bytes()).hexdigest(),
        "reference_panel_sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
        "bands": results,
    }
    (directory / "model_evaluation_all_ages.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    for band, splits in results.items():
        recent = splits["final"]
        print(band, recent["rows"], *(f"{recent[method]['mae_people']:.2f} "
              f"{recent[method]['direction_accuracy']:.2%} {recent[method]['pair_accuracy']:.2%}"
              for method in ("repeat_change", "model")))


if __name__ == "__main__":
    main()
