"""Summarize common-grid errors by shop count and broad business category."""

import numpy as np
from pyproj import Transformer


METHODS = (
    "regional_mean", "admin_origin_0_shops_population",
    "grid_500_origin_0_shops_population", "grid_250_origin_0_shops_population",
)
COUNT_BANDS = (("1–4", 1, 5), ("5–9", 5, 10), ("10–24", 10, 25),
               ("25–49", 25, 50), ("50+", 50, None))
BLOCK_SIZE = 2000
EVALUATION_CELL_SIZE = 250


def compare_blocks(cells, sizes, distances):
    _, admin, _, fine = METHODS
    block_ids, index = np.unique(cells // (BLOCK_SIZE // EVALUATION_CELL_SIZE),
                                 axis=0, return_inverse=True)
    weights = np.bincount(index, weights=sizes)
    admin_error = np.bincount(index, weights=sizes * distances[admin]) / weights
    fine_error = np.bincount(index, weights=sizes * distances[fine]) / weights
    difference = fine_error - admin_error
    ties = np.isclose(difference, 0, atol=1e-12, rtol=0)
    # Break density ties by the block index, already sorted by coordinates.
    dense = np.argsort(-weights, kind="stable")[:(len(weights) + 9) // 10]
    other = np.ones(len(weights), dtype=bool)
    other[dense] = False
    return {
        "admin_wins": int(((difference > 0) & ~ties).sum()),
        "grid_250_wins": int(((difference < 0) & ~ties).sum()),
        "ties": int(ties.sum()),
        "mean_gap": float(difference.mean()),
        "median_gap": float(np.median(difference)),
        "weighted_gap": float(np.average(difference, weights=weights)),
        "dense_blocks": len(dense),
        "dense_shop_share": float(weights[dense].sum() / weights.sum()),
        "dense_gap": float(np.average(difference[dense], weights=weights[dense])),
        "excluding_dense_gap": float(np.average(difference[other], weights=weights[other])),
        "blocks": [
            {"block": key.tolist(), "shops": int(count), "admin_error": float(a),
             "grid_250_error": float(b)}
            for key, count, a, b in zip(block_ids, weights, admin_error, fine_error, strict=True)
        ],
    }


def summarize_errors(diagnostics, classes):
    cells, sizes, counts, _ = [
        np.concatenate(column) for column in zip(*diagnostics[METHODS[0]], strict=True)
    ]
    actual = counts / sizes[:, None]
    distances, predictions, categories = {}, {}, {}
    for method, folds in diagnostics.items():
        keys, weights, observed, predicted_counts = [
            np.concatenate(column) for column in zip(*folds, strict=True)
        ]
        if not all(np.array_equal(a, b) for a, b in ((cells, keys), (sizes, weights), (counts, observed))):
            raise ValueError("Each method must use the same evaluation cells and actual composition")
        predicted = predicted_counts / sizes[:, None]
        difference = predicted - actual
        predictions[method] = predicted
        distances[method] = np.abs(difference).sum(axis=1) / 2
        mae = np.average(np.abs(difference), axis=0, weights=sizes)
        bias = np.average(difference, axis=0, weights=sizes)
        categories[method] = {
            name: {"mae": float(error), "bias": float(signed)}
            for name, error, signed in zip(classes, mae, bias, strict=True)
        }
    density = {}
    for label, lower, upper in COUNT_BANDS:
        mask = sizes >= lower
        if upper is not None:
            mask &= sizes < upper
        density[label] = {
            "cells": int(mask.sum()), "shops": int(sizes[mask].sum()),
            "errors": {method: float(np.average(values[mask], weights=sizes[mask])) if mask.any() else None
                       for method, values in distances.items()},
        }
    eligible = np.flatnonzero(sizes >= 50)
    baseline, admin, _, fine = METHODS
    fine_delta = distances[fine][eligible] - distances[baseline][eligible]
    admin_delta = distances[admin][eligible] - distances[baseline][eligible]
    cases = {
        "fine_grid_largest_loss": eligible[fine_delta.argmax()],
        "fine_grid_largest_gain": eligible[fine_delta.argmin()],
        "admin_largest_gain": eligible[admin_delta.argmin()],
    } if len(eligible) else {}
    transform = Transformer.from_crs(5179, 4326, always_xy=True)
    examples = {}
    for name, index in cases.items():
        lon, lat = transform.transform(*(cells[index] * 250 + 125))
        examples[name] = {
            "cell": cells[index].tolist(), "center_lon_lat": [lon, lat],
            "shops": int(sizes[index]), "actual": dict(zip(classes, actual[index], strict=True)),
            "predicted": {method: dict(zip(classes, values[index], strict=True))
                          for method, values in predictions.items()},
            "errors": {method: float(values[index]) for method, values in distances.items()},
        }
    return {"density": density, "categories": categories, "examples": examples,
            "paired_blocks": compare_blocks(cells, sizes, distances)}
