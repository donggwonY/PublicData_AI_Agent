"""Export the validated A-07 ridge forecasts for use by the app."""

import hashlib
import json
from pathlib import Path

from threadpoolctl import threadpool_limits

from evaluate_a07_all_ages import make_examples, prepare_panel, read_csv, write_csv
from evaluate_a07_baselines import DATA
from evaluate_a07_models import CANDIDATES
from prepare_a07_population import shift_month


def export():
    age_path = DATA / "all_ages/monthly_all_ages.csv"
    reference_path = DATA / "monthly_panel.csv"
    evaluation = json.loads(
        (DATA / "all_ages/model_evaluation_all_ages.json").read_text(encoding="utf-8")
    )
    for key, path in (("age_input_sha256", age_path), ("reference_panel_sha256", reference_path)):
        if hashlib.sha256(path.read_bytes()).hexdigest() != evaluation[key]:
            raise ValueError(f"Forecast input must match the evaluated input: {path.name}")
    ages, reference = read_csv(age_path), read_csv(reference_path)
    bands = list(evaluation["bands"])
    panel, history = prepare_panel(reference, ages, bands)
    base = max(row["base_month"] for row in reference)
    target = shift_month(base, 12)
    latest = {row["admin_code"]: row for row in reference if row["base_month"] == base}
    rows = []
    with threadpool_limits(limits=2):
        for band in bands:
            training = [
                example for month, batch in make_examples(panel, history, band).items()
                if shift_month(month, 12) <= base for example in batch
            ]
            model = CANDIDATES[evaluation["model"]]()
            model.fit([row[1] for row in training], [row[2] for row in training])
            for code, row in sorted(latest.items()):
                current = int(history[code, base][band])
                estimate = None
                if row["history_12m_usable"] == "1":
                    features = [current, *(
                        current - int(history[code, shift_month(base, -lag)][band])
                        for lag in (3, 6, 12)
                    )]
                    estimate = max(0, round(current + float(model.predict([features])[0])))
                change = estimate - current if estimate is not None else None
                rows.append({
                    "admin_code": code, "admin_area": row["admin_area"],
                    "age_band": band, "base_month": base, "target_month": target,
                    "current_population": current, "forecast_population": estimate,
                    "forecast_change": change,
                    "forecast_change_pct": round(100 * change / current, 4)
                    if change is not None and current else None,
                    "status": "available" if estimate is not None else "withheld",
                    "withheld_reason": "" if estimate is not None else "incomparable_12_month_history",
                })
    frozen = DATA / f"frozen_{base}_to_{target}/forecast.csv"
    if frozen.exists():
        children = {row["admin_code"]: row for row in rows if row["age_band"] == "age_00_09"}
        for row in read_csv(frozen):
            estimate = children[row["admin_code"]]["forecast_population"]
            if ("" if estimate is None else str(estimate)) != row["model_population"]:
                raise ValueError(f"Forecast differs from the frozen 0–9 estimate: {row['admin_code']}")
    output = Path(__file__).resolve().parents[1] / f"output/a07_population_forecast_{target}.csv"
    output.parent.mkdir(exist_ok=True)
    write_csv(output, rows)
    print(f"{len(latest)} areas × {len(bands)} bands; "
          f"{sum(row['status'] == 'available' for row in rows)} available forecasts")
    print("SHA-256:", hashlib.sha256(output.read_bytes()).hexdigest())
    print(output)


if __name__ == "__main__":
    export()
