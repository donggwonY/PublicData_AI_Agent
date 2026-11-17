"""Prepare the A-07 monthly population panel from locally collected MOIS extracts."""

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "data/raw/a07_population"
AREA = re.compile(r"(.+?)\s*\((27\d{8})\)\s*$")
MONTH = re.compile(r"(\d{4})년(\d{2})월_거주자_0~9세")
# District-wide screening for notices that may affect continuing codes.
DISTRICT_CHANGES = {
    "27710": ("2018-03", "2018-11", "2026-09"),
    "27140": ("2020-07",),
    "27290": ("2021-11",),
    "27720": ("2023-07",),
}


def shift_month(month, offset):
    year, number = map(int, month.split("-"))
    year, month_index = divmod(year * 12 + number - 1 + offset, 12)
    return f"{year:04d}-{month_index + 1:02d}"


def load_months():
    months = {}
    sources = json.loads((ROOT / "monthly_sources.json").read_text(encoding="utf-8"))
    for source in sources:
        path = ROOT / source["file"]
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader)
            columns = {}
            for index in range(2, len(header), 2):
                match = MONTH.fullmatch(header[index])
                if not match or not header[index - 1].endswith("_연령구간인구수"):
                    raise ValueError(f"Unexpected county/age column in {path.name}")
                month = "-".join(match.groups())
                if month in months:
                    raise ValueError(f"Duplicate month {month}")
                columns[index] = month
                months[month] = {}
            for row in reader:
                name, code = AREA.fullmatch(row[0]).groups()
                for index, month in columns.items():
                    value = row[index].strip()
                    if value != row[index - 1].strip() or code in months[month]:
                        raise ValueError(f"Inconsistent or duplicate record {month} {code}")
                    if value:
                        count = int(value.replace(",", ""))
                        if count < 0:
                            raise ValueError(f"Negative population {month} {code}")
                        months[month][code] = (name, count)
    expected = {shift_month("2016-01", index) for index in range(130)}
    if months.keys() != expected:
        raise ValueError("The input does not cover all expected months")
    for month, counts in months.items():
        local = {code: value for code, value in counts.items() if not code.endswith("00000")}
        if sum(count for _, count in local.values()) != counts["2700000000"][1]:
            raise ValueError(f"City total mismatch in {month}")
        months[month] = local
    return months


def build_panel(months):
    changes = defaultdict(set, {key: set(value) for key, value in DISTRICT_CHANGES.items()})
    for month, current in sorted(months.items()):
        previous = months.get(shift_month(month, -1))
        if previous is not None:
            for code in current.keys() ^ previous.keys():
                changes[code[:5]].add(month)
    for month, current in sorted(months.items()):
        target_month = shift_month(month, 12)
        for code, (name, count) in sorted(current.items()):
            history_months = [shift_month(month, offset) for offset in range(-12, 1)]
            future_months = [shift_month(month, offset) for offset in range(1, 13)]
            history = [months.get(key, {}).get(code) for key in history_months]
            future = [months.get(key, {}).get(code) for key in future_months]
            district_changes = changes[code[:5]]
            if target_month not in months:
                status = "awaiting_observation"
            elif any(key in district_changes for key in future_months):
                status = "district_change"
            elif any(record is None or record[0] != name for record in future):
                status = "code_or_name_discontinuity"
            else:
                status = "matched"
            history_ok = all(record is not None and record[0] == name for record in history)
            history_ok = history_ok and not district_changes.intersection(history_months[1:])
            target = future[-1][1] if status == "matched" else None
            yield {
                "admin_code": code,
                "admin_area": name,
                "base_month": month,
                "population_0_9": count,
                "target_month": target_month,
                "population_0_9_after_12m": target,
                "change_after_12m": None if target is None else target - count,
                "target_status": status,
                "history_12m_usable": int(history_ok),
                "usable_for_baseline_comparison": int(history_ok and status == "matched"),
            }


if __name__ == "__main__":
    panel = list(build_panel(load_months()))
    with (ROOT / "monthly_panel.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(panel[0]))
        writer.writeheader()
        writer.writerows(panel)
    print("rows:", len(panel), "target status:", dict(Counter(row["target_status"] for row in panel)))
    print("usable rows:", sum(row["usable_for_baseline_comparison"] for row in panel))
