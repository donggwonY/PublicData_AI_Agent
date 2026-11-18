"""Compare current shop counts across every observed A-10 industry subclass."""

import json

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from evaluate_a10_cafe_concentration import MONTHS, POPULATION, ROOT, estimate_counts, load_inputs
from snapshot_hashes import snapshot_sha256


OUTPUT = ROOT / "a10"


def evaluate_month(month):
    path, stores, population = load_inputs(month)
    label_columns = ["상권업종소분류코드", "상권업종소분류명"]
    labels = pd.read_csv(path, usecols=label_columns, dtype=str, encoding="utf-8-sig").drop_duplicates()
    names = labels.set_index(label_columns[0])[label_columns[1]]
    groups = stores[["subclass", "industry"]].drop_duplicates().set_index("subclass").industry
    if not groups.index.is_unique or not names.index.is_unique or names.isna().any():
        raise ValueError("Each subclass must have one label and parent industry per month")

    profile = population.loc[population.total.gt(0)].set_index("admin_code").copy()
    profile["district"] = profile.index.str[:5]
    profile["log_population"] = np.log1p(profile.total)
    ages = list(profile.filter(regex="^age_").columns)
    profile[ages] = profile[ages].div(profile.total, axis=0)
    subclasses = pd.crosstab(stores.admin_code, stores.subclass).reindex(profile.index, fill_value=0)
    industry_counts = pd.crosstab(stores.admin_code, stores.industry).reindex(profile.index, fill_value=0)
    source_shops = stores.loc[stores.admin_code.isin(profile.index)]
    if subclasses.to_numpy().sum() != len(source_shops):
        raise ValueError("Count matrix does not cover all eligible shops")
    source_counts = source_shops.subclass.value_counts()

    summaries = []
    details = []
    for code, parent in groups.sort_index().items():
        target = subclasses[code]
        other = industry_counts.copy()
        other[parent] -= target
        features = profile.assign(cafes=target, other_shops=other.sum(axis=1))
        features["log_other_shops"] = np.log1p(features.other_shops)
        other = np.log1p(other.add_prefix("other_"))
        features = features.join(other)
        estimates, methods = estimate_counts(features, ages, list(other.columns), include_median=True)
        estimates = estimates.rename(columns={"cafes": "actual_shops"})
        if estimates.actual_shops.sum() != source_counts.get(code, 0):
            raise ValueError(f"Wrong observed shop count for {code}")
        estimates.insert(0, "industry_code", code)
        estimates.insert(1, "industry_name", names[code])
        estimates["actual_minus_context"] = estimates.actual_shops - estimates.poisson_context
        details.append(estimates)

        errors = estimates[methods].sub(estimates.actual_shops, axis=0).abs()
        mae = errors.mean()
        baselines = mae.drop("poisson_context")
        strongest = baselines.idxmin()
        summaries.append({
            "industry_code": code, "industry_name": names[code], "areas": len(estimates),
            "shops": int(target.sum()), "occupied_areas": int(target.gt(0).sum()),
            "strongest_comparator": strongest,
            "beats_all_comparators": bool(mae.poisson_context < baselines[strongest] - 1e-9),
            "context_mae_on_occupied_areas": errors.loc[estimates.actual_shops.gt(0), "poisson_context"].mean(),
            **{f"{method}_mae": value for method, value in mae.items()},
        })
    return pd.concat(details), pd.DataFrame(summaries), {
        "source_sha256": snapshot_sha256(path),
        "source_shops": len(stores), "eligible_shops": len(source_shops),
        "regions": len(profile), "districts": profile.district.nunique(),
        "excluded_zero_population_codes": population.loc[population.total.eq(0), "admin_code"].tolist(),
    }


def main():
    OUTPUT.mkdir(exist_ok=True)
    inputs = {}
    summaries = []
    with threadpool_limits(limits=2):
        for month in MONTHS:
            details, summary, inputs[month] = evaluate_month(month)
            details.to_csv(OUTPUT / f"industry_comparison_{month}.csv", encoding="utf-8-sig", index_label="admin_code")
            summaries.append(summary.assign(month=month))
            wins = int(summary.beats_all_comparators.sum())
            print(f"{month}: {len(summary)} subclasses, {len(details)} estimates, {wins} wins", flush=True)
    combined = pd.concat(summaries, ignore_index=True)
    combined.to_csv(OUTPUT / "industry_evaluation.csv", encoding="utf-8-sig", index=False)
    manifest = {"population_sha256": snapshot_sha256(POPULATION), "inputs": inputs}
    (OUTPUT / "industry_inputs.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
