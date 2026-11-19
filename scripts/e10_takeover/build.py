"""E-10 1단계: 같은 업종 이어받기 사례 표와 변수 (계획 docs/e10/plan.md §1~2).

입력(저장소 밖, 읽기만):
  C:/claude_workspace/e05_data/serve/asof_episodes_2026.parquet  E-03 사례 표(2012~2026 폐업)
  C:/claude_workspace/e05_data/input/{stores,units,legal_admin_map}.parquet, meta.json  E-05 고정 빌드
  C:/claude_workspace/e05_data/aux/{subway,station,population}  지하철·인구
출력: C:/claude_workspace/e10_data/cases.parquet, cases_meta.json(저장소 밖), 요약 docs/e10/results/build.json
실행(저장소 루트): C:/claude_workspace/e06_env/Scripts/python scripts/e10_takeover/build.py

예측 시점 = 이어받은 가게의 인허가일(개업일) o.
  - 자리 이력: E-05 history_features 를 t0 = o − 1일로 다시 계산(이어받은 가게 자신은 ld = o > t0 라 빠진다).
  - 주변·동·지하철·인구: E-05 함수로 at = o(직전 달 말 상태)로 다시 계산. 이어받은 가게는 개업 달 이후에만 반영된다.
  - 두 조건을 코드에서 확인(assert)한다.
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/e05_vacancy"))
import asof as A  # noqa: E402
import ext as E  # noqa: E402

E05 = Path("C:/claude_workspace/e05_data")
EPIS = E05 / "serve/asof_episodes_2026.parquet"
EPIS_SHA = "e3700bbe52b1c975916d24de2dba00c71abf6cfe67fee55e21f30ddfaed25558"
AUX = E05 / "aux"
OUT = Path("C:/claude_workspace/e10_data")
HORIZON = 1095
GAP_MIN, GAP_MAX = -A.TOL, 90
TENURE_BINS = [-np.inf, 1, 3, 10, np.inf]
TENURE_LABELS = ["≤1년", "1~3년", "3~10년", ">10년"]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def split_of(year):
    return np.select([year <= 2018, year <= 2020], ["train", "valid"], "test")


def main():
    if sha(EPIS) != EPIS_SHA:
        raise SystemExit("E-03 사례 표 해시가 다릅니다.")
    ep = pd.read_parquet(EPIS)
    ep = ep[~ep.censor_bulk_registration]
    meta_in = json.loads((E05 / "input/meta.json").read_text(encoding="utf-8"))
    ref = pd.Timestamp(meta_in["reference_date"])
    stores = pd.read_parquet(E05 / "input/stores.parquet")
    units = pd.read_parquet(E05 / "input/units.parquet", columns=["uid", "lat", "lon"])
    occ = A.load_occupants(stores, units)
    oi = occ.set_index("occupant_id")

    # ── 사례: 같은 인허가 업종이 폐업 −60~+90일 안에 이어받음, 3년 관측 가능 ──
    d = ep[ep.event & (ep.next_service == ep.service) & ep.gap.between(GAP_MIN, GAP_MAX)].copy()
    n_all_takeover = len(d)
    d = d[d.next_ld <= ref - pd.Timedelta(days=HORIZON)].copy()
    assert d.next_occupant.is_unique
    s = oi.loc[d.next_occupant]
    d["s_occupant_id"] = d.next_occupant.to_numpy()
    d["s_ld"] = d.next_ld
    d["s_category"] = s.category.to_numpy()
    d["s_area_m2"] = s.area_m2.where(s.area_m2 > 0).to_numpy()
    d["s_floor_class"] = s.floor.map(A.floor_class).to_numpy()
    s_cd, s_closed = s.cd.to_numpy(), s.closed.to_numpy()
    d["s_life_days"] = (pd.Series(np.where(s_closed, s_cd, ref.to_datetime64()), index=d.index) - d.next_ld).dt.days
    d["y"] = (s_closed & (d.s_life_days <= HORIZON)).astype(int)
    assert (d.uid.to_numpy() == s.uid.to_numpy()).all()

    d["open_year"] = d.next_ld.dt.year
    d["split"] = split_of(d.open_year)
    d["open_month"] = d.next_ld.dt.month
    d["covid_open"] = d.next_ld.between(pd.Timestamp("2020-03-01"), pd.Timestamp("2022-04-30")).astype(int)

    # ── 직전 가게 ──
    end = d[["t0", "next_ld"]].min(axis=1)
    d["p_tenure_years"] = (end - d.ld).dt.days / 365.25
    d["p_tenure_band"] = pd.cut(d.p_tenure_years, TENURE_BINS, labels=TENURE_LABELS, right=True).astype(str)
    d["p_category"] = d.category
    d["same_category"] = (d.category == d.s_category).astype(int)
    d["p_area_m2"] = d.area_m2.where(d.area_m2 > 0)
    d["p_n_licenses"] = d.n_licenses
    d["gap_days"] = d.gap
    d["overlap"] = (d.gap <= 0).astype(int)
    d["area_ratio"] = d.s_area_m2 / d.p_area_m2

    # 폐업일 기준 변수(E-03)는 버리고 개업일 기준으로 다시 계산
    old = [c for c in d.columns if c.startswith(("s1_", "s2_", "h_"))] + [
        "prev_group", "prev_life_years", "prev_area_m2", "prev_n_licenses", "close_month", "covid"]
    d = d.drop(columns=old).reset_index(drop=True)

    # ── 자리 이력: t0 = 개업일 − 1일 ──
    hx = d[["uid", "ld"]].assign(t0=d.next_ld - A.DAY)
    assert (d.next_ld > hx.t0).all()
    # 이어받은 가게가 이력 집계 대상(ld ≤ t0)에 들어가지 않는지 직접 확인
    s_ld = oi.loc[d.s_occupant_id, "ld"].to_numpy()
    assert (s_ld > hx.t0.to_numpy()).all()
    H = A.history_features(hx, occ)

    # ── 주변·동·지하철·인구: at = 개업일(직전 달 말 상태) ──
    P = A.Panels(occ, ref)
    at = d.next_ld
    m = (A.month_idx(at) - 1).clip(lower=0, upper=P.M - 1).to_numpy()
    assert (A.month_idx(d.next_ld).to_numpy() > m).all()      # 이어받은 가게는 조회 달 뒤에 개업
    sub = E.load_subway(str(AUX / "subway/subway_monthly.csv"), str(AUX / "station/daegu_station_location.xlsx"))
    pop = E.load_population(str(AUX / "population"))
    lmap = pd.read_parquet(E05 / "input/legal_admin_map.parquet")
    feats = [H, A.neighbor_features(d, P, at, "o_"), A.dong_features(d, P, occ, at, "o_"),
             E.subway_features(d, sub, at, "o_"), E.population_features(d, pop, lmap, at, "o_")]
    d = pd.concat([d] + feats, axis=1)

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "cases.parquet"
    d.to_parquet(path, index=False)

    def tab(g):
        return {"n": int(len(g)), "pos": int(g.y.sum()), "rate": round(float(g.y.mean()), 3), "uids": int(g.uid.nunique())}

    order = ["train", "valid", "test"]
    top = ["일반음식점", "담배소매업", "휴게음식점", "미용업", "즉석판매제조가공업"]
    svc = d.service.where(d.service.isin(top), "그 밖")
    feat_cols = ["s_category", "s_area_m2", "s_floor_class", "p_tenure_years", "p_area_m2", "area_ratio",
                 "gap_days"] + [c for f in feats for c in f.columns]
    meta = {
        "rows": len(d), "sha256": sha(path), "input_episodes_sha256": EPIS_SHA,
        "input_stores_sha256": sha(E05 / "input/stores.parquet"), "input_units_sha256": sha(E05 / "input/units.parquet"),
        "input_lmap_sha256": sha(E05 / "input/legal_admin_map.parquet"), "reference_date": str(ref.date()),
        "takeovers_all_years": n_all_takeover, "open_year_range": [int(d.open_year.min()), int(d.open_year.max())],
        "by_split": {k: tab(d[d.split == k]) for k in order},
        "by_split_service": {k: {sv: [int(len(g)), round(float(g.y.mean()), 3)] for sv, g in d[d.split == k].groupby(svc)}
                             for k in order},
        "by_split_tenure_band": {k: {b: [int(len(g)), round(float(g.y.mean()), 3)]
                                     for b, g in d[d.split == k].groupby("p_tenure_band")} for k in order},
        "overlap_n": int(d.overlap.sum()), "same_category_share": round(float(d.same_category.mean()), 3),
        "missing_rate": {c: round(float(d[c].isna().mean()), 4) for c in feat_cols},
        "asserts": ["successor unique", "successor uid = predecessor uid", "successor ld > history t0",
                    "successor open month > lookup month"],
    }
    for p in (OUT / "cases_meta.json", ROOT / "docs/e10/results/build.json"):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=int), encoding="utf-8")
    print(json.dumps({k: meta[k] for k in ("rows", "takeovers_all_years", "open_year_range", "by_split", "overlap_n",
                                           "same_category_share")}, ensure_ascii=False))
    print(json.dumps(meta["by_split_service"], ensure_ascii=False))
    print(json.dumps(meta["by_split_tenure_band"], ensure_ascii=False))
    mr = pd.Series(meta["missing_rate"])
    print(mr[mr > 0].to_string())


if __name__ == "__main__":
    main()
