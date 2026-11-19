"""Evaluate the fixed A-10 candidates on the previously unused June snapshot."""

import json

import pandas as pd
from threadpoolctl import threadpool_limits

from evaluate_a10_all_industries import evaluate_month
from evaluate_a10_improvements import CODES, OUTPUT
from evaluate_a10_nearby_context import evaluate
from snapshot_hashes import verify_snapshot_hash


MONTH = "2026-06"


def main():
    source = json.loads((OUTPUT / "202606_source.json").read_text(encoding="utf-8"))
    verify_snapshot_hash(OUTPUT.parent / "a08/daegu_stores_202606.csv", source["sha256"])
    with threadpool_limits(limits=2):
        details, summary, audit = evaluate_month(MONTH, codes=CODES)
        details.to_csv(OUTPUT / f"industry_comparison_{MONTH}.csv", index_label="admin_code", encoding="utf-8-sig")
        summary.to_csv(OUTPUT / f"industry_evaluation_{MONTH}.csv", index=False, encoding="utf-8-sig")
        manifest_path = OUTPUT / "industry_inputs.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["inputs"][MONTH] = audit
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        results = evaluate(MONTH)
    (OUTPUT / "additional_month_evaluation.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(pd.DataFrame(results["summary"])[[
        "industry_name", "method", "mae", "max_error", "better_districts"
    ]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
