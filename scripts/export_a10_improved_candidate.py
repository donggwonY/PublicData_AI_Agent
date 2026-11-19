"""Build an A-10 candidate handoff and preserve the prior app export."""

import numpy as np
import pandas as pd

from export_a10_app_comparison import MONTH, ROOT


def main():
    folder = ROOT / "docs/a10"
    keys = ["admin_code", "industry_code"]
    old = pd.read_csv(folder / "industry_comparison_app.csv", dtype={"admin_code": str})
    nearby = pd.read_csv(ROOT / f"data/raw/a10/nearby_predictions_{MONTH}.csv", dtype={"admin_code": str})
    if old.duplicated(keys).any() or nearby.duplicated(keys).any():
        raise ValueError("Duplicate area-industry keys")
    merged = old.merge(nearby, on=keys, validate="one_to_one", suffixes=("_old", ""))
    if len(merged) != len(old) or len(merged) != 608:
        raise ValueError("All four industries and all areas must be covered")
    pd.testing.assert_frame_equal(old[keys].reset_index(drop=True), merged[keys].reset_index(drop=True))
    np.testing.assert_array_equal(merged.actual_shops_old, merged.actual_shops)
    np.testing.assert_allclose(merged.estimated_shops, merged.poisson_context)
    methods = merged.industry_code.map({"I20101": "nearby_scale", "P10501": "nearby_industries"}).fillna("poisson_context")
    merged["candidate_estimate"] = [
        row[method] for (_, row), method in zip(merged.iterrows(), methods)
    ]
    if not np.isfinite(merged.candidate_estimate).all() or merged.candidate_estimate.lt(0).any():
        raise ValueError("Invalid estimate")
    comparison = merged[keys + ["industry_name", "admin_area", "actual_shops", "estimated_shops", "candidate_estimate", "full_fit_estimate"]].copy()
    comparison["method"] = methods
    comparison["estimate_change"] = comparison.candidate_estimate - comparison.estimated_shops
    comparison.to_csv(folder / "improved_candidate_comparison.csv", index=False, encoding="utf-8", lineterminator="\n")
    candidate = old.copy()
    candidate["estimated_shops"] = merged.candidate_estimate.to_numpy()
    candidate.to_csv(folder / "industry_comparison_app_candidate.csv", index=False, encoding="utf-8", lineterminator="\n")
    for code, group in comparison.groupby("industry_code"):
        old_error = (group.estimated_shops - group.actual_shops).abs()
        new_error = (group.candidate_estimate - group.actual_shops).abs()
        print(group.industry_name.iloc[0], f"{old_error.mean():.2f} -> {new_error.mean():.2f}",
              "better/worse/equal", (new_error < old_error - 1e-7).sum(),
              (new_error > old_error + 1e-7).sum(), np.isclose(new_error, old_error, atol=1e-7).sum())
        if code in ("I20101", "P10501"):
            print(group.loc[group.estimate_change.abs().nlargest(3).index].round(2).to_string(index=False))


if __name__ == "__main__":
    main()
