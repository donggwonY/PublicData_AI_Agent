"""Build the two-area A-10 preview using the reviewed industry estimates."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from export_a10_app_comparison import MONTH, ROOT
from evaluate_a10_cafe_concentration import POPULATION, load_inputs
from snapshot_hashes import verify_snapshot_hash


DOCS = ROOT / "docs/a10"


def build_preview():
    estimates = pd.read_csv(DOCS / "industry_comparison_app_83.csv", dtype={"admin_code": str})
    methods = pd.read_csv(DOCS / "expanded_industry_validation.csv")
    source, stores, population = load_inputs(MONTH)
    manifest = json.loads((ROOT / "data/raw/a10/industry_inputs.json").read_text(encoding="utf-8"))
    verify_snapshot_hash(source, manifest["inputs"][MONTH]["source_sha256"])
    verify_snapshot_hash(POPULATION, manifest["population_sha256"])
    population = population.set_index("admin_code")
    totals = stores.groupby("admin_code").size().rename("total_shops")
    areas = sorted(estimates.admin_code.unique())
    profiles = population.loc[areas].join(totals).fillna({"total_shops": 0})
    profiles["total_shops"] = profiles.total_shops.astype(int)
    ages = list(profiles.filter(regex="^age_").columns)
    if profiles.total.le(0).any() or profiles[["total_shops", *ages]].isna().any().any():
        raise ValueError("Incomplete comparison-area profiles")
    np.testing.assert_array_equal(profiles[ages].sum(axis=1), profiles.total)
    if len(estimates) != 12616 or estimates.duplicated(["admin_code", "industry_code"]).any():
        raise ValueError("Incomplete or duplicated industry-area estimates")
    if set(estimates.industry_code) != set(methods.industry_code):
        raise ValueError("Industry lookup mismatch")
    if estimates.actual_shops.gt(estimates.admin_code.map(profiles.total_shops)).any():
        raise ValueError("Industry count exceeds the total shop count")
    profiles[["month", "admin_area", "total", "total_shops", *ages]].to_csv(
        DOCS / f"area_profiles_{MONTH}.csv", index_label="admin_code",
        encoding="utf-8", lineterminator="\n"
    )
    payload = {
        "month": MONTH,
        "areas": {
            code: {
                "name": row.admin_area.removeprefix("대구광역시 "),
                "residents": int(row.total),
                "shops": int(row.total_shops),
                "ages": {age: int(row[age]) for age in ages},
            }
            for code, row in profiles.iterrows()
        },
        "industries": {
            row.industry_code: {
                "name": row.industry_name,
                "uses_nearby": row.active_method != "poisson_context",
                "counts": {
                    item.admin_code: [int(item.actual_shops), float(item.estimated_shops)]
                    for _, item in estimates.loc[estimates.industry_code.eq(row.industry_code)].iterrows()
                },
            }
            for _, row in methods.iterrows()
        },
    }
    template = Path(__file__).with_name("a10_area_comparison_template.html").read_text(encoding="utf-8")
    if template.count("__A10_DATA__") != 1:
        raise ValueError("Expected one data placeholder")
    content = template.replace("__A10_DATA__", json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c"))
    (DOCS / "cafe_comparison_preview.html").write_text(content, encoding="utf-8", newline="\n")
    print(f"Built comparison for {len(areas)} areas and {len(methods)} industries")


if __name__ == "__main__":
    build_preview()
