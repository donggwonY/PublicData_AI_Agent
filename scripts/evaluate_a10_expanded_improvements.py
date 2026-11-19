"""Evaluate fixed nearby features for all 83 previously qualified A-10 industries."""

import json

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from evaluate_a10_all_industries import evaluate_month
from evaluate_a10_improvements import OUTPUT
from evaluate_a10_nearby_context import POPULATION, evaluate
from snapshot_hashes import snapshot_sha256, verify_snapshot_hash


DEVELOPMENT_MONTHS = ("2025-06", "2026-09")
CONFIRMATION_MONTH = "2026-06"
METHODS = ("reproduced_context", "nearby_scale", "nearby_industries")


def main():
    original = pd.read_csv(OUTPUT / "industry_evaluation.csv")
    qualified = original.pivot(index="industry_code", columns="month", values="beats_all_comparators")
    codes = sorted(qualified.index[qualified[list(DEVELOPMENT_MONTHS)].eq(True).all(axis=1)])
    if len(codes) != 83:
        raise ValueError("Expected the original 83 qualified industry subclasses")
    results = {}
    algorithm_hash = snapshot_sha256(OUTPUT.parents[2] / "scripts/evaluate_a10_nearby_context.py")
    population_hash = snapshot_sha256(POPULATION)
    with threadpool_limits(limits=2):
        for month in DEVELOPMENT_MONTHS:
            checkpoint = OUTPUT / f"expanded_nearby_{month}.json"
            cached = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else {}
            if (cached.get("algorithm_sha256"), cached.get("population_sha256"), cached.get("industry_codes")) == (algorithm_hash, population_hash, codes):
                results[month] = cached
                verify_snapshot_hash(
                    OUTPUT.parent / f"a08/daegu_stores_{month.replace('-', '')}.csv",
                    cached["source_sha256"],
                )
            else:
                results[month] = evaluate(month, codes=codes, prefix="expanded_nearby", full_fit=False)
                results[month]["algorithm_sha256"] = algorithm_hash
                results[month]["population_sha256"] = population_hash
                results[month]["industry_codes"] = codes
                checkpoint.write_text(json.dumps(results[month], ensure_ascii=False, indent=2), encoding="utf-8")

        rows = [row for month in DEVELOPMENT_MONTHS for row in results[month]["summary"]]
        development = pd.DataFrame(rows)
        selections = []
        for code in codes:
            scores = development.loc[development.industry_code.eq(code)].pivot(index="method", columns="month", values="mae")
            baseline = scores.loc["reproduced_context"]
            improvements = scores.loc[["nearby_scale", "nearby_industries"]]
            eligible = improvements.lt(baseline - 1e-8, axis=1).all(axis=1)
            method = "reproduced_context"
            if eligible.any():
                method = improvements.loc[eligible].div(baseline).mean(axis=1).idxmin()
            selections.append({
                "industry_code": code,
                "industry_name": development.loc[development.industry_code.eq(code), "industry_name"].iloc[0],
                "selected_method": method,
                "improved_both_development_months": method != "reproduced_context",
                **{
                    f"{month}_{label}_mae": scores.loc[score_method, month]
                    for month in DEVELOPMENT_MONTHS
                    for label, score_method in (("original", "reproduced_context"), ("selected", method))
                },
            })
        selected = pd.DataFrame(selections)
        selected.to_csv(OUTPUT / "expanded_nearby_selection.csv", index=False, encoding="utf-8-sig")
        print(f"Frozen choices: {(selected.selected_method != 'reproduced_context').sum()}/83 improved", flush=True)

        details, summary, audit = evaluate_month(CONFIRMATION_MONTH, codes=codes)
        details.to_csv(OUTPUT / f"industry_comparison_{CONFIRMATION_MONTH}.csv", index_label="admin_code", encoding="utf-8-sig")
        manifest_path = OUTPUT / "industry_inputs.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["inputs"][CONFIRMATION_MONTH] = audit
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        checkpoint = OUTPUT / f"expanded_nearby_{CONFIRMATION_MONTH}.json"
        cached = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else {}
        if (cached.get("algorithm_sha256"), cached.get("population_sha256"), cached.get("industry_codes")) == (algorithm_hash, population_hash, codes):
            results[CONFIRMATION_MONTH] = cached
            verify_snapshot_hash(
                OUTPUT.parent / "a08/daegu_stores_202606.csv", cached["source_sha256"]
            )
        else:
            results[CONFIRMATION_MONTH] = evaluate(
                CONFIRMATION_MONTH, codes=codes, prefix="expanded_nearby", full_fit=False
            )
            results[CONFIRMATION_MONTH]["algorithm_sha256"] = algorithm_hash
            results[CONFIRMATION_MONTH]["population_sha256"] = population_hash
            results[CONFIRMATION_MONTH]["industry_codes"] = codes
            checkpoint.write_text(json.dumps(results[CONFIRMATION_MONTH], ensure_ascii=False, indent=2), encoding="utf-8")

    confirmation = pd.DataFrame(results[CONFIRMATION_MONTH]["summary"])
    for index, row in selected.iterrows():
        group = confirmation.loc[confirmation.industry_code.eq(row.industry_code)].set_index("method")
        old = group.loc["reproduced_context", "mae"]
        new = group.loc[row.selected_method, "mae"]
        selected.loc[index, "confirmation_old_mae"] = old
        selected.loc[index, "confirmation_selected_mae"] = new
        selected.loc[index, "confirmed_improvement"] = bool(new < old - 1e-8)
        selected.loc[index, "confirmation_worse"] = bool(new > old + 1e-8)
    selected.to_csv(OUTPUT / "expanded_nearby_selection.csv", index=False, encoding="utf-8-sig")
    all_scores = pd.DataFrame([row for month in results for row in results[month]["summary"]])
    all_scores.to_csv(OUTPUT / "expanded_nearby_scores.csv", index=False, encoding="utf-8-sig")
    print(selected.groupby(["selected_method", "confirmed_improvement"]).size().to_string(), flush=True)
    print(f"Confirmed improvement: {selected.confirmed_improvement.sum()}/83", flush=True)
    if not np.isfinite(selected[["confirmation_old_mae", "confirmation_selected_mae"]]).all().all():
        raise ValueError("Non-finite selection scores")
    selected.to_csv(
        OUTPUT.parents[2] / "docs/a10/expanded_industry_validation.csv",
        index=False, encoding="utf-8", lineterminator="\n",
    )


if __name__ == "__main__":
    main()
