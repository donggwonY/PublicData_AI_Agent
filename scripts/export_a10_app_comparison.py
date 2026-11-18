"""Export the four A-10 preview industries for app lookup."""

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MONTH = "2026-09"
INDUSTRIES = {"I21201", "S20701", "I20101", "P10501"}
FIELDS = ("admin_code", "industry_code", "base_month", "actual_shops", "estimated_shops")


def main():
    source = ROOT / f"data/raw/a10/industry_comparison_{MONTH}.csv"
    target = ROOT / "docs/a10/industry_comparison_app.csv"
    with source.open(encoding="utf-8-sig", newline="") as file:
        rows = [
            {
                "admin_code": row["admin_code"],
                "industry_code": row["industry_code"],
                "base_month": MONTH,
                "actual_shops": row["actual_shops"],
                "estimated_shops": row["poisson_context"],
            }
            for row in csv.DictReader(file)
            if row["industry_code"] in INDUSTRIES
        ]
    areas = {row["admin_code"] for row in rows}
    keys = {(row["admin_code"], row["industry_code"]) for row in rows}
    if not rows or len(rows) != len(keys) or keys != {(area, code) for area in areas for code in INDUSTRIES}:
        raise ValueError("Expected one result per area and preview industry")
    with target.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: (row["admin_code"], row["industry_code"])))
    print(f"Exported {len(rows)} rows from {len(areas)} areas")


if __name__ == "__main__":
    main()
