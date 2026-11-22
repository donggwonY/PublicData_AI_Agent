"""Export all 83 qualified industry comparisons and rebuild the local preview."""

import json

import numpy as np
import pandas as pd

from export_a10_app_comparison import MONTH, ROOT
from build_a10_area_comparison import build_preview


DOCS = ROOT / "docs/a10"


def main():
    validation = pd.read_csv(DOCS / "expanded_industry_validation.csv")
    if len(validation) != 83 or not validation.industry_code.is_unique:
        raise ValueError("Expected 83 unique qualified industries")
    if int(validation.confirmed_improvement.sum()) != 22:
        raise ValueError("Expected the reviewed 22 improved industry methods")
    validation["active_method"] = validation.selected_method.where(
        validation.confirmed_improvement, "poisson_context"
    )
    original = pd.read_csv(ROOT / f"data/raw/a10/industry_comparison_{MONTH}.csv", dtype={"admin_code": str})
    nearby = pd.read_csv(ROOT / f"data/raw/a10/expanded_nearby_predictions_{MONTH}.csv", dtype={"admin_code": str})
    keys = ["admin_code", "industry_code"]
    data = nearby.merge(validation[["industry_code", "active_method"]], on="industry_code", validate="many_to_one")
    reference = original.loc[original.industry_code.isin(validation.industry_code)]
    if len(data) != 12616 or data.duplicated(keys).any():
        raise ValueError("Expected 152 areas by 83 industries")
    if not data.groupby("industry_code").size().eq(152).all():
        raise ValueError("Each industry must cover 152 areas")
    merged = data.merge(reference[keys + ["actual_shops", "poisson_context"]], on=keys,
                        validate="one_to_one", suffixes=("", "_original"))
    if len(merged) != len(reference):
        raise ValueError("Lookup keys differ from the original evaluations")
    np.testing.assert_array_equal(merged.actual_shops, merged.actual_shops_original)
    np.testing.assert_allclose(merged.poisson_context, merged.poisson_context_original, atol=1e-10)
    data["estimated_shops"] = [row[row.active_method] for _, row in data.iterrows()]
    if not np.isfinite(data.estimated_shops).all() or data.estimated_shops.lt(0).any():
        raise ValueError("Invalid count estimate")
    data["base_month"] = MONTH
    output = data[keys + ["base_month", "actual_shops", "estimated_shops"]].sort_values(keys)
    output.to_csv(DOCS / "industry_comparison_app_83.csv", index=False, encoding="utf-8", lineterminator="\n")
    validation.to_csv(DOCS / "expanded_industry_validation.csv", index=False, encoding="utf-8", lineterminator="\n")
    evidence = {
        month: json.loads((ROOT / f"data/raw/a10/expanded_nearby_{month}.json").read_text(encoding="utf-8"))
        for month in ("2025-06", "2026-09", "2026-06")
    }
    (DOCS / "expanded_validation_summary.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    build_preview()
    print(f"Exported {len(output)} rows for {len(validation)} industries")


if __name__ == "__main__":
    main()
