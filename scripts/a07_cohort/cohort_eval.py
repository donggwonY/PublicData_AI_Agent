"""A-07 추가 실험: 코호트 이동 기준선(C1)과 보정 릿지(B). 계획 docs/a07/cohort_plan.md (2026-11-18 고정).

입력: data/raw/a07_cohort/src/*.csv (download_population.py, 대구 읍·면·동 거주자 10세 구간 월별).
1) A-07 준비 규칙(prepare_a07_population.py)과 같은 방식으로 지역·월 표와 사용 가능 행을 만든다.
2) 사전 점검: 행 수(18,863 / 16,292 / 13,832)와 A-07이 발표한 R0·R1 최근 평가 오차를 재현해야 진행한다.
3) 개발 구간에서 C1의 k, B의 alpha, 연령대별 표시 후보를 고르고 최근 평가 구간에서 판정한다.
실행(저장소 루트): service/.venv/Scripts/python scripts/a07_cohort/cohort_eval.py
"""
import csv
import hashlib
import itertools
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from prepare_a07_population import DISTRICT_CHANGES, shift_month  # noqa: E402

SRC = ROOT / "data/raw/a07_cohort/src"
# C안(docs/a07/cohort_plan_c.md): --single-age 를 주면 1세 단위 자료로 C2·B2 를 추가한다. 없으면 B안과 같다.
SINGLE = "--single-age" in sys.argv
SRC1 = ROOT / "data/raw/a07_cohort/src_1y"
OUT = ROOT / ("docs/a07/cohort_results_c.json" if SINGLE else "docs/a07/cohort_results.json")
TOP = {"age_00_09": 9, "age_10_19": 19, "age_20_29": 29, "age_30_39": 39, "age_40_49": 49, "age_50_59": 59,
       "age_60_69": 69, "age_70_79": 79, "age_80_89": 89, "age_90_99": 99}
AREA = re.compile(r"(.+?)\s*\((27\d{8})\)\s*$")
BANDS = ["total", "age_00_09", "age_10_19", "age_20_29", "age_30_39", "age_40_49", "age_50_59",
         "age_60_69", "age_70_79", "age_80_89", "age_90_99", "age_100_plus"]
LABEL = {"총인구수": "total", "0~9세": "age_00_09", "10~19세": "age_10_19", "20~29세": "age_20_29",
         "30~39세": "age_30_39", "40~49세": "age_40_49", "50~59세": "age_50_59", "60~69세": "age_60_69",
         "70~79세": "age_70_79", "80~89세": "age_80_89", "90~99세": "age_90_99", "100세 이상": "age_100_plus"}
LOWER = {b: (BANDS[i - 1] if i >= 2 else None) for i, b in enumerate(BANDS)}  # total·0~9세는 아래 연령대 없음
PERIODS = {"development": ("2023-11", "2024-10"), "final": ("2024-11", "2025-10")}
KS = [0, 100, 1000, float("inf")]
ALPHAS = [1, 10, 100]
# A-07 README 전 연령 2단계 표(최근 평가, 인구 평균 절대오차: 기준선 → 릿지)
A07_FINAL = {"total": (432.51, 279.16), "age_00_09": (61.30, 39.70), "age_10_19": (54.03, 44.10),
             "age_20_29": (70.93, 62.98), "age_30_39": (118.88, 79.59), "age_40_49": (89.48, 58.03),
             "age_50_59": (80.78, 76.76), "age_60_69": (51.30, 52.01), "age_70_79": (35.68, 39.14),
             "age_80_89": (21.91, 31.75), "age_90_99": (8.74, 6.41), "age_100_plus": (1.12, 0.73)}


def load_months():
    months = {}
    for path in sorted(SRC.glob("pop_*.csv")):
        with path.open(encoding="utf-8", newline="") as h:
            rows = list(csv.reader(h))
        header = rows[0]
        cols = {}
        for i, name in enumerate(header):
            m = re.fullmatch(r"(\d{4})년(\d{2})월_거주자_(.+)", name)
            if m and m.group(3) in LABEL:
                cols[i] = (f"{m.group(1)}-{m.group(2)}", LABEL[m.group(3)])
        for row in rows[1:]:
            name, code = AREA.fullmatch(row[0]).groups()
            for i, (month, band) in cols.items():
                v = row[i].strip()
                if v:
                    months.setdefault(month, {}).setdefault(code, {"name": name})[band] = int(v.replace(",", ""))
    expected = {shift_month("2016-01", i) for i in range(130)}
    if set(months) != expected:
        raise ValueError(f"월 범위 불일치: {sorted(set(months) ^ expected)[:5]}")
    for month, cur in months.items():
        local = {c: v for c, v in cur.items() if not c.endswith("00000")}
        for b in BANDS:
            if sum(v.get(b, 0) for v in local.values()) != cur["2700000000"][b]:
                raise ValueError(f"시 합계 불일치 {month} {b}")
        for c, v in local.items():
            if v["total"] != sum(v[b] for b in BANDS[1:]):
                raise ValueError(f"연령 합계 불일치 {month} {c}")
        months[month] = local
    return months


def load_single(months):
    """1세 단위 자료: {월: {코드: {나이(int, 100=100세 이상): 인원}}}. 10세 구간 합이 B안 입력과 같아야 한다."""
    ages = {}
    for path in sorted(SRC1.glob("pop_*.csv")):
        with path.open(encoding="utf-8", newline="") as h:
            rows = list(csv.reader(h))
        cols = {}
        for i, name in enumerate(rows[0]):
            m = re.fullmatch(r"(\d{4})년(\d{2})월_거주자_(\d+)세( 이상)?", name)
            if m:
                cols[i] = (f"{m.group(1)}-{m.group(2)}", int(m.group(3)))
        for row in rows[1:]:
            _, code = AREA.fullmatch(row[0]).groups()
            for i, (month, age) in cols.items():
                v = row[i].strip()
                if v:
                    ages.setdefault(month, {}).setdefault(code, {})[age] = int(v.replace(",", ""))
    for month, cur in months.items():
        for code, rec in cur.items():
            a = ages[month][code]
            for band, top in TOP.items():
                if sum(a[x] for x in range(top - 9, top + 1)) != rec[band]:
                    raise ValueError(f"1세 합계 불일치 {month} {code} {band}")
            if a[100] != rec["age_100_plus"]:
                raise ValueError(f"100세 이상 불일치 {month} {code}")
    return ages


def build_panel(months):
    """prepare_a07_population.build_panel 과 같은 규칙(이름 연속성, 구 변경 공고, 12개월 이력)."""
    changes = defaultdict(set, {k: set(v) for k, v in DISTRICT_CHANGES.items()})
    for month, cur in sorted(months.items()):
        prev = months.get(shift_month(month, -1))
        if prev is not None:
            for code in cur.keys() ^ prev.keys():
                changes[code[:5]].add(month)
    panel = []
    for month, cur in sorted(months.items()):
        target = shift_month(month, 12)
        for code, rec in sorted(cur.items()):
            hist_m = [shift_month(month, o) for o in range(-12, 1)]
            fut_m = [shift_month(month, o) for o in range(1, 13)]
            hist = [months.get(k, {}).get(code) for k in hist_m]
            fut = [months.get(k, {}).get(code) for k in fut_m]
            dc = changes[code[:5]]
            if target not in months:
                status = "awaiting_observation"
            elif any(k in dc for k in fut_m):
                status = "district_change"
            elif any(r is None or r["name"] != rec["name"] for r in fut):
                status = "code_or_name_discontinuity"
            else:
                status = "matched"
            hist_ok = all(r is not None and r["name"] == rec["name"] for r in hist) and not dc.intersection(hist_m[1:])
            panel.append({"code": code, "gu": code[:5], "name": rec["name"], "month": month, "status": status,
                          "history_ok": hist_ok, "usable": hist_ok and status == "matched"})
    return panel


def sign(x):
    return (x > 0) - (x < 0)


def metrics(rows, key):
    """A-07 evaluate_a07_baselines.evaluate 와 같은 정의. rows: dict(actual, month, preds...)."""
    err = [abs(r[key] - r["actual"]) for r in rows]
    direc = [sign(r[key]) == sign(r["actual"]) for r in rows]
    by_m = defaultdict(list)
    for r in rows:
        by_m[r["month"]].append(r)
    hits = cnt = 0
    for mr in by_m.values():
        a = np.array([r["actual"] for r in mr]); p = np.array([r[key] for r in mr])
        i, j = np.triu_indices(len(mr), 1)
        act = np.sign(a[i] - a[j]); pr = np.sign(p[i] - p[j])
        m = act != 0
        cnt += int(m.sum()); hits += int((pr[m] == act[m]).sum())
    return {"mae_people": round(float(np.mean(err)), 4), "direction_accuracy": round(float(np.mean(direc)), 4),
            "pair_order_accuracy": round(hits / cnt, 4) if cnt else None, "rows": len(rows)}


def boot_ci(rows, key, base="R0", n=1000, seed=0):
    by = defaultdict(list)
    for r in rows:
        by[r["code"]].append(abs(r[key] - r["actual"]) - abs(r[base] - r["actual"]))
    codes = sorted(by)
    sums = np.array([sum(by[c]) for c in codes]); cnts = np.array([len(by[c]) for c in codes])
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(codes), size=(n, len(codes)))
    stat = sums[idx].sum(1) / cnts[idx].sum(1)
    return [round(float(np.percentile(stat, 2.5)), 3), round(float(np.percentile(stat, 97.5)), 3)]


def main():
    months = load_months()
    panel = build_panel(months)
    matched = sum(p["status"] == "matched" for p in panel)
    usable_rows = [p for p in panel if p["usable"]]
    pre = {"rows": len(panel), "matched": matched, "usable": len(usable_rows)}
    print("사전 점검 행 수", pre)
    assert pre == {"rows": 18863, "matched": 16292, "usable": 13832}, "A-07 행 수와 다름"
    P = lambda code, month, band: months[month][code][band] if band else 0
    ages = load_single(months) if SINGLE else None
    if SINGLE:
        print("사전 점검 1세 합계 = 10세 구간 자료: 통과", flush=True)
    A = lambda code, month, age: ages[month][code][age] if age is not None else 0
    src_hash = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(SRC.glob("pop_*.csv"))}

    res = {"plan": "docs/a07/cohort_plan.md", "precheck_rows": pre, "src_files": len(src_hash),
           "src_sha256_of_hashes": hashlib.sha256("".join(src_hash.values()).encode()).hexdigest(),
           "bands": {}}
    for band in BANDS:
        lo = LOWER[band]
        rows = []
        for p in usable_rows:
            c, t = p["code"], p["month"]
            cur = P(c, t, band)
            ch = [cur - P(c, shift_month(t, -L), band) for L in (3, 6, 12)]
            t12 = shift_month(t, -12)
            if band == "total":
                s_now, s_prev = cur, P(c, t12, band)
            elif band == "age_100_plus":   # 열린 구간: 나가는 몫 없음
                s_now = cur + 0.1 * P(c, t, lo); s_prev = P(c, t12, band) + 0.1 * P(c, t12, lo)
            else:
                s_now = 0.9 * cur + 0.1 * P(c, t, lo); s_prev = 0.9 * P(c, t12, band) + 0.1 * P(c, t12, lo)
            after = P(c, shift_month(t, 12), band)
            row = {"code": c, "gu": p["gu"], "month": t, "cur": cur, "ch": ch, "s_now": s_now, "s_prev": s_prev,
                   "lo_cur": P(c, t, lo), "lo_ch12": P(c, t, lo) - P(c, t12, lo),
                   "actual": after - cur, "R0": max(0, cur + ch[2]) - cur}
            if SINGLE:
                # 정확한 1세 이동: 이 구간의 가장 높은 나이는 나가고, 아래 구간의 가장 높은 나이가 들어온다
                top = TOP.get(band) if band != "age_100_plus" else None
                low_top = TOP.get(lo) if lo else None
                if band == "total":
                    s2 = lambda m: P(c, m, band)
                elif band == "age_100_plus":
                    s2 = lambda m: P(c, m, band) + A(c, m, 99)
                else:
                    s2 = lambda m, top=top, low_top=low_top: P(c, m, band) - A(c, m, top) + A(c, m, low_top)
                row.update({"s2_now": s2(t), "s2_prev": s2(t12),
                            "top_cur": A(c, t, top), "top_ch12": A(c, t, top) - A(c, t12, top),
                            "ltop_cur": A(c, t, low_top), "ltop_ch12": A(c, t, low_top) - A(c, t12, low_top)})
            rows.append(row)
        # 구 단위 변화율(같은 달, 같은 구의 사용 가능 행 합)
        g_now = defaultdict(float); g_prev = defaultdict(float)
        for r in rows:
            g_now[r["gu"], r["month"]] += r["cur"]; g_prev[r["gu"], r["month"]] += r["s_prev"]
        for r in rows:
            gp = g_prev[r["gu"], r["month"]]
            r["r_gu"] = g_now[r["gu"], r["month"]] / gp if gp > 0 else 1.0
            r["r_d"] = r["cur"] / r["s_prev"] if r["s_prev"] > 0 else None
        if SINGLE:
            g2 = defaultdict(float)
            for r in rows:
                g2[r["gu"], r["month"]] += r["s2_prev"]
            for r in rows:
                gp = g2[r["gu"], r["month"]]
                r["r2_gu"] = g_now[r["gu"], r["month"]] / gp if gp > 0 else 1.0
                r["r2_d"] = r["cur"] / r["s2_prev"] if r["s2_prev"] > 0 else None

        def c1(r, k, sfx=""):
            rd, rg, sp, sn = r[f"r{sfx}_d"], r[f"r{sfx}_gu"], r[f"s{sfx}_prev"], r[f"s{sfx}_now"]
            w = 0.0 if rd is None or k == float("inf") else sp / (sp + k) if k > 0 else 1.0
            rr = w * (rd or 0) + (1 - w) * rg
            return max(0, round(sn * rr)) - r["cur"]

        by_month = defaultdict(list)
        for r in rows:
            by_month[r["month"]].append(r)
        months_sorted = sorted(by_month)

        def in_period(r, per):
            return PERIODS[per][0] <= r["month"] <= PERIODS[per][1]

        def roll(feat_fn, target_fn, alpha, period, base_fn=lambda r: 0.0):
            """A-07 backtest 와 같은 시점 이동: 기준월 m 예측은 기준월 ≤ m−12 행으로 학습."""
            out = {}
            for m in months_sorted:
                if not PERIODS[period][0] <= m <= PERIODS[period][1]:
                    continue
                last = shift_month(m, -12)
                train = [r for mm in months_sorted if mm <= last for r in by_month[mm]]
                model = make_pipeline(StandardScaler(), Ridge(alpha=alpha))
                model.fit(np.array([feat_fn(r) for r in train], float), np.array([target_fn(r) for r in train], float))
                pred = model.predict(np.array([feat_fn(r) for r in by_month[m]], float))
                for r, pv in zip(by_month[m], pred):
                    out[id(r)] = max(0, round(r["cur"] + base_fn(r) + float(pv))) - r["cur"]
            return out

        a07_feat = lambda r: [r["cur"], *r["ch"]]
        # R1: A-07 릿지 그대로
        for per in PERIODS:
            o = roll(a07_feat, lambda r: r["actual"], 10, per)
            for r in rows:
                if id(r) in o:
                    r["R1"] = o[id(r)]
        dev = [r for r in rows if in_period(r, "development")]
        fin = [r for r in rows if in_period(r, "final")]
        pre_r = (metrics(fin, "R0")["mae_people"], metrics(fin, "R1")["mae_people"])
        if (round(pre_r[0], 2), round(pre_r[1], 2)) != A07_FINAL[band]:
            raise AssertionError(f"{band}: A-07 재현 실패 {pre_r} vs {A07_FINAL[band]}")
        # C1: k 선택(개발)
        k_scores = {str(k): round(float(np.mean([abs(c1(r, k) - r["actual"]) for r in dev])), 4) for k in KS}
        k_best = min(KS, key=lambda k: k_scores[str(k)])
        for r in rows:
            r["C1"] = c1(r, k_best)
        # B: 보정 릿지, alpha 선택(개발)
        b_feat = lambda r: [r["cur"], *r["ch"], r["lo_cur"], r["lo_ch12"], r["C1"] + r["cur"], r["r_d"] or r["r_gu"], r["r_gu"]]
        b_target = lambda r: r["actual"] - r["C1"]
        b_base = lambda r: r["C1"]
        a_scores, b_preds = {}, {}
        for a in ALPHAS:
            o = roll(b_feat, b_target, a, "development", b_base)
            a_scores[str(a)] = round(float(np.mean([abs(o[id(r)] - r["actual"]) for r in dev])), 4)
            b_preds[a] = o
        a_best = min(ALPHAS, key=lambda a: a_scores[str(a)])
        o_fin = roll(b_feat, b_target, a_best, "final", b_base)
        for r in rows:
            if id(r) in b_preds[a_best]:
                r["B"] = b_preds[a_best][id(r)]
            if id(r) in o_fin:
                r["B"] = o_fin[id(r)]
        methods = ["R0", "R1", "C1", "B"]
        extra = {}
        if SINGLE and band == "total":   # 나이 이동이 없으므로 C2 = C1, B2 = B (계획)
            for r in rows:
                r["C2"], r["B2"] = r["C1"], r.get("B")
            extra = {"c2_k": "C1과 같음", "b2_alpha": "B와 같음"}
            methods += ["C2", "B2"]
        elif SINGLE:
            k2_scores = {str(k): round(float(np.mean([abs(c1(r, k, "2") - r["actual"]) for r in dev])), 4) for k in KS}
            k2 = min(KS, key=lambda k: k2_scores[str(k)])
            for r in rows:
                r["C2"] = c1(r, k2, "2")
            b2_feat = lambda r: [*b_feat(r), r["C2"] + r["cur"], r["r2_d"] or r["r2_gu"], r["r2_gu"],
                                 r["top_cur"], r["top_ch12"], r["ltop_cur"], r["ltop_ch12"]]
            b2_target = lambda r: r["actual"] - r["C2"]
            b2_base = lambda r: r["C2"]
            a2_scores, b2_preds = {}, {}
            for a in ALPHAS:
                o = roll(b2_feat, b2_target, a, "development", b2_base)
                a2_scores[str(a)] = round(float(np.mean([abs(o[id(r)] - r["actual"]) for r in dev])), 4)
                b2_preds[a] = o
            a2 = min(ALPHAS, key=lambda a: a2_scores[str(a)])
            o2_fin = roll(b2_feat, b2_target, a2, "final", b2_base)
            for r in rows:
                r["B2"] = b2_preds[a2].get(id(r), o2_fin.get(id(r)))
            extra = {"c2_k_dev_mae": k2_scores, "c2_k": str(k2), "b2_alpha_dev_mae": a2_scores, "b2_alpha": a2}
            methods += ["C2", "B2"]
        dev_m = {m: metrics(dev, m) for m in methods}
        fin_m = {m: metrics(fin, m) for m in methods}
        pick = min(methods, key=lambda m: dev_m[m]["mae_people"])
        ci = boot_ci(fin, pick) if pick != "R0" else None
        passed = bool(pick != "R0" and fin_m[pick]["mae_people"] < fin_m["R0"]["mae_people"] and ci[1] < 0)
        res["bands"][band] = {"lower_band": LOWER[band], "c1_k_dev_mae": k_scores, "c1_k": str(k_best),
                              "b_alpha_dev_mae": a_scores, "b_alpha": a_best,
                              "development": dev_m, "final": fin_m, "pick_on_dev": pick,
                              "final_improvement_vs_R0_ci95": ci, "display_pass": passed,
                              "a07_reproduced_final_R0_R1": pre_r, **extra}
        print(band, "pick", pick, "k", k_best, "alpha", a_best, "| final MAE",
              {m: fin_m[m]["mae_people"] for m in methods}, "CI", ci, "pass", passed, flush=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
