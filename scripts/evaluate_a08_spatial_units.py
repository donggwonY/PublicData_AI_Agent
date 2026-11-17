"""Compare business-mix estimates across three scales on common spatial holdouts."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits


ROOT = Path(__file__).resolve().parents[1] / "data/raw"
POPULATION = ROOT / "a07_population/all_ages/monthly_all_ages.csv"
SCALES = {"admin": None, "grid_250": 250, "grid_500": 500}
BUFFER_METERS = 500
NEIGHBORS = 200


def grid(coords, size, origin=0):
    return np.floor((coords - origin) / size).astype(int)


def unit_keys(stores, scale, origin=0):
    if scale is None:
        return stores[["district", "admin_code"]]
    coords = grid(stores[["x", "y"]].to_numpy(), scale, origin)
    return stores[["district"]].assign(i=coords[:, 0], j=coords[:, 1])


def load_data(path, month):
    labels = {
        "상가업소번호": "store_id", "시군구코드": "district", "행정동코드": "admin_code",
        "상권업종대분류명": "category", "경도": "longitude", "위도": "latitude",
    }
    raw = pd.read_csv(path, encoding="utf-8-sig", usecols=labels, dtype=str).rename(columns=labels)
    if raw["store_id"].isna().any() or raw["store_id"].duplicated().any():
        raise ValueError("Store identifiers must be unique and nonempty")
    coords = raw[["longitude", "latitude"]].apply(pd.to_numeric, errors="coerce")
    valid = (coords.longitude.between(128, 130) & coords.latitude.between(35, 37)
             & raw["category"].notna() & raw["district"].str.startswith("27", na=False))
    stores = raw.loc[valid].copy()
    stores["admin_code"] = stores["admin_code"].str.replace(r"^(\d{8})$", r"\g<1>00", regex=True)
    transform = Transformer.from_crs(4326, 5179, always_xy=True)
    stores["x"], stores["y"] = transform.transform(coords.longitude[valid].to_numpy(),
                                                 coords.latitude[valid].to_numpy())
    population = pd.read_csv(POPULATION, dtype={"admin_code": str})
    population = population.loc[population["month"].eq(month)].drop(columns=["month", "admin_area"])
    if population.empty or population["admin_code"].duplicated().any():
        raise ValueError(f"Population month missing or duplicated: {month}")
    ages = [name for name in population if name.startswith("age_")]
    population["log_population"] = np.log1p(population["total"])
    population[ages] = population[ages].div(population["total"].replace(0, np.nan), axis=0).fillna(0)
    features = ["log_population", *ages]
    joined = stores.merge(population[["admin_code", *features]], how="inner",
                          on="admin_code", validate="many_to_one")
    if joined["category"].nunique() != 10 or joined["district"].nunique() < 8:
        raise ValueError("Unexpected category or district coverage")
    counts = {"source_rows": len(raw), "invalid_records": int((~valid).sum()),
              "missing_population_join": len(stores) - len(joined), "analysis_rows": len(joined)}
    counts["unmatched_admin_codes"] = stores.loc[
        ~stores["admin_code"].isin(population["admin_code"]), "admin_code"
    ].value_counts(dropna=False).rename_axis("admin_code").reset_index(name="rows").fillna("").to_dict("records")
    return joined, features, counts


def units(stores, scale, features, origin=0):
    keys = unit_keys(stores, scale, origin)
    groups = keys.groupby(list(keys.columns), sort=True).ngroup().to_numpy()
    summary = stores[["district", "x", "y", *features]].groupby(groups).agg(
        {"district": "first", **{column: "mean" for column in ("x", "y", *features)}}
    )
    return groups, summary


def unit_counts(groups, labels, unit_count, class_count):
    counts = np.zeros((unit_count, class_count), dtype=int)
    np.add.at(counts, (groups, labels), 1)
    return counts


def neighbor_features(summary, train, classes):
    mixes = np.empty((len(summary), len(classes)))
    distances = np.empty((len(summary), 2))
    for district, rows in summary.groupby("district").groups.items():
        pool = train.loc[train["district"].ne(district)]
        tree = cKDTree(pool[["x", "y"]].to_numpy())
        k = min(NEIGHBORS, len(pool))
        if k < 2:
            raise ValueError("Insufficient shops outside the target district")
        distances_m, index = tree.query(summary.loc[rows, ["x", "y"]].to_numpy(), k=k)
        nearest_classes = pool["class"].to_numpy()[index]
        mixes[rows] = np.column_stack([(nearest_classes == category).mean(axis=1)
                                       for category in range(len(classes))])
        distances[rows] = np.log1p(distances_m[:, [0, -1]])
    return mixes, distances


def cell_compositions(labels, predictions, cells, class_count):
    unique_cells, group = np.unique(cells, axis=0, return_inverse=True)
    counts = unit_counts(group, labels, int(group.max()) + 1, class_count)
    sizes = counts.sum(axis=1)
    predicted_counts = np.zeros(counts.shape)
    np.add.at(predicted_counts, group, predictions)
    return unique_cells, sizes, counts, predicted_counts


def score(labels, predictions, cells, class_count):
    _, sizes, counts, predicted_counts = cell_compositions(labels, predictions, cells, class_count)
    composition_error = np.abs(counts - predicted_counts).sum(axis=1) / (2 * sizes)
    populated = sizes >= 10
    return {
        "shop_log_loss": float(-np.log(predictions[np.arange(len(labels)), labels]).mean()),
        "weighted_250m_composition_error": float(np.average(composition_error, weights=sizes)),
        "macro_250m_error_min_10": float(composition_error[populated].mean()) if populated.any() else None,
        "cells": len(sizes), "cells_min_10": int(populated.sum()),
    }


def run_fold(stores, features, classes, held_out):
    test = stores.loc[stores["district"].eq(held_out)].reset_index(drop=True)
    outside = stores.loc[stores["district"].ne(held_out)]
    test_coords = test[["x", "y"]].to_numpy()
    outside_coords = outside[["x", "y"]].to_numpy()
    distance, _ = cKDTree(test_coords).query(outside_coords)
    blocked_cells = set(map(tuple, grid(test_coords, 500)))
    eligible = np.array([tuple(cell) not in blocked_cells for cell in grid(outside_coords, 500)])
    train = outside.loc[(distance > BUFFER_METERS) & eligible].reset_index(drop=True)
    if train.empty:
        raise ValueError(f"Empty training cohort for {held_out}")
    class_count = len(classes)
    labels = test["class"].to_numpy()
    common_cells = grid(test_coords, 250)
    prior = np.bincount(train["class"], minlength=class_count) + 1
    prior = prior / prior.sum()
    results = {"regional_mean": score(labels, np.tile(prior, (len(test), 1)), common_cells, class_count)}
    for name, scale in SCALES.items():
        train_groups, train_units = units(train, scale, features)
        test_groups, test_units = units(test, scale, features)
        mixes, distances = neighbor_features(pd.concat([train_units, test_units], ignore_index=True),
                                            train, classes)
        counts = unit_counts(train_groups, train["class"].to_numpy(), len(train_units), class_count)
        sizes = counts.sum(axis=1)
        target = counts / sizes[:, None]
        test_neighbor = mixes[len(train_units):][test_groups]
        smoothed_neighbor = (test_neighbor * NEIGHBORS + prior) / (NEIGHBORS + 1)
        results[f"{name}_neighbors"] = score(labels, smoothed_neighbor, common_cells, class_count)
        for suffix, inputs in (
            ("shops", np.column_stack((mixes, distances))),
            ("shops_population", np.column_stack((mixes, distances,
                pd.concat([train_units, test_units])[features].to_numpy()))),
        ):
            scaler = StandardScaler().fit(inputs[:len(train_units)], sample_weight=sizes)
            x = scaler.transform(inputs)
            model = Ridge(alpha=100).fit(x[:len(train_units)], target, sample_weight=sizes)
            prediction = np.maximum(model.predict(x[len(train_units):]), 1e-6)
            prediction /= prediction.sum(axis=1, keepdims=True)
            results[f"{name}_{suffix}"] = score(labels, prediction[test_groups], common_cells, class_count)
    return {"test_rows": len(test), "train_rows": len(train), "buffer_rows": len(outside) - len(train),
            "metrics": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stores", type=Path)
    parser.add_argument("population_month")
    args = parser.parse_args()
    stores, features, counts = load_data(args.stores, args.population_month)
    classes = sorted(stores["category"].unique())
    stores["class"] = pd.Categorical(stores["category"], categories=classes).codes
    with threadpool_limits(limits=2):
        folds = {district: run_fold(stores, features, classes, district)
                 for district in sorted(stores["district"].unique())}
    if sum(fold["test_rows"] for fold in folds.values()) != len(stores):
        raise ValueError("Each outlet must occur in exactly one test fold")
    summary = {
        method: {
            metric: float(np.average([fold["metrics"][method][metric] for fold in folds.values()],
                                     weights=[fold["test_rows"] for fold in folds.values()]))
            for metric in ("shop_log_loss", "weighted_250m_composition_error")
        }
        for method in next(iter(folds.values()))["metrics"]
    }
    output = {"stores_sha256": hashlib.sha256(args.stores.read_bytes()).hexdigest(),
              "population_sha256": hashlib.sha256(POPULATION.read_bytes()).hexdigest(),
              "population_month": args.population_month, "counts": counts,
              "categories": classes, "folds": folds, "summary": summary}
    path = ROOT / f"a08/spatial_unit_evaluation_{args.population_month}.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"counts": counts, "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
