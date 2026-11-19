"""Stress-test the fixed A-10 nearby inputs by excluding two districts."""

import json

import pandas as pd
from threadpoolctl import threadpool_limits

from evaluate_a10_nearby_context import MONTHS, OUTPUT, evaluate


def main():
    results = {}
    with threadpool_limits(limits=2):
        for month in MONTHS:
            results[month] = evaluate(month, holdout_size=2)
            print(f"Completed {month}", flush=True)
    (OUTPUT / "nearby_two_districts_evaluation.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    rows = [row for month in MONTHS for row in results[month]["summary"]]
    print(pd.DataFrame(rows)[["month", "industry_name", "method", "mae", "max_error", "better_folds"]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
