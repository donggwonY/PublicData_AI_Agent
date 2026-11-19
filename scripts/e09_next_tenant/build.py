"""E-09 1단계: 대상 표와 추가 변수 (계획 docs/e09/plan.md §1~2, 변경 기록 2026-11-19).

입력(저장소 밖, 읽기만):
  C:/claude_workspace/e05_data/e05_ref/asof_episodes.parquet  E-05 v2 사례·시점 기준 변수
  C:/claude_workspace/e05_data/input/{stores,units}.parquet, meta.json  E-05 고정 빌드
출력(저장소 밖): C:/claude_workspace/e09_data/cases.parquet, cases_meta.json
실행(저장소 루트): C:/claude_workspace/e06_env/Scripts/python scripts/e09_next_tenant/build.py

추가 변수는 E-05 Panels(월 누적, 폐업 1개월 늦게 반영)를 써서 예측 시점(폐업일 t0)이 속한 달의 직전 달 말 상태로 계산한다.
대상은 다음 가게 인허가가 t0 뒤(0 < 간격 ≤ 730일)인 사례라 다음 가게는 어떤 변수에도 들어가지 않는다(코드에서 확인).
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

E05 = Path("C:/claude_workspace/e05_data")
EPIS = E05 / "e05_ref/asof_episodes.parquet"
EPIS_SHA = "caede0042c6c82bb122cfa3c85011242833472451604dce5bb25486ea191e12b"
OUT = Path("C:/claude_workspace/e09_data")
MAIN = ["음식점", "카페·제과", "미용·이용", "식품판매", "담배", "오락"]
CLASSES = MAIN + ["기타"]
G7 = np.array([CLASSES.index(g) if g in MAIN else CLASSES.index("기타") for g in A.GROUPS])  # 11 → 7
WINDOW = 730


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def to7(g):
    return g if g in MAIN else "기타"


def collapse(arr11):
    """(..., 11) → (..., 7)"""
    out = np.zeros(arr11.shape[:-1] + (7,), dtype=float)
    for j in range(11):
        out[..., G7[j]] += arr11[..., j]
    return out


def main():
    if sha(EPIS) != EPIS_SHA:
        raise SystemExit("E-05 사례 표 해시가 다릅니다.")
    ep = pd.read_parquet(EPIS)
    ep["next_group"] = ep.next_service.map(A.GROUP)
    d = ep[ep.event & (ep.gap > 0) & (ep.gap <= WINDOW) & ~ep.censor_bulk_registration].copy()
    excluded_pre = int((ep.event & (ep.gap <= 0) & (ep.gap >= -A.TOL)).sum())
    assert (d.next_ld > d.t0).all()
    d["y"] = d.next_group.map(to7)
    d["prev7"] = d.group.map(to7)

    meta_in = json.loads((E05 / "input/meta.json").read_text(encoding="utf-8"))
    ref = pd.Timestamp(meta_in["reference_date"])
    stores = pd.read_parquet(E05 / "input/stores.parquet")
    units = pd.read_parquet(E05 / "input/units.parquet", columns=["uid", "lat", "lon"])
    occ = A.load_occupants(stores, units)
    P = A.Panels(occ, ref)

    m = (A.month_idx(d.t0) - 1).clip(lower=0, upper=P.M - 1).to_numpy()
    # 다음 가게가 조회 달까지 개업하지 않았는지 확인(대상 정의상 불가능해야 함)
    assert (A.month_idx(d.next_ld).to_numpy() > m).all()
    act7, op7 = [], []
    for oid, mm in zip(d.occupant_id, m):
        ci = P.occ_cell.get(oid)
        if ci is None:
            act7.append(np.full(7, np.nan)); op7.append(np.full(7, np.nan)); continue
        nb = P.neigh(ci)
        act = P.cum_open[nb, mm, :].sum(0) - P.cum_close[nb, mm, :].sum(0)
        op12 = (P.cum_open[nb, mm, :] - P.cum_open[nb, max(mm - 12, 0), :]).sum(0)
        act7.append(collapse(act.astype(float))); op7.append(collapse(op12.astype(float)))
    act7, op7 = np.array(act7), np.array(op7)
    keys = [c.replace("·", "_") for c in CLASSES]
    with np.errstate(invalid="ignore", divide="ignore"):
        sa = act7 / act7.sum(1, keepdims=True)
        so = op7 / op7.sum(1, keepdims=True)
    for k, c in enumerate(keys):
        d[f"nb_act_share_{c}"] = sa[:, k]
        d[f"nb_open12_share_{c}"] = so[:, k]
    d["nb_open12_total"] = op7.sum(1)

    # 대구 전체 최근 3년 '이전에 가게가 있던 자리'에 들어온 개업의 묶음 비중(월 누적, 조회 달까지)
    o = occ.sort_values(["uid", "ld", "occupant_id"])
    had_prev = o.groupby("uid").cumcount() > 0
    re = o[had_prev]
    rm = A.month_idx(re.ld).clip(lower=0, upper=P.M - 1).to_numpy()
    cnt = np.zeros((P.M, 7))
    np.add.at(cnt, (rm, re.group.map(to7).map(CLASSES.index).to_numpy()), 1)
    cum = cnt.cumsum(0)
    win = cum[m] - cum[np.maximum(m - 36, 0)]
    trend = win / win.sum(1, keepdims=True)
    for k, c in enumerate(keys):
        d[f"city_reopen36_share_{c}"] = trend[:, k]

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "cases.parquet"
    d.to_parquet(path, index=False)
    new = [c for c in d.columns if c.startswith(("nb_act_share_", "nb_open12_", "city_reopen36_"))]
    by = pd.crosstab(d.split, d.y).reindex(columns=CLASSES)
    meta = {
        "rows": len(d), "sha256": sha(path), "input_episodes_sha256": EPIS_SHA,
        "input_stores_sha256": sha(E05 / "input/stores.parquet"), "input_units_sha256": sha(E05 / "input/units.parquet"),
        "excluded_successor_licensed_by_t0": excluded_pre,
        "by_split": by.to_dict(orient="index"), "n_by_split": d.split.value_counts().to_dict(),
        "uids": int(d.uid.nunique()),
        "missing_rate_new": {c: round(float(d[c].isna().mean()), 4) for c in new},
    }
    (OUT / "cases_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=int), encoding="utf-8")
    print(json.dumps({k: meta[k] for k in ("rows", "excluded_successor_licensed_by_t0", "n_by_split", "uids")}, ensure_ascii=False, default=int))
    print(by.to_string())
    print(pd.Series(meta["missing_rate_new"]).to_string())


if __name__ == "__main__":
    main()
