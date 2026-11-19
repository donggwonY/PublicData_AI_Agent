"""E-08 1단계: 브랜드 × 기준년도 패널과 변수 표 (계획 docs/e08/plan.md §1~3).

입력: data/raw/e08_franchise/*.jsonl.gz (download_ftc.py)
출력(저장소 밖): C:/claude_workspace/e08_data/panel.parquet, panel_meta.json(행 수·결측률·SHA-256)
실행(저장소 루트): C:/claude_workspace/e06_env/Scripts/python scripts/e08_franchise/panel.py

시점 규칙: 기준년도 N 행의 변수는 features(N)에서 N 이하 연도의 파일만 읽어 만든다(load 함수가 연도 상한을 받는다).
정답은 N+1 파일로만 만든다.
"""
import gzip
import hashlib
import json
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/raw/e08_franchise"
OUT = Path("C:/claude_workspace/e08_data")
YEARS = range(2017, 2026)          # 기준년도 N (정답 N+1 ≤ 2026)
MIN_DAEGU = 3


@lru_cache(maxsize=None)
def _rows(name: str, year: int) -> tuple:
    p = RAW / f"{name}_{year}.jsonl.gz"
    if not p.exists():
        return ()
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return tuple(json.loads(line) for line in f)


def load(name: str, year: int, upto: int) -> tuple:
    """연도 상한을 강제하는 읽기: features(N)은 upto=N으로만 부른다."""
    if year > upto:
        raise ValueError(f"{name} {year} > 기준년도 {upto}: 미래 자료 읽기 금지")
    return _rows(name, year)


@lru_cache(maxsize=None)
def region(year: int) -> pd.DataFrame:
    """브랜드별 대구 가맹·직영, 전국 가맹, 진출 시·도 수, 본부 번호. 행이 없으면 그 지역 0곳."""
    df = pd.DataFrame(_rows("brand_region", year))
    for c in ("frcsCnt", "dmsCnt"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    sido = df[df["areaNm"] != "전체"]
    out = pd.DataFrame({
        "hq": df.groupby("brandMnno")["jnghdqrtrsMnno"].first(),
        "dg_frcs": sido[sido["areaNm"] == "대구"].set_index("brandMnno")["frcsCnt"],
        "dg_dms": sido[sido["areaNm"] == "대구"].set_index("brandMnno")["dmsCnt"],
        "nat_frcs": df[df["areaNm"] == "전체"].set_index("brandMnno")["frcsCnt"],
        "n_sido": sido[sido["frcsCnt"] > 0].groupby("brandMnno").size(),
    })
    out[["dg_frcs", "dg_dms", "n_sido"]] = out[["dg_frcs", "dg_dms", "n_sido"]].fillna(0)
    out["nat_frcs"] = out["nat_frcs"].fillna(sido.groupby("brandMnno")["frcsCnt"].sum())
    return out


@lru_cache(maxsize=None)
def brand_list(year: int) -> pd.DataFrame:
    """그해 브랜드 목록. 같은 번호가 여러 행이면(가맹본부 변경) 지역 자료의 본부 번호와 같은 행, 없으면 첫 행."""
    df = pd.DataFrame(_rows("brand_list", year))
    hq = region(year)["hq"] if (RAW / f"brand_region_{year}.jsonl.gz").exists() else pd.Series(dtype=object)
    df["_match"] = df["jnghdqrtrsMnno"].values == df["brandMnno"].map(hq).values
    df = df.sort_values("_match", ascending=False, kind="stable").drop_duplicates("brandMnno")
    return df.set_index("brandMnno")


@lru_cache(maxsize=None)
def stats(year: int) -> pd.DataFrame:
    """가맹점 현황 yr=year를 브랜드명+법인명으로 브랜드 번호에 연결. 키가 여러 번호에 걸리면 연결하지 않는다."""
    st = pd.DataFrame(_rows("brand_stats", year))
    if st.empty:
        return pd.DataFrame()
    lst = pd.DataFrame(_rows("brand_list", year))      # 중복 행 포함: 본부별 법인명 모두 키로 쓴다
    keys = lst.groupby(["brandNm", "corpNm"])["brandMnno"].agg(lambda s: s.unique().tolist())
    keys = keys[keys.map(len) == 1].map(lambda v: v[0])
    st = st.drop_duplicates(["brandNm", "corpNm"], keep=False)   # 현황 쪽 같은 키 중복도 제외
    st["brandMnno"] = [keys.get((b, c)) for b, c in zip(st["brandNm"], st["corpNm"])]
    st = st.dropna(subset=["brandMnno"]).drop_duplicates("brandMnno", keep=False).set_index("brandMnno")
    num = ["frcsCnt", "newFrcsRgsCnt", "ctrtEndCnt", "ctrtCncltnCnt", "nmChgCnt", "avrgSlsAmt", "arUnitAvrgSlsAmt"]
    st[num] = st[num].apply(pd.to_numeric, errors="coerce")
    st.loc[st["avrgSlsAmt"] <= 0, "avrgSlsAmt"] = np.nan          # 0 = 미기재
    st.loc[st["arUnitAvrgSlsAmt"] <= 0, "arUnitAvrgSlsAmt"] = np.nan
    return st[num]


def outcome(n: int) -> pd.DataFrame:
    """대상(기준년도 n 대구 가맹 ≥3)과 정답. N+1 목록에 없으면 status='absent'(주 분석 제외)."""
    r0, r1 = region(n), region(n + 1)
    base = r0[r0["dg_frcs"] >= MIN_DAEGU]
    nxt_list = set(brand_list(n + 1).index)
    nxt = base.index.map(lambda b: r1["dg_frcs"].get(b, 0.0))
    status = np.where(~base.index.isin(nxt_list), "absent",
                      np.where(nxt < base["dg_frcs"].values, "decline", "keep"))
    return pd.DataFrame({"N": n, "dg_frcs_next": np.where(status == "absent", np.nan, nxt),
                         "status": status}, index=base.index)


def _industry_flow(n: int) -> pd.Series:
    """직전 쌍(n-1 → n) 대구 감소율: 중분류(대상 10곳 이상) → 대분류 → 전체. 기준년도 n 이하 자료만."""
    if n - 1 < min(YEARS):
        return pd.Series(dtype=float)
    load("brand_region", n, upto=n)
    prev = outcome(n - 1)                       # n-1 대상의 n 시점 결과: 기준년도 n까지의 자료
    prev = prev[prev["status"] != "absent"]
    meta = brand_list(n - 1).reindex(prev.index)
    prev = prev.assign(y=(prev["status"] == "decline").astype(float),
                       mid=meta["indutyMlsfcNm"].values, lcl=meta["indutyLclasNm"].values)
    mid = prev.groupby("mid")["y"].agg(["mean", "size"])
    lcl = prev.groupby("lcl")["y"].agg(["mean", "size"])
    return pd.Series({"_mid": mid, "_lcl": lcl, "_all": prev["y"].mean()})


def features(n: int, ids: pd.Index) -> pd.DataFrame:
    for name in ("brand_region", "brand_list", "brand_stats"):
        load(name, n, upto=n)
    r0 = region(n).reindex(ids)
    rp = region(n - 1).reindex(ids) if n - 1 >= 2017 else None
    lst = brand_list(n).reindex(ids)
    s0 = stats(n).reindex(ids)
    sp = stats(n - 1).reindex(ids) if n - 1 >= 2017 else pd.DataFrame(index=ids)
    f = pd.DataFrame(index=ids)
    f["dg_frcs_log"] = np.log1p(r0["dg_frcs"])
    f["dg_dms"] = r0["dg_dms"]
    if rp is not None:
        prev_dg = rp["dg_frcs"]
        f["dg_prev_missing"] = prev_dg.isna().astype(int)
        prev_dg = prev_dg.fillna(0)
        f["dg_chg"] = r0["dg_frcs"] - prev_dg
        f["dg_chg_rate"] = np.where(prev_dg > 0, f["dg_chg"] / prev_dg.where(prev_dg > 0, 1), np.nan)
        f["nat_chg_rate"] = np.where(rp["nat_frcs"] > 0, (r0["nat_frcs"] - rp["nat_frcs"]) / rp["nat_frcs"].where(rp["nat_frcs"] > 0, 1), np.nan)
    else:
        f["dg_prev_missing"] = 1
        f["dg_chg"] = f["dg_chg_rate"] = f["nat_chg_rate"] = np.nan
    f["dg_share"] = r0["dg_frcs"] / r0["nat_frcs"].where(r0["nat_frcs"] > 0)
    f["nat_frcs_log"] = np.log1p(r0["nat_frcs"])
    f["n_sido"] = r0["n_sido"]
    denom = s0["frcsCnt"].where(s0["frcsCnt"] > 0)
    for c, k in (("newFrcsRgsCnt", "new_rate"), ("ctrtEndCnt", "end_rate"), ("ctrtCncltnCnt", "cancel_rate"), ("nmChgCnt", "namechg_rate")):
        f[k] = s0[c] / denom
    f["sales_log"] = np.log(s0["avrgSlsAmt"])
    f["sales_area_log"] = np.log(s0["arUnitAvrgSlsAmt"])
    f["sales_chg_rate"] = (s0["avrgSlsAmt"] / sp["avrgSlsAmt"] - 1) if "avrgSlsAmt" in sp else np.nan
    f["stats_unlinked"] = s0["frcsCnt"].isna().astype(int)
    start = pd.to_numeric(lst["jngBizStrtDate"].astype(str).str[:4], errors="coerce")
    f["brand_age"] = (n - start).where((start >= 1950) & (start <= n))
    f["induty_l"] = lst["indutyLclasNm"]
    f["induty_m"] = lst["indutyMlsfcNm"]
    hq_n = brand_list(n)["jnghdqrtrsMnno"].value_counts()
    f["hq_brands"] = lst["jnghdqrtrsMnno"].map(hq_n)
    flow = _industry_flow(n)
    if len(flow):
        mid, lcl, al = flow["_mid"], flow["_lcl"], flow["_all"]
        def rate(m, l):
            if m in mid.index and mid.loc[m, "size"] >= 10:
                return mid.loc[m, "mean"]
            if l in lcl.index and lcl.loc[l, "size"] >= 10:
                return lcl.loc[l, "mean"]
            return al
        f["induty_prev_decline"] = [rate(m, l) for m, l in zip(f["induty_m"], f["induty_l"])]
    else:
        f["induty_prev_decline"] = np.nan
    return f


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    parts = []
    for n in YEARS:
        y = outcome(n)
        parts.append(y.join(features(n, y.index)))
        print(n, len(y), (y["status"] == "decline").sum(), (y["status"] == "absent").sum(), flush=True)
    panel = pd.concat(parts).reset_index(names="brandMnno")
    panel["y"] = (panel["status"] == "decline").astype(int)
    panel["y_absent_as_decline"] = panel["status"].isin(["decline", "absent"]).astype(int)
    path = OUT / "panel.parquet"
    panel.to_parquet(path, index=False)
    feat = [c for c in panel.columns if c not in ("brandMnno", "N", "dg_frcs_next", "status", "y", "y_absent_as_decline")]
    counts = panel.groupby("N")["status"].value_counts().unstack(fill_value=0)
    meta = {
        "rows": len(panel), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "by_year": {str(k): v for k, v in counts.to_dict(orient="index").items()},
        "missing_rate": {c: round(float(panel[c].isna().mean()), 4) for c in feat},
        "missing_rate_main": {c: round(float(panel.loc[panel["status"] != "absent", c].isna().mean()), 4) for c in feat},
        "raw_sources": json.loads((RAW / "sources.json").read_text(encoding="utf-8")),
    }
    (OUT / "panel_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(counts)
    print(pd.Series(meta["missing_rate_main"]).to_string())


if __name__ == "__main__":
    sys.exit(main())
