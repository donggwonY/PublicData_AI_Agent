"""Estimate current café counts from Daegu neighborhood context using spatial holdouts."""

import hashlib
import json

import numpy as np
import pandas as pd
from sklearn.linear_model import PoissonRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from evaluate_a08_spatial_units import POPULATION, ROOT


CAFE = "I21201"
MONTHS = ("2025-06", "2026-09")


def load_inputs(month):
    path = ROOT / f"a08/daegu_stores_{month.replace('-', '')}.csv"
    columns = {"상가업소번호": "shop_id", "행정동코드": "admin_code",
               "상권업종소분류코드": "subclass", "상권업종대분류코드": "industry"}
    stores = pd.read_csv(path, usecols=columns, dtype=str, encoding="utf-8-sig").rename(columns=columns)
    if stores.isna().any().any() or stores.shop_id.duplicated().any():
        raise ValueError("Missing shop attributes or duplicated shop IDs")
    stores["admin_code"] = stores["admin_code"].str.replace(r"^(\d{8})$", r"\g<1>00", regex=True)
    population = pd.read_csv(POPULATION, dtype={"admin_code": str})
    population = population.loc[population.month.eq(month)].copy()
    if population.admin_code.duplicated().any() or not stores.admin_code.isin(population.admin_code).all():
        raise ValueError("Population codes must uniquely cover shop areas")
    return path, stores, population


def load_profiles(month):
    path, stores, population = load_inputs(month)
    cafes = stores["subclass"].eq(CAFE)
    other = pd.crosstab(stores.loc[~cafes, "admin_code"], stores.loc[~cafes, "industry"])
    other.columns = [f"other_{name}" for name in other.columns]
    counts = stores.loc[cafes].groupby("admin_code").size().rename("cafes")
    profiles = population.set_index("admin_code").join([other, counts])
    count_columns = [*other.columns, "cafes"]
    profiles[count_columns] = profiles[count_columns].fillna(0).astype(int)
    audit = {
        "stores_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_shops": len(stores), "source_cafes": int(cafes.sum()),
        "zero_population_regions": profiles.index[profiles.total.eq(0)].tolist(),
        "cafes_excluded_by_zero_population": int(profiles.loc[profiles.total.eq(0), "cafes"].sum()),
    }
    profiles = profiles.loc[profiles.total.gt(0)].copy()
    profiles["district"] = profiles.index.str[:5]
    profiles["other_shops"] = profiles[other.columns].sum(axis=1)
    profiles["log_population"] = np.log1p(profiles.total)
    profiles["log_other_shops"] = np.log1p(profiles.other_shops)
    age_columns = [name for name in population if name.startswith("age_")]
    profiles[age_columns] = profiles[age_columns].div(profiles.total, axis=0)
    profiles[other.columns] = np.log1p(profiles[other.columns])
    return profiles, age_columns, list(other.columns), audit


def estimate_counts(profile, age, industries, include_median=False):
    configs = {
        "poisson_scale": ["log_population", "log_other_shops"],
        "poisson_context": ["log_population", "log_other_shops", *age, *industries],
    }
    parts = []
    for district in sorted(profile.district.unique()):
        fit = profile.loc[profile.district.ne(district)]
        test = profile.loc[profile.district.eq(district)]
        predictions = test[["admin_area", "district", "total", "other_shops", "cafes"]].copy()
        predictions["population_rate"] = test.total * fit.cafes.sum() / fit.total.sum()
        predictions["other_shop_rate"] = test.other_shops * fit.cafes.sum() / fit.other_shops.sum()
        if include_median:
            predictions["training_median"] = fit.cafes.median()
        for name, columns in configs.items():
            if not fit.cafes.any():
                predictions[name] = 0.0
                continue
            model = make_pipeline(StandardScaler(), PoissonRegressor(alpha=0.1, max_iter=1000))
            model.fit(fit[columns], fit.cafes)
            predictions[name] = model.predict(test[columns])
        parts.append(predictions)
    results = pd.concat(parts).sort_index()
    if not results.index.is_unique or not results.index.equals(profile.sort_index().index):
        raise ValueError("Each area must have exactly one out-of-district prediction")
    methods = ["population_rate", "other_shop_rate", *configs]
    if include_median:
        methods.append("training_median")
    if not np.isfinite(results[methods].to_numpy()).all():
        raise ValueError("Non-finite forecast")
    return results, methods


def evaluate(month):
    profile, age, industries, audit = load_profiles(month)
    results, methods = estimate_counts(profile, age, industries)
    errors = results[methods].sub(results.cafes, axis=0).abs()
    summary = {
        method: {
            "mae_shops": float(errors[method].mean()),
            "median_absolute_error": float(errors[method].median()),
            "rmse_shops": float(np.sqrt(np.square(errors[method]).mean())),
        } for method in methods
    }
    results["actual_minus_context"] = results.cafes - results.poisson_context
    output = ROOT / "a10"
    output.mkdir(exist_ok=True)
    results.to_csv(output / f"cafe_comparison_{month}.csv", encoding="utf-8-sig", index_label="admin_code")
    return {
        **audit, "areas": len(results), "districts": int(results.district.nunique()),
        "cafes_used": int(results.cafes.sum()), "summary": summary,
        "mae_by_district": errors.groupby(results.district).mean().to_dict(orient="index"),
    }


if __name__ == "__main__":
    with threadpool_limits(limits=2):
        results = {month: evaluate(month) for month in MONTHS}
    output = {"target_subclass": CAFE, "population_sha256": hashlib.sha256(POPULATION.read_bytes()).hexdigest(),
              "poisson_alpha": 0.1, "evaluations": results}
    (ROOT / "a10/cafe_evaluation.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(results, indent=2))
