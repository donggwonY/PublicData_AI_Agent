"""A-07 기준월 2026-10 → 2027-10 연령대별 예측표 (C안 선택 방법 적용, 2026-11-18).

- 방법·설정: docs/a07/cohort_results_c.json 의 연령대별 개발 구간 선택(pick_on_dev)과 k·alpha 를 그대로 쓴다.
  새로 고르지 않는다. 학습은 정답이 알려진 사용 가능 행(기준월 ≤ 2025-10) 전부.
- 입력: data/raw/a07_cohort/src(10세 구간)·src_1y(1세 단위), cohort_eval.py 와 같은 사전 점검.
- 형식: docs/a07/population_forecast_2027-10.csv(김선경, R1 전 연령)와 같은 열에 method·최근 1년 실제 증감·
  증감 표시 방식을 더한다. 보류 규칙도 같다(최근 12개월 비교 가능한 이력 없음).
- 점검: R1 을 고른 연령대는 기존 예측표와 값이 모두 같아야 한다.
실행(저장소 루트): C:\\claude_workspace\\e06_env\\Scripts\\python scripts/a07_cohort/forecast_2027.py
"""
import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cohort_eval as ce  # noqa: E402
from prepare_a07_population import shift_month  # noqa: E402

ROOT = ce.ROOT
BASE, TARGET = "2026-10", "2027-10"
CFG = json.loads((ROOT / "docs/a07/cohort_results_c.json").read_text(encoding="utf-8"))["bands"]
OLD = ROOT / "docs/a07/population_forecast_2027-10.csv"
OUT_CSV = ROOT / "docs/a07/population_forecast_2027-10_cohort.csv"
OUT_JSON = ROOT / "docs/a07/population_forecast_2027-10_cohort.json"
RECENT_ACTUAL = {"age_30_39", "age_00_09"}  # 앱 표시 규칙: 증감은 최근 1년 실제 기록으로 보여 준다
KF = lambda s: float("inf") if s == "inf" else float(s)  # noqa: E731


def main():
    months = ce.load_months()
    panel = ce.build_panel(months)
    usable = [p for p in panel if p["usable"]]
    assert (len(panel), sum(p["status"] == "matched" for p in panel), len(usable)) == (18863, 16292, 13832)
    assert max(p["month"] for p in usable) == "2025-10"
    ages = ce.load_single(months)
    base_rows = [p for p in panel if p["month"] == BASE]
    P = lambda c, m, b: months[m][c][b] if b else 0  # noqa: E731
    A = lambda c, m, a: ages[m][c][a] if a is not None else 0  # noqa: E731

    def make(p, band, with_target):
        c, t, lo = p["code"], p["month"], ce.LOWER[band]
        t12 = shift_month(t, -12)
        cur = P(c, t, band)
        ch = [cur - P(c, shift_month(t, -L), band) for L in (3, 6, 12)]
        if band == "total":
            s_now, s_prev = cur, P(c, t12, band)
        elif band == "age_100_plus":
            s_now = cur + 0.1 * P(c, t, lo); s_prev = P(c, t12, band) + 0.1 * P(c, t12, lo)
        else:
            s_now = 0.9 * cur + 0.1 * P(c, t, lo); s_prev = 0.9 * P(c, t12, band) + 0.1 * P(c, t12, lo)
        top = ce.TOP.get(band) if band != "age_100_plus" else None
        low_top = ce.TOP.get(lo) if lo else None
        if band == "total":
            s2 = lambda m: P(c, m, band)  # noqa: E731
        elif band == "age_100_plus":
            s2 = lambda m: P(c, m, band) + A(c, m, 99)  # noqa: E731
        else:
            s2 = lambda m: P(c, m, band) - A(c, m, top) + A(c, m, low_top)  # noqa: E731
        r = {"code": c, "gu": p["gu"], "name": p["name"], "month": t, "cur": cur, "ch": ch,
             "s_now": s_now, "s_prev": s_prev, "lo_cur": P(c, t, lo), "lo_ch12": P(c, t, lo) - P(c, t12, lo),
             "s2_now": s2(t), "s2_prev": s2(t12), "top_cur": A(c, t, top), "top_ch12": A(c, t, top) - A(c, t12, top),
             "ltop_cur": A(c, t, low_top), "ltop_ch12": A(c, t, low_top) - A(c, t12, low_top)}
        if with_target:
            r["actual"] = P(c, shift_month(t, 12), band) - cur
        return r

    def add_ratios(rows):
        """구 단위 변화율: 같은 달·같은 구 행의 합(평가와 같은 정의, 예측 달은 이력이 있는 행)."""
        g_now, g1, g2 = defaultdict(float), defaultdict(float), defaultdict(float)
        for r in rows:
            k = r["gu"], r["month"]
            g_now[k] += r["cur"]; g1[k] += r["s_prev"]; g2[k] += r["s2_prev"]
        for r in rows:
            k = r["gu"], r["month"]
            r["r_gu"] = g_now[k] / g1[k] if g1[k] > 0 else 1.0
            r["r_d"] = r["cur"] / r["s_prev"] if r["s_prev"] > 0 else None
            r["r2_gu"] = g_now[k] / g2[k] if g2[k] > 0 else 1.0
            r["r2_d"] = r["cur"] / r["s2_prev"] if r["s2_prev"] > 0 else None

    def cshift(r, k, sfx=""):
        rd, rg, sp, sn = r[f"r{sfx}_d"], r[f"r{sfx}_gu"], r[f"s{sfx}_prev"], r[f"s{sfx}_now"]
        w = 0.0 if rd is None or k == float("inf") else sp / (sp + k) if k > 0 else 1.0
        return max(0, round(sn * (w * (rd or 0) + (1 - w) * rg))) - r["cur"]

    a07_feat = lambda r: [r["cur"], *r["ch"]]  # noqa: E731
    b_feat = lambda r: [r["cur"], *r["ch"], r["lo_cur"], r["lo_ch12"], r["C1"] + r["cur"],  # noqa: E731
                        r["r_d"] or r["r_gu"], r["r_gu"]]
    b2_feat = lambda r: [*b_feat(r), r["C2"] + r["cur"], r["r2_d"] or r["r2_gu"], r["r2_gu"],  # noqa: E731
                         r["top_cur"], r["top_ch12"], r["ltop_cur"], r["ltop_ch12"]]

    def ridge(train, fut, feat, target, alpha, base):
        m = make_pipeline(StandardScaler(), Ridge(alpha=alpha))
        m.fit(np.array([feat(r) for r in train], float), np.array([target(r) for r in train], float))
        pred = m.predict(np.array([feat(r) for r in fut], float))
        return [max(0, round(r["cur"] + base(r) + float(v))) - r["cur"] for r, v in zip(fut, pred)]

    old = {(r["admin_code"], r["age_band"]): r for r in csv.DictReader(OLD.open(encoding="utf-8-sig"))}
    out, summary = [], {}
    for band in ce.BANDS:
        cfg = CFG[band]
        pick = cfg["pick_on_dev"]
        train = [make(p, band, True) for p in usable]
        fut = [make(p, band, False) for p in base_rows if p["history_ok"]]
        add_ratios(train); add_ratios(fut)
        k1 = KF(cfg["c1_k"])
        k2 = k1 if band == "total" else KF(cfg["c2_k"])
        for rows in (train, fut):
            for r in rows:
                r["C1"] = cshift(r, k1)
                r["C2"] = r["C1"] if band == "total" else cshift(r, k2, "2")
        if pick == "R1":
            pred = ridge(train, fut, a07_feat, lambda r: r["actual"], 10, lambda r: 0.0)
        elif pick == "B":
            pred = ridge(train, fut, b_feat, lambda r: r["actual"] - r["C1"], cfg["b_alpha"], lambda r: r["C1"])
        elif pick == "B2":
            pred = ridge(train, fut, b2_feat, lambda r: r["actual"] - r["C2"], cfg["b2_alpha"], lambda r: r["C2"])
        elif pick == "C2":
            pred = [r["C2"] for r in fut]
        else:
            raise ValueError(pick)
        est = {r["code"]: (r, d) for r, d in zip(fut, pred)}
        n_same = n_cmp = 0
        for p in base_rows:
            c = p["code"]
            cur = P(c, BASE, band)
            recent = cur - P(c, shift_month(BASE, -12), band) if p["history_ok"] else None
            r_d = est.get(c)
            change = r_d[1] if r_d else None
            fc = cur + change if r_d else None
            o = old[(c, band)]
            assert int(o["current_population"]) == cur and (o["status"] == "available") == bool(r_d), (c, band)
            if pick == "R1" and r_d:
                n_cmp += 1; n_same += int(o["forecast_population"]) == fc
            out.append({"admin_code": c, "admin_area": o["admin_area"], "age_band": band, "base_month": BASE,
                        "target_month": TARGET, "current_population": cur, "forecast_population": fc,
                        "forecast_change": change,
                        "forecast_change_pct": round(100 * change / cur, 4) if r_d and cur else None,
                        "status": "available" if r_d else "withheld",
                        "withheld_reason": "" if r_d else "incomparable_12_month_history",
                        "method": pick, "recent_change_12m": recent,
                        "change_display": "recent_actual" if band in RECENT_ACTUAL else "forecast"})
        if pick == "R1":
            assert n_same == n_cmp, f"{band}: 기존 R1 예측표와 다름 {n_same}/{n_cmp}"
        avail = [x for x in out if x["age_band"] == band and x["status"] == "available"]
        summary[band] = {"method": pick, "available": len(avail),
                         "current_sum": sum(x["current_population"] for x in avail),
                         "forecast_sum": sum(x["forecast_population"] for x in avail),
                         "areas_up": sum(x["forecast_change"] > 0 for x in avail),
                         "areas_down": sum(x["forecast_change"] < 0 for x in avail),
                         "same_as_existing_r1": f"{n_same}/{n_cmp}" if pick == "R1" else None}
        print(band, summary[band], flush=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows({k: ("" if v is None else v) for k, v in r.items()} for r in out)
    res = {"base_month": BASE, "target_month": TARGET, "methods_from": "docs/a07/cohort_results_c.json",
           "train_base_months": f"{min(p['month'] for p in usable)}..{max(p['month'] for p in usable)}",
           "areas": len(base_rows), "rows": len(out),
           "available_rows": sum(r["status"] == "available" for r in out),
           "csv_sha256": hashlib.sha256(OUT_CSV.read_bytes()).hexdigest(), "bands": summary}
    OUT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print("rows", len(out), "sha256", res["csv_sha256"])


if __name__ == "__main__":
    main()
