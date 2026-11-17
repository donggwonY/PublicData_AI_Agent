"""Evaluate A-08 using 2 km holdout blocks and two prediction-grid origins."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from a08_error_analysis import BLOCK_SIZE, METHODS as DIAGNOSTIC_METHODS, summarize_errors
from evaluate_a08_spatial_units import (
    BUFFER_METERS, NEIGHBORS, POPULATION, ROOT, SCALES, grid, load_data, score, unit_counts, units,
    cell_compositions,
)


ORIGINS = (0, 125)
FOLD_COUNT = 5
COORDINATES = ["x", "y"]
LOCAL_PRIOR_WEIGHT = 100


def local_composition(train, test, class_count, prior):
    district_counts = pd.crosstab(train["district"], train["class"]).reindex(
        columns=range(class_count), fill_value=0,
    ).reindex(test["district"], fill_value=0).to_numpy()
    district = district_counts + LOCAL_PRIOR_WEIGHT * prior
    district /= district.sum(axis=1, keepdims=True)
    admin_counts = pd.crosstab(train["admin_code"], train["class"]).reindex(
        columns=range(class_count), fill_value=0,
    ).reindex(test["admin_code"], fill_value=0).to_numpy()
    admin = admin_counts + LOCAL_PRIOR_WEIGHT * district
    admin /= admin.sum(axis=1, keepdims=True)
    return district, admin


def neighborhood(centers, tree, reference_labels, class_count):
    k = min(NEIGHBORS, len(reference_labels))
    distances, neighbors = tree.query(centers[COORDINATES].to_numpy(), k=k)
    labels = reference_labels[neighbors]
    mix = np.column_stack([(labels == code).mean(axis=1) for code in range(class_count)])
    return mix, np.log1p(distances[:, [0, -1]])


def evaluate_scale(fit, test, reference, features, class_count, scale, origin, prior, evaluate):
    fit_groups, fit_units = units(fit, scale, features, origin)
    test_groups, test_units = units(test, scale, features, origin)
    centers = pd.concat([fit_units, test_units], ignore_index=True)
    mix, distances = neighborhood(centers, cKDTree(reference[COORDINATES]),
                                  reference["class"].to_numpy(), class_count)
    count = len(fit_units)
    counts = unit_counts(fit_groups, fit["class"].to_numpy(), count, class_count)
    sizes = counts.sum(axis=1)
    neighbor = (NEIGHBORS * mix[count:] + prior) / (NEIGHBORS + 1)
    results = {"neighbors": evaluate("neighbors", neighbor[test_groups])}
    for name, inputs in (
        ("shops", np.column_stack((mix, distances))),
        ("shops_population", np.column_stack((mix, distances, centers[features].to_numpy()))),
    ):
        scaler = StandardScaler().fit(inputs[:count], sample_weight=sizes)
        scaled = scaler.transform(inputs)
        model = Ridge(alpha=100).fit(scaled[:count], counts / sizes[:, None], sample_weight=sizes)
        predicted = np.maximum(model.predict(scaled[count:]), 1e-6)
        predicted /= predicted.sum(axis=1, keepdims=True)
        results[name] = evaluate(name, predicted[test_groups])
    return results


def run_fold(stores, features, classes, outside, held_out, blocks, buffer_meters, diagnostics=None):
    test = stores.iloc[held_out]
    available = stores.iloc[outside]
    test_xy, train_xy = (rows[COORDINATES].to_numpy() for rows in (test, available))
    distances, _ = cKDTree(test_xy).query(train_xy)
    eligible = distances > buffer_meters
    for origin in ORIGINS:
        prohibited = set(map(tuple, grid(test_xy, 500, origin)))
        eligible &= np.array([tuple(cell) not in prohibited for cell in grid(train_xy, 500, origin)])
    train = available.loc[eligible]
    # Separate labeled references from targets used to fit ridge.
    references = pd.util.hash_pandas_object(train["store_id"], index=False) % 2 == 0
    reference, fit = train.loc[references], train.loc[~references]
    if len(reference) < NEIGHBORS or fit.empty:
        raise ValueError("Insufficient training or reference shops")
    class_count = len(classes)
    prior = np.bincount(train["class"], minlength=class_count) + 1
    prior = prior / prior.sum()
    common_cells = grid(test_xy, 250)
    labels = test["class"].to_numpy()

    def evaluate(method, prediction):
        if diagnostics is not None and method in DIAGNOSTIC_METHODS:
            diagnostics[method].append(cell_compositions(labels, prediction, common_cells, class_count))
        return score(labels, prediction, common_cells, class_count)

    results = {"regional_mean": evaluate("regional_mean", np.tile(prior, (len(test), 1)))}
    district, admin = local_composition(train, test, class_count, prior)
    for name, predicted in (("district_mean", district), ("admin_mean", admin)):
        results[name] = evaluate(name, predicted)
    for name, scale in SCALES.items():
        for origin in ORIGINS if scale else (0,):
            prefix = f"{name}_origin_{origin}_"
            metrics = evaluate_scale(fit, test, reference, features, class_count, scale, origin, prior,
                                     lambda method, prediction: evaluate(prefix + method, prediction))
            results.update({prefix + method: result for method, result in metrics.items()})
    return {
        "test_rows": len(test), "test_blocks": len(set(blocks[held_out])),
        "fit_rows": len(fit), "reference_rows": len(reference),
        "buffer_rows": len(available) - len(train), "metrics": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stores", type=Path)
    parser.add_argument("population_month")
    parser.add_argument("--buffer-meters", type=int, default=BUFFER_METERS)
    parser.add_argument("--error-analysis", action="store_true")
    args = parser.parse_args()
    if args.buffer_meters < 0:
        parser.error("--buffer-meters must be nonnegative")
    stores, features, counts = load_data(args.stores, args.population_month)
    classes = sorted(stores["category"].unique())
    stores["class"] = pd.Categorical(stores["category"], categories=classes).codes
    _, blocks = np.unique(grid(stores[COORDINATES].to_numpy(), BLOCK_SIZE), axis=0, return_inverse=True)
    partitions = GroupKFold(FOLD_COUNT).split(stores, groups=blocks)
    diagnostics = {name: [] for name in DIAGNOSTIC_METHODS} if args.error_analysis else None
    with threadpool_limits(limits=2):
        folds = [
            run_fold(stores, features, classes, outside, test, blocks, args.buffer_meters, diagnostics)
            for outside, test in partitions
        ]
    if sum(fold["test_rows"] for fold in folds) != len(stores):
        raise ValueError("Fold counts do not cover the source")
    summary = {}
    for method in folds[0]["metrics"]:
        row = {
            metric: float(np.average([fold["metrics"][method][metric] for fold in folds],
                                     weights=[fold["test_rows"] for fold in folds]))
            for metric in ("shop_log_loss", "weighted_250m_composition_error")
        }
        row["macro_250m_error_min_10"] = float(np.average(
            [fold["metrics"][method]["macro_250m_error_min_10"] for fold in folds],
            weights=[fold["metrics"][method]["cells_min_10"] for fold in folds],
        ))
        summary[method] = row
    result = {
        "month": args.population_month, "counts": counts,
        "stores_sha256": hashlib.sha256(args.stores.read_bytes()).hexdigest(),
        "population_sha256": hashlib.sha256(POPULATION.read_bytes()).hexdigest(),
        "test_blocks": len(set(blocks)), "prediction_grid_origins_m": ORIGINS,
        "buffer_meters": args.buffer_meters,
        "folds": folds, "summary": summary,
    }
    suffix = "" if args.buffer_meters == BUFFER_METERS else f"_buffer_{args.buffer_meters}m"
    path = ROOT / f"a08/spatial_block_evaluation_{args.population_month}{suffix}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if diagnostics is not None:
        errors = summarize_errors(diagnostics, classes)
        error_path = ROOT / f"a08/spatial_errors_{args.population_month}{suffix}.json"
        error_path.write_text(json.dumps(errors, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.population_month, args.buffer_meters, "m;", counts["analysis_rows"],
          "shops;", result["test_blocks"], "blocks")
    for method, metrics in summary.items():
        print(method, *(f"{value:.5f}" for value in metrics.values()))


if __name__ == "__main__":
    main()
