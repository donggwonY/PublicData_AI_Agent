"""Build Daegu neighborhood recommendations and check their temporal stability."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from evaluate_a08_spatial_units import POPULATION, ROOT, load_data


MONTHS = ("2025-06", "2026-09")
MIN_SHOPS = 50
TOP_K = 5
WEIGHTS = {"combined": 0.5, "business": 1.0, "population": 0.0}
PRIORITY_WEIGHT = 0.65


def area_profiles(month):
    path = ROOT / f"a08/daegu_stores_{month.replace('-', '')}.csv"
    stores, features, audit = load_data(path, month)
    shops = pd.crosstab(stores["admin_code"], stores["category"]).sort_index()
    people = pd.read_csv(POPULATION, dtype={"admin_code": str})
    people = people[people["month"].eq(month)].set_index("admin_code").loc[shops.index]
    age_fields = [field for field in features if field.startswith("age_")]
    if (people["total"] < 0).any() or not np.array_equal(
        people[age_fields].sum(axis=1).to_numpy(), people["total"].to_numpy()
    ):
        raise ValueError(f"Inconsistent population counts for {month}")
    unavailable = people["total"].eq(0)
    audit["zero_population_areas"] = people.index[unavailable].tolist()
    audit["shops_in_zero_population_areas"] = int(shops.loc[unavailable].to_numpy().sum())
    people = people.loc[~unavailable]
    shops = shops.loc[people.index]
    counts = shops.sum(axis=1)
    businesses = shops.div(counts, axis=0)
    ages = people[age_fields].div(people["total"], axis=0)
    entries = {
        code: {
            "name": people.loc[code, "admin_area"].removeprefix("대구광역시 "),
            "shops": int(counts.loc[code]),
            "residents": int(people.loc[code, "total"]),
            "business": businesses.loc[code].to_dict(),
            "population": ages.loc[code].to_dict(),
        }
        for code in shops.index
    }
    return entries, {**audit, "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def composition_distances(profiles, codes, weight):
    matrices = [np.sqrt([list(profiles[code][feature].values()) for code in codes])
                for feature in ("business", "population")]
    distances = []
    for values in matrices:
        # Squared Hellinger distance between two distributions.
        distances.append(np.square(values[:, None, :] - values[None, :, :]).sum(axis=2) / 2)
    mixed = weight * distances[0] + (1 - weight) * distances[1]
    np.fill_diagonal(mixed, np.inf)
    return mixed


def top_candidates(codes, distances):
    code_array = np.array(codes)
    return {
        code: code_array[np.argsort(distances[index], kind="stable")[:TOP_K]].tolist()
        for index, code in enumerate(codes)
    }


def rankings(profiles, codes, weight):
    return top_candidates(codes, composition_distances(profiles, codes, weight))


def scenario_comparison(profiles, codes, basic):
    sizes = np.array([[profiles[code]["shops"], profiles[code]["residents"]] for code in codes])
    size_gap = np.abs(sizes[:, None] - sizes[None, :]) / np.maximum(sizes[:, None], sizes[None, :])
    objectives = {"size": size_gap.mean(axis=2)}
    options = {}
    for group in ("business", "population"):
        for key in profiles[codes[0]][group]:
            mode = {("business", "음식"): "food", ("population", "age_00_09"): "children"}.get(
                (group, key), f"{group}:{key}"
            )
            values = np.array([profiles[code][group][key] for code in codes])
            objectives[mode] = np.abs(values[:, None] - values[None, :])
            options[mode] = {"group": group, "key": key}
    base_distance = composition_distances(profiles, codes, WEIGHTS["combined"])
    # Ranking each component per query makes different units comparable.
    base_rank = rankdata(base_distance, axis=1, method="average")
    idx = {code: index for index, code in enumerate(codes)}

    def average_gaps(rankings_by_area):
        pairs = [(idx[query], idx[neighbor]) for query, neighbors in rankings_by_area.items()
                 for neighbor in neighbors]
        rows, cols = np.array(pairs).T
        return {
            **{name: float(values[rows, cols].mean()) for name, values in objectives.items()},
            "shops_relative_gap": float(size_gap[rows, cols, 0].mean()),
            "residents_relative_gap": float(size_gap[rows, cols, 1].mean()),
            "composition_distance": float(base_distance[rows, cols].mean()),
        }

    summaries = {"basic": average_gaps(basic)}
    lists = {}
    for name, distance in objectives.items():
        np.fill_diagonal(distance, np.inf)
        ranks = rankdata(distance, axis=1, method="average")
        combined = (1 - PRIORITY_WEIGHT) * base_rank + PRIORITY_WEIGHT * ranks
        np.fill_diagonal(combined, np.inf)
        lists[name] = top_candidates(codes, combined)
        np.fill_diagonal(distance, 0)
        summaries[name] = average_gaps(lists[name])
    return {"priority_weight": PRIORITY_WEIGHT, "recommendations": lists, "mean_gaps": summaries,
            "options": options}


def stability(before, after):
    overlap = np.array([len(set(before[code]) & set(after[code])) for code in before])
    return {
        "query_areas": len(overlap), "mean_overlap_of_5": float(overlap.mean()),
        "at_least_3_in_both": float((overlap >= 3).mean()),
        "same_first": sum(before[code][0] == after[code][0] for code in before) / len(overlap),
    }


def build():
    inputs = {month: area_profiles(month) for month in MONTHS}
    profiles = {month: value[0] for month, value in inputs.items()}
    eligible = {month: {code for code, area in values.items() if area["shops"] >= MIN_SHOPS}
                for month, values in profiles.items()}
    before, latest = MONTHS
    codes = sorted(eligible[before] & eligible[latest])
    stability_results = {
        method: stability(rankings(profiles[before], codes, weight),
                          rankings(profiles[latest], codes, weight))
        for method, weight in WEIGHTS.items()
    }
    latest_codes = sorted(eligible[latest])
    recommended = rankings(profiles[latest], latest_codes, WEIGHTS["combined"])
    output = {
        "months": MONTHS, "minimum_shops": MIN_SHOPS, "top_k": TOP_K,
        "population_sha256": hashlib.sha256(POPULATION.read_bytes()).hexdigest(),
        "sources": {month: value[1] for month, value in inputs.items()},
        "profile_counts": {month: len(values) for month, values in profiles.items()},
        "eligible_counts": {month: len(values) for month, values in eligible.items()},
        "weights": WEIGHTS, "stability": stability_results,
        "profiles": profiles[latest], "recommendations": recommended,
        "scenarios": scenario_comparison(profiles[latest], latest_codes, recommended),
    }
    for code, neighbors in recommended.items():
        if code in neighbors or len(set(neighbors)) != TOP_K:
            raise ValueError(f"Invalid recommendation list for {code}")
    return output


if __name__ == "__main__":
    result = build()
    directory = ROOT / "a09"
    directory.mkdir(exist_ok=True)
    (directory / "similar_areas.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: result[k] for k in ("profile_counts", "eligible_counts", "stability")}, indent=2))
