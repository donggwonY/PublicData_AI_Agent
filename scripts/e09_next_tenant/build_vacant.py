"""E-09 2차 1단계: 이미 빈 자리 기준(랜드마크) 사례 표와 변수 (계획 docs/e09/plan_vacant.md §1~2).

입력(저장소 밖, 읽기만): E-05 사례 표 v2, 고정 빌드(stores·units·meta·legal_admin_map), 보조 자료(지하철·역 좌표·인구)
출력(저장소 밖): C:/claude_workspace/e09_data/vacant_cases.parquet, vacant_cases_meta.json
실행(저장소 루트): C:/claude_workspace/e06_env/Scripts/python scripts/e09_next_tenant/build_vacant.py

랜드마크 L(폐업 후 90·180·365·730·1,095일)에 아직 빈 사례만 쓴다. 주변·동·지하철·인구와 추가 변수는
예측 시점 = 폐업일 + L 이 속한 달의 직전 달 말 상태로 E-05 함수로 다시 계산한다(접두 s1_ 를 그대로 써 1차 모델 코드와 열 이름을 맞춤).
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
AUX = E05 / "aux"
EPIS = E05 / "e05_ref/asof_episodes.parquet"
EPIS_SHA = "caede0042c6c82bb122cfa3c85011242833472451604dce5bb25486ea191e12b"
OUT = Path("C:/claude_workspace/e09_data")
LANDMARKS = (90, 180, 365, 730, 1095)
WINDOW = 730
LAST_LANDMARK = pd.Timestamp("2023-12-31")
MAIN = ["음식점", "카페·제과", "미용·이용", "식품판매", "담배", "오락"]
CLASSES = MAIN + ["기타"]
KEYS = [c.replace("·", "_") for c in CLASSES]
G7 = np.array([CLASSES.index(g) if g in MAIN else CLASSES.index("기타") for g in A.GROUPS])


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def to7(g):
    return g if g in MAIN else "기타"


def collapse(a11):
    out = np.zeros(a11.shape[:-1] + (7,), dtype=float)
    for j in range(11):
        out[..., G7[j]] += a11[..., j]
    return out


def landmark_rows(ep):
    parts = []
    for L in LANDMARKS:
        lm = ep.t0 + pd.Timedelta(days=L)
        vac = (~ep.event | (ep.gap > L)) & (ep["T"] > L)
        tgt = vac & (lm <= LAST_LANDMARK) & ep.event & (ep.gap <= L + WINDOW)
        r = ep[tgt].copy()
        r["L"] = L
        r["at"] = lm[tgt]
        parts.append(r)
    d = pd.concat(parts, ignore_index=True)
    d["lm_year"] = d["at"].dt.year
    d["split"] = np.select([d.lm_year <= 2019, d.lm_year <= 2021], ["train", "valid"], "test")
    d["y"] = d.next_service.map(A.GROUP).map(to7)
    d["prev7"] = d.group.map(to7)
    d["vacant_days"] = d["L"]
    return d


def added_features(d, P, occ):
    m_lm = (A.month_idx(d["at"]) - 1).clip(lower=0, upper=P.M - 1).to_numpy()
    m_t0 = (A.month_idx(d["t0"]) - 1).clip(lower=0, upper=P.M - 1).to_numpy()
    assert (A.month_idx(d.next_ld).to_numpy() > m_lm).all(), "다음 가게가 조회 달 안에 있음"
    act7, op7, since7, dact = [], [], [], []
    for oid, mm, m0 in zip(d.occupant_id, m_lm, m_t0):
        ci = P.occ_cell.get(oid)
        if ci is None:
            nan7 = np.full(7, np.nan)
            act7.append(nan7); op7.append(nan7); since7.append(nan7); dact.append(np.nan); continue
        nb = P.neigh(ci)
        act = (P.cum_open[nb, mm, :].sum(0) - P.cum_close[nb, mm, :].sum(0)).astype(float)
        act0 = (P.cum_open[nb, m0, :].sum(0) - P.cum_close[nb, m0, :].sum(0)).astype(float)
        op12 = (P.cum_open[nb, mm, :] - P.cum_open[nb, max(mm - 12, 0), :]).sum(0).astype(float)
        since = (P.cum_open[nb, mm, :] - P.cum_open[nb, m0, :]).sum(0).astype(float)
        act7.append(collapse(act)); op7.append(collapse(op12)); since7.append(collapse(since)); dact.append(act.sum() - act0.sum())
    act7, op7, since7 = np.array(act7), np.array(op7), np.array(since7)
    f = pd.DataFrame(index=d.index)
    with np.errstate(invalid="ignore", divide="ignore"):
        sa, so, ss = (x / x.sum(1, keepdims=True) for x in (act7, op7, since7))
    for k, c in enumerate(KEYS):
        f[f"nb_act_share_{c}"] = sa[:, k]
        f[f"nb_open12_share_{c}"] = so[:, k]
        f[f"since_close_open_share_{c}"] = ss[:, k]
    f["nb_open12_total"] = op7.sum(1)
    f["since_close_open_total"] = since7.sum(1)
    f["nb_active_change_since_close"] = dact
    # 대구 전체 최근 36개월 '이전에 가게가 있던 자리' 개업 묶음 비중(조회 달까지)
    o = occ.sort_values(["uid", "ld", "occupant_id"])
    re = o[o.groupby("uid").cumcount() > 0]
    rm = A.month_idx(re.ld).clip(lower=0, upper=P.M - 1).to_numpy()
    cnt = np.zeros((P.M, 7))
    np.add.at(cnt, (rm, re.group.map(to7).map(CLASSES.index).to_numpy()), 1)
    cum = cnt.cumsum(0)
    win = cum[m_lm] - cum[np.maximum(m_lm - 36, 0)]
    tr = win / win.sum(1, keepdims=True)
    for k, c in enumerate(KEYS):
        f[f"city_reopen36_share_{c}"] = tr[:, k]
    return f


def main():
    if sha(EPIS) != EPIS_SHA:
        raise SystemExit("E-05 사례 표 해시가 다릅니다.")
    ep = pd.read_parquet(EPIS)
    ep = ep[~ep.censor_bulk_registration].reset_index(drop=True)
    d = landmark_rows(ep)
    d = d.drop(columns=[c for c in d.columns if c.startswith(("s1_", "s2_"))])

    meta_in = json.loads((E05 / "input/meta.json").read_text(encoding="utf-8"))
    ref = pd.Timestamp(meta_in["reference_date"])
    stores = pd.read_parquet(E05 / "input/stores.parquet")
    units = pd.read_parquet(E05 / "input/units.parquet", columns=["uid", "lat", "lon"])
    occ = A.load_occupants(stores, units)
    P = A.Panels(occ, ref)
    sub = E.load_subway(str(AUX / "subway/subway_monthly.csv"), str(AUX / "station/daegu_station_location.xlsx"))
    pop = E.load_population(str(AUX / "population"))
    lmap = pd.read_parquet(E05 / "input/legal_admin_map.parquet")
    at = d["at"]
    feats = [A.neighbor_features(d, P, at, "s1_"), A.dong_features(d, P, occ, at, "s1_"),
             E.subway_features(d, sub, at, "s1_"), E.population_features(d, pop, lmap, at, "s1_"),
             added_features(d, P, occ)]
    d = pd.concat([d] + feats, axis=1)

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "vacant_cases.parquet"
    d.to_parquet(path, index=False)
    feat_cols = [c for f in feats for c in f.columns]
    meta = {
        "rows": len(d), "sha256": sha(path), "input_episodes_sha256": EPIS_SHA,
        "input_stores_sha256": sha(E05 / "input/stores.parquet"), "input_units_sha256": sha(E05 / "input/units.parquet"),
        "input_lmap_sha256": sha(E05 / "input/legal_admin_map.parquet"),
        "by_split_landmark": {f"{s}|{L}": int(n) for (s, L), n in d.groupby(["split", "L"]).size().items()},
        "by_split_class": pd.crosstab(d.split, d.y).reindex(columns=CLASSES).to_dict(orient="index"),
        "uids": int(d.uid.nunique()),
        "missing_rate": {c: round(float(d[c].isna().mean()), 4) for c in feat_cols},
    }
    (OUT / "vacant_cases_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=int), encoding="utf-8")
    print(len(d), "uids", meta["uids"])
    print(pd.crosstab(d.split, d.L, margins=True).to_string())
    print(pd.crosstab(d.split, d.y).reindex(columns=CLASSES).to_string())
    mr = pd.Series(meta["missing_rate"])
    print(mr[mr > 0].to_string())


if __name__ == "__main__":
    main()
