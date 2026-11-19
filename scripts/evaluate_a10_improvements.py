"""Audit source counts and compare fixed tree models for four A-10 industries."""

import json

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from threadpoolctl import threadpool_limits

from evaluate_a10_cafe_concentration import MONTHS, POPULATION, ROOT, load_inputs
from snapshot_hashes import snapshot_sha256, verify_snapshot_hash


CODES = ("I21201", "S20701", "I20101", "P10501")
OUTPUT = ROOT / "a10"


def evaluate(month):
    source, stores, population = load_inputs(month)
    manifest = json.loads((OUTPUT / "industry_inputs.json").read_text(encoding="utf-8"))
    verify_snapshot_hash(source, manifest["inputs"][month]["source_sha256"])
    verify_snapshot_hash(POPULATION, manifest["population_sha256"])
    saved = pd.read_csv(OUTPUT / f"industry_comparison_{month}.csv", dtype={"admin_code": str})
    population = population.loc[population.total.gt(0)].set_index("admin_code")
    totals = pd.crosstab(stores.admin_code, stores.industry).reindex(population.index, fill_value=0)
    all_results = []
    for code in CODES:
        target_stores = stores.loc[stores.subclass.eq(code)]
        parent, = target_stores.industry.unique()
        counts = target_stores.groupby("admin_code").size().reindex(population.index, fill_value=0)
        other = totals.copy()
        other[parent] -= counts
        assert other.ge(0).all().all()
        features = np.log1p(other.add_prefix("other_"))
        features["log_population"] = np.log1p(population.total)
        features["log_other_shops"] = np.log1p(other.sum(axis=1))
        for age in population.filter(regex="^age_").columns:
            features[age] = population[age] / population.total
        results = saved.loc[saved.industry_code.eq(code)].set_index("admin_code").reindex(population.index)
        np.testing.assert_array_equal(results.actual_shops, counts)
        np.testing.assert_array_equal(results.other_shops, other.sum(axis=1))
        assert len(results) == 152 and results.index.is_unique
        for district in sorted(results.district.unique()):
            train = results.district.ne(district)
            test = ~train
            factories = {
                "forest": RandomForestRegressor(n_estimators=150, min_samples_leaf=5, max_features=0.8, random_state=7, n_jobs=2),
                "boosting": HistGradientBoostingRegressor(loss="poisson", max_iter=150, max_leaf_nodes=7, min_samples_leaf=10, l2_regularization=1, learning_rate=0.05, random_state=7),
            }
            for name, model in factories.items():
                model.fit(features.loc[train], counts.loc[train])
                results.loc[test, name] = model.predict(features.loc[test])
        assert np.isfinite(results[["forest", "boosting"]]).all().all()
        results["month"] = month
        all_results.append(results)
    combined = pd.concat(all_results)
    combined.to_csv(OUTPUT / f"improvement_predictions_{month}.csv", index_label="admin_code", encoding="utf-8-sig")
    summary = []
    for code, group in combined.groupby("industry_code"):
        for method in ("population_rate", "other_shop_rate", "training_median", "poisson_scale", "poisson_context", "forest", "boosting"):
            errors = (group[method] - group.actual_shops).abs()
            summary.append({
                "month": month, "industry_code": code, "industry_name": group.industry_name.iloc[0],
                "method": method, "mae": errors.mean(), "max_absolute_error": errors.max(),
                "district_mae": errors.groupby(group.district).mean().to_dict(),
            })
    return {"source_sha256": snapshot_sha256(source), "summary": summary}


def main():
    with threadpool_limits(limits=2):
        results = {month: evaluate(month) for month in MONTHS}
    results["population_sha256"] = snapshot_sha256(POPULATION)
    (OUTPUT / "improvement_evaluation.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = [row for month in MONTHS for row in results[month]["summary"]]
    print(pd.DataFrame(rows).pivot(index=["month", "industry_name"], columns="method", values="mae").round(2).to_string())


if __name__ == "__main__":
    main()
