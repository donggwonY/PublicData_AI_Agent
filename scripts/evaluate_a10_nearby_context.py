"""Evaluate fixed nearby-area inputs for four A-10 shop-count models."""

import json
from itertools import combinations

import numpy as np
import pandas as pd
from sklearn.linear_model import PoissonRegressor
from sklearn.metrics.pairwise import haversine_distances
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from evaluate_a10_cafe_concentration import MONTHS, POPULATION, load_inputs
from evaluate_a10_improvements import CODES, OUTPUT
from snapshot_hashes import snapshot_sha256, verify_snapshot_hash


def nearby_weights(stores, coordinates, code, areas):
    # Target shops contribute neither counts nor location representatives.
    other = stores.loc[stores.subclass.ne(code)].join(coordinates.set_index("shop_id"), on="shop_id")
    valid = other.latitude.between(33, 39) & other.longitude.between(124, 132)
    centers = other.loc[valid].groupby("admin_code")[["latitude", "longitude"]].median().reindex(areas)
    located = centers.notna().all(axis=1).to_numpy()
    distance = haversine_distances(np.radians(centers.fillna(0))) * 6371
    distance[~located, :] = np.inf
    distance[:, ~located] = np.inf
    np.fill_diagonal(distance, np.inf)
    closest = np.argsort(distance, axis=1)[:, :3]
    weights = np.zeros_like(distance)
    weights[np.arange(len(areas))[:, None], closest] = np.isfinite(
        np.take_along_axis(distance, closest, axis=1)
    ) / 3
    if not np.allclose(weights.sum(axis=1), located.astype(int)) or np.diag(weights).any():
        raise ValueError("Invalid neighboring-area weights")
    return weights, int((~valid).sum()), centers.index[~located].tolist()


def evaluate(month, holdout_size=1):
    if holdout_size not in (1, 2):
        raise ValueError("Expected one or two held-out districts")
    source, stores, population = load_inputs(month)
    manifest = json.loads((OUTPUT / "industry_inputs.json").read_text(encoding="utf-8"))
    verify_snapshot_hash(source, manifest["inputs"][month]["source_sha256"])
    verify_snapshot_hash(POPULATION, manifest["population_sha256"])
    coordinates = pd.read_csv(source, usecols=["상가업소번호", "위도", "경도"],
                              dtype={"상가업소번호": str}).rename(columns={
                                  "상가업소번호": "shop_id", "위도": "latitude", "경도": "longitude"})
    population = population.loc[population.total.gt(0)].set_index("admin_code")
    totals = pd.crosstab(stores.admin_code, stores.industry).reindex(population.index, fill_value=0)
    saved = pd.read_csv(OUTPUT / f"industry_comparison_{month}.csv", dtype={"admin_code": str})
    parts, summaries, audits = [], [], []
    for code in CODES:
        if holdout_size == 2 and code not in ("I20101", "P10501"):
            continue
        target = stores.loc[stores.subclass.eq(code)]
        parent, = target.industry.unique()
        counts = target.groupby("admin_code").size().reindex(population.index, fill_value=0)
        other = totals.copy()
        other[parent] -= counts
        weights, missing, missing_areas = nearby_weights(stores, coordinates, code, population.index)
        features = np.log1p(other.add_prefix("other_"))
        features["log_population"] = np.log1p(population.total)
        features["log_other_shops"] = np.log1p(other.sum(axis=1))
        for age in population.filter(regex="^age_").columns:
            features[age] = population[age] / population.total
        original_columns = ["log_population", "log_other_shops",
                            *population.filter(regex="^age_").columns,
                            *other.add_prefix("other_").columns]
        features = features[original_columns]
        features["near_population"] = np.log1p(weights @ population.total.to_numpy())
        features["near_shops"] = np.log1p(weights @ other.sum(axis=1).to_numpy())
        features["near_location_missing"] = population.index.isin(missing_areas).astype(int)
        scale_columns = [*original_columns, "near_population", "near_shops", "near_location_missing"]
        for industry in other:
            features[f"near_{industry}"] = np.log1p(weights @ other[industry].to_numpy())
        configs = {
            "reproduced_context": original_columns,
            "nearby_scale": scale_columns,
            "nearby_industries": list(features.columns),
        }
        if holdout_size == 2:
            selected = "nearby_scale" if code == "I20101" else "nearby_industries"
            configs = {name: configs[name] for name in ("reproduced_context", selected)}
        results = saved.loc[saved.industry_code.eq(code)].set_index("admin_code").reindex(population.index)
        np.testing.assert_array_equal(results.actual_shops, counts)
        np.testing.assert_array_equal(results.other_shops, other.sum(axis=1))
        folds = []
        for districts in combinations(sorted(results.district.unique()), holdout_size):
            train = ~results.district.isin(districts)
            predictions = results.loc[~train].copy()
            for name, columns in configs.items():
                model = make_pipeline(StandardScaler(), PoissonRegressor(alpha=0.1, max_iter=1000))
                model.fit(features.loc[train, columns], counts.loc[train])
                predictions[name] = model.predict(features.loc[~train, columns])
            predictions["heldout_districts"] = "+".join(map(str, districts))
            folds.append(predictions)
        results = pd.concat(folds)
        if holdout_size == 1:
            selected = {"I20101": "nearby_scale", "P10501": "nearby_industries"}.get(
                code, "reproduced_context"
            )
            full_model = make_pipeline(StandardScaler(), PoissonRegressor(alpha=0.1, max_iter=1000))
            full_model.fit(features[configs[selected]], counts)
            full_predictions = pd.Series(full_model.predict(features[configs[selected]]), index=features.index)
            results["full_fit_estimate"] = results.index.map(full_predictions)
        if holdout_size == 1:
            np.testing.assert_allclose(results.poisson_context, results.reproduced_context, atol=1e-7)
        if not np.isfinite(results[list(configs)]).all().all():
            raise ValueError("Non-finite model estimate")
        results["month"] = month
        for name in configs:
            errors = (results[name] - results.actual_shops).abs()
            old_errors = (results.reproduced_context - results.actual_shops).abs()
            district_errors = errors.groupby(results.district).mean()
            district_old = old_errors.groupby(results.district).mean()
            summaries.append({
                "month": month, "industry_code": code, "industry_name": results.industry_name.iloc[0],
                "method": name, "mae": errors.mean(), "max_error": errors.max(),
                "better_districts": int((district_errors < district_old - 1e-8).sum()),
                "district_mae": district_errors.to_dict(),
                "better_folds": int((
                    errors.groupby(results.heldout_districts).mean()
                    < old_errors.groupby(results.heldout_districts).mean() - 1e-8
                ).sum()),
            })
        audits.append({"industry_code": code, "non_target_shops_without_valid_coordinates": missing,
                       "areas_without_non_target_shop_coordinates": missing_areas})
        parts.append(results)
    prefix = "nearby" if holdout_size == 1 else "nearby_two_districts"
    pd.concat(parts).to_csv(OUTPUT / f"{prefix}_predictions_{month}.csv", index_label="admin_code", encoding="utf-8-sig")
    return {"source_sha256": snapshot_sha256(source), "location_audit": audits, "summary": summaries}


def main():
    with threadpool_limits(limits=2):
        result = {month: evaluate(month) for month in MONTHS}
    (OUTPUT / "nearby_evaluation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = [row for month in MONTHS for row in result[month]["summary"]]
    print(pd.DataFrame(rows).pivot(index=["month", "industry_name"], columns="method", values="mae").round(2).to_string())


if __name__ == "__main__":
    main()
