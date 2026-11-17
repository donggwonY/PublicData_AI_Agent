"""Select and evaluate 12-month population regressors using monthly backtests."""

import csv
import hashlib
import json
from collections import defaultdict

import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from evaluate_a07_baselines import DATA, PERIODS, evaluate
from prepare_a07_population import shift_month


# Its last outcome was available when the first final prediction was issued.
SELECTION = ("2022-12", "2023-11")
CANDIDATES = {
    "ridge": lambda: make_pipeline(StandardScaler(), Ridge(alpha=10)),
    "hist_gradient_boosting": lambda: HistGradientBoostingRegressor(
        max_iter=100, max_leaf_nodes=15, min_samples_leaf=30,
        early_stopping=False, random_state=7,
    ),
}


def load_examples(panel):
    with panel.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    history = {(row["admin_code"], row["base_month"]): int(row["population_0_9"]) for row in rows}
    if len(history) != len(rows):
        raise ValueError("Duplicate area and month")
    examples = defaultdict(list)
    for row in rows:
        if row["usable_for_baseline_comparison"] != "1":
            continue
        month = row["base_month"]
        code = row["admin_code"]
        current = history[code, month]
        changes = [current - history[code, shift_month(month, -lag)] for lag in (3, 6, 12)]
        actual = int(row["change_after_12m"])
        examples[month].append((code, [current, *changes], actual))
    return examples


def backtest(examples, period, factory):
    records = []
    predictions = []
    monthly_training = {}
    for month, batch in sorted(examples.items()):
        if not period[0] <= month <= period[1]:
            continue
        last_train_month = shift_month(month, -12)
        train = [example for key, rows in examples.items() if key <= last_train_month
                 for example in rows]
        model = factory()
        model.fit([row[1] for row in train], [row[2] for row in train])
        forecast = model.predict([row[1] for row in batch])
        if not np.isfinite(forecast).all():
            raise ValueError(f"Non-finite predictions in {month}")
        monthly_training[month] = {"rows": len(train), "last_target_month": month}
        for (code, features, actual), predicted in zip(batch, forecast, strict=True):
            current, *changes = features
            baseline = max(0, current + changes[-1]) - current
            modeled = max(0, round(current + float(predicted))) - current
            records.append((actual, baseline, modeled, month))
            predictions.append({
                "admin_code": code, "base_month": month, "population_0_9": current,
                "target_month": shift_month(month, 12), "actual_change": actual,
                "baseline_change": baseline, "model_change": modeled,
            })
    return {
        "months": period, "rows": len(records), "monthly_training": monthly_training,
        "repeat_change": evaluate(records, 1), "model": evaluate(records, 2),
    }, predictions


def main():
    panel = DATA / "monthly_panel.csv"
    examples = load_examples(panel)
    with threadpool_limits(limits=2):
        selection = {
            name: backtest(examples, SELECTION, factory)[0]
            for name, factory in CANDIDATES.items()
        }
        winner = min(selection, key=lambda name: selection[name]["model"]["mae_people"])
        results = {}
        for label, period in PERIODS.items():
            results[label], predictions = backtest(examples, period, CANDIDATES[winner])
            with (DATA / f"model_predictions_{label}.csv").open(
                "w", encoding="utf-8-sig", newline=""
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=list(predictions[0]))
                writer.writeheader()
                writer.writerows(predictions)
    output = {
        "panel_sha256": hashlib.sha256(panel.read_bytes()).hexdigest(),
        "sklearn_version": sklearn.__version__,
        "selection": selection, "selected_model": winner, **results,
    }
    (DATA / "model_evaluation.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    for label, result in [*selection.items(), *results.items()]:
        print(label, result["rows"], result["repeat_change"], result["model"])
    print("selected:", winner)


if __name__ == "__main__":
    main()
