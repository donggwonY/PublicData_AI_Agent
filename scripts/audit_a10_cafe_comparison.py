"""Summarize held-out A-10 café count estimates by district, size and month."""

import csv
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[1] / "data" / "raw" / "a10"
MONTHS = ("2025-06", "2026-09")


def load_month(month):
    with (ROOT / f"cafe_comparison_{month}.csv").open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    keyed = {row["admin_code"]: row for row in rows}
    if len(keyed) != len(rows):
        raise ValueError(f"Duplicate administrative code in {month}")
    return keyed


def gap(row, estimate="poisson_context"):
    return int(row["cafes"]) - float(row[estimate])


def summarize(label, rows):
    rows = list(rows)
    if not rows:
        return
    baseline = mean(abs(gap(row, "other_shop_rate")) for row in rows)
    model = mean(abs(gap(row)) for row in rows)
    bias = mean(gap(row) for row in rows)
    print(f"| {label} | {len(rows)} | {baseline:.2f} | {model:.2f} | {bias:+.2f} |")


def print_month(month, data):
    rows = list(data.values())
    print(f"\n{month}")
    summarize("전체", rows)
    districts = sorted({row["admin_area"].split()[1] for row in rows})
    for district in districts:
        summarize(district, (row for row in rows if row["admin_area"].split()[1] == district))
    for lower, upper in ((0, 500), (500, 1500), (1500, float("inf"))):
        summarize(
            f"{lower} 이상 {upper} 미만",
            (row for row in rows if lower <= int(row["other_shops"]) < upper),
        )


def main():
    older, newer = (load_month(month) for month in MONTHS)
    for month, data in zip(MONTHS, (older, newer)):
        print_month(month, data)
    codes = sorted(
        code for code in older.keys() & newer.keys()
        if older[code]["admin_area"] == newer[code]["admin_area"]
    )
    mismatches_old = sorted(set(older) - set(codes))
    mismatches_new = sorted(set(newer) - set(codes))
    print(f"Excluded older: {mismatches_old}. Excluded newer: {mismatches_new}.")
    for minimum in (0, 10):
        pairs = [(gap(older[code]), gap(newer[code])) for code in codes]
        pairs = [(a, b) for a, b in pairs if min(abs(a), abs(b)) >= minimum]
        same = sum((a > 0) == (b > 0) for a, b in pairs if a != 0 and b != 0)
        ties = sum(a == 0 or b == 0 for a, b in pairs)
        print(f"Minimum gap {minimum}: {same} same, {len(pairs) - same - ties} flipped, {ties} tied.")


if __name__ == "__main__":
    main()
