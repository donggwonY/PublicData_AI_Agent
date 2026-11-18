"""동네·자리 화면용 표 2개: A-07 1년 뒤 거주 인구, A-09 비슷한 동네 5곳 (2026-11-18).

입력(저장소 문서, 바꾸지 않는다):
  docs/a07/population_forecast_2027-10_cohort.csv  (A-07 C안 연령대별 예측표, cohort_results_c.md)
  docs/a09/similar_areas.json                      (A-09 추천 결과, 김선경)
출력(앱은 읽기만): service/data/processed/population_forecast.parquet, similar_areas.parquet
연결 키: 행정기관코드. 앱의 동네 프로필(area_context)은 코드가 없어 구·행정동 이름으로 잇는다.
  달성군 구지읍(A-07·A-09)은 프로필에 옛 이름 구지면으로 있어 그 하나만 따로 짝짓는다.
실행(저장소 루트): service/.venv/Scripts/python scripts/area_outlook_export.py
"""
import csv
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "service/data/processed"
A07 = ROOT / "docs/a07/population_forecast_2027-10_cohort.csv"
A09 = ROOT / "docs/a09/similar_areas.json"
A07_SHA = "6bb99bca26d24161e562cdc199200ab11eb02ac398ee35cf48663dbe2b5d125e"  # cohort_results_c.md 기록값
ALIAS = {("달성군", "구지읍"): ("달성군", "구지면")}  # 원자료 이름 → 동네 프로필 이름
BANDS = ["total", "age_00_09", "age_10_19", "age_20_29", "age_30_39", "age_40_49", "age_50_59",
         "age_60_69", "age_70_79", "age_80_89", "age_90_99", "age_100_plus"]


def ctx_name(gu, dong):
    return ALIAS.get((gu, dong), (gu, dong))


def population(ctx_keys):
    if hashlib.sha256(A07.read_bytes()).hexdigest() != A07_SHA:
        raise ValueError("A-07 예측표가 기록된 SHA-256 과 다르다")
    rows = list(csv.DictReader(A07.open(encoding="utf-8-sig")))
    num = lambda v: float(v) if v != "" else float("nan")  # noqa: E731
    out = []
    for r in rows:
        _, gu, dong = r["admin_area"].split()
        g, d = ctx_name(gu, dong)
        out.append({"admin_code": r["admin_code"], "gu": g, "admin_dong": d, "source_name": f"{gu} {dong}",
                    "age_band": r["age_band"], "base_month": r["base_month"], "target_month": r["target_month"],
                    "current_population": int(r["current_population"]),
                    "forecast_population": num(r["forecast_population"]),
                    "forecast_change": num(r["forecast_change"]),
                    "recent_change_12m": num(r["recent_change_12m"]),
                    "status": r["status"], "method": r["method"], "change_display": r["change_display"]})
    df = pd.DataFrame(out)
    assert len(df) == 1824 and df.groupby("admin_code").size().eq(12).all()
    assert set(df["age_band"]) == set(BANDS) and (df["status"] == "available").sum() == 1692
    ok = df.dropna(subset=["forecast_population"])
    assert (ok["forecast_population"] - ok["current_population"] == ok["forecast_change"]).all()
    linked = {(g, d) for g, d in zip(df["gu"], df["admin_dong"])} & ctx_keys
    return df, linked


def similar(ctx_keys):
    s = json.loads(A09.read_text(encoding="utf-8"))
    prof, opts = s["profiles"], s["scenarios"]["options"]
    month = max(s["months"])
    lists = {"combined": s["recommendations"], **s["scenarios"]["recommendations"]}
    out = []
    for option, recs in lists.items():
        o = opts.get(option)
        for code, recl in recs.items():
            assert len(recl) == 5 and code not in recl and len(set(recl)) == 5, (option, code)
            g, d = ctx_name(*prof[code]["name"].split(" ", 1))
            for rank, rc in enumerate(recl, 1):
                rg, rd = ctx_name(*prof[rc]["name"].split(" ", 1))
                out.append({"admin_code": code, "gu": g, "admin_dong": d, "option": option, "rank": rank,
                            "rec_code": rc, "rec_gu": rg, "rec_admin_dong": rd,
                            "rec_shops": int(prof[rc]["shops"]), "rec_residents_a09": int(prof[rc]["residents"]),
                            "option_group": o["group"] if o else "", "option_key": o["key"] if o else "",
                            "base_share": prof[code][o["group"]][o["key"]] if o else float("nan"),
                            "rec_share": prof[rc][o["group"]][o["key"]] if o else float("nan"),
                            "base_month": month})
    df = pd.DataFrame(out)
    assert df["option"].nunique() == 23 and df.groupby("option")["admin_code"].nunique().eq(146).all()
    linked = {(g, d) for g, d in zip(df["gu"], df["admin_dong"])} & ctx_keys
    return df, linked


def main():
    ctx = pd.read_parquet(OUT / "area_context.parquet")
    keys = set(zip(ctx["gu"], ctx["admin_dong"]))
    pop, pl = population(keys)
    sim, sl = similar(keys)
    pop.to_parquet(OUT / "population_forecast.parquet", index=False)
    sim.to_parquet(OUT / "similar_areas.parquet", index=False)
    print(f"population_forecast {len(pop):,}행, 프로필과 연결 {len(pl)}/{len(keys)}곳")
    print(f"similar_areas {len(sim):,}행, 기준 동네 {sim['admin_code'].nunique()}곳, 프로필과 연결 {len(sl)}/{len(keys)}곳")
    print("프로필에만 있는 동네(인구):", sorted(keys - pl), "(추천):", sorted(keys - sl))


if __name__ == "__main__":
    main()
