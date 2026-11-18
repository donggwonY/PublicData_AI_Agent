"""A-07 추가 실험: 30대·0~9세 이사 신호 1단계. 계획 docs/a07/age30_plan.md (2026-11-18 고정).

새 개발 구간(기준월 2019-11~2022-10)에서 고르고, 참고 구간(2023-11~2025-10)은 보고만 한다.
자료 읽기·점검·지표는 cohort_eval.py 의 함수를 그대로 쓴다.
실행(저장소 루트): C:\\claude_workspace\\e06_env\\Scripts\\python scripts/a07_cohort/age30_eval.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cohort_eval as ce  # noqa: E402
from cohort_eval import shift_month  # noqa: E402

ROOT = HERE.parents[1]
# 2단계(계획 '2단계 추가 계획'): --permits 를 주면 건축인허가 입주 물량 변수로 B4·H4 를 더한다.
PERMITS = "--permits" in sys.argv
OUT = ROOT / ("docs/a07/age30_results_stage2.json" if PERMITS else "docs/a07/age30_results.json")
DEV, REF = ("2019-11", "2022-10"), ("2023-11", "2025-10")
A07_FINAL_PERIOD = ("2024-11", "2025-10")
TARGETS = {"age_30_39": {"lower": "age_20_29", "top": 39, "low_top": 29},
           "age_00_09": {"lower": None, "top": 9, "low_top": None}}


def in_p(month, per):
    return per[0] <= month <= per[1]


def load_housing(admin_names):
    """건축인허가 신축·세대 기록 → 행정동별 (사용승인월, 착공월, 세대수×비율) 목록. admin_names: '구 행정동' 집합."""
    import pandas as pd
    codes = json.loads((ROOT / "docs/d03/daegu_legal_codes.json").read_text(encoding="utf-8"))["codes"]
    name_of = {v: k.replace("대구광역시 ", "") for k, v in codes.items()}
    lam = pd.read_parquet(ROOT / "service/data/processed/legal_admin_map.parquet")
    share = defaultdict(list)
    for r in lam.itertuples():
        share[f"{r.gu} {r.legal_dong}"].append((f"{r.gu} {r.admin_dong}", float(r.share)))
    ym = lambda s: f"{s[:4]}-{s[4:6]}" if isinstance(s, str) and len(s.strip()) == 8 and s.strip().isdigit() else None
    out, stat = defaultdict(list), {"records": 0, "new_households_records": 0, "households": 0, "unmapped_households": 0,
                                     "unmapped_legal_dongs": set()}
    for path in sorted((ROOT / "data/raw/a07_cohort/permits").glob("27*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        legal = name_of.get(d["code"], "")
        parts = legal.split()
        gu, ld = (parts[0], " ".join(parts[1:])) if len(parts) >= 2 else ("", "")
        # 리 단위 코드는 읍·면 이름으로 대응표를 찾는다
        targets = share.get(f"{gu} {ld}") or share.get(f"{gu} {ld.split()[0]}") if ld else None
        if not targets and f"{gu} {ld}" in admin_names:
            targets = [(f"{gu} {ld}", 1.0)]
        for it in d["items"]:
            stat["records"] += 1
            hh = int(it.get("hhldCnt") or 0)
            if it.get("archGbCdNm") != "신축" or hh <= 0:
                continue
            stat["new_households_records"] += 1; stat["households"] += hh
            if not targets:
                stat["unmapped_households"] += hh; stat["unmapped_legal_dongs"].add(legal)
                continue
            for adm, sh in targets:
                out[adm].append((ym(it.get("useAprDay")), ym(it.get("realStcnsDay")), hh * sh))
    stat["unmapped_legal_dongs"] = sorted(stat["unmapped_legal_dongs"])
    return out, stat


def housing_feats(recs, t, pop_total):
    t12, t36 = shift_month(t, -12), shift_month(t, -36)
    recent = sum(h for apr, _, h in recs if apr and t12 < apr <= t)
    soon = sum(h for apr, st, h in recs if st and t36 < st <= t12 and (apr is None or apr > t))
    k = max(pop_total, 1) / 1000
    return [recent, soon, recent / k, soon / k]


def main():
    months = ce.load_months()
    panel = ce.build_panel(months)
    usable = [p for p in panel if p["usable"]]
    assert (len(panel), sum(p["status"] == "matched" for p in panel), len(usable)) == (18863, 16292, 13832)
    ages = ce.load_single(months)
    P = lambda c, m, b: months[m][c][b] if b else 0
    A = lambda c, m, a: ages[m][c][a] if a is not None else 0
    res = {"plan": "docs/a07/age30_plan.md", "periods": {"development": DEV, "reference": REF}, "bands": {}}
    housing = None
    if PERMITS:
        names = {rec["name"].replace("대구광역시 ", "") for cur in months.values() for rec in cur.values()}
        housing, hstat = load_housing(names)
        res["housing_input"] = hstat
        print("인허가 입력", {k: (v if not isinstance(v, list) else len(v)) for k, v in hstat.items()}, flush=True)

    for band, cfg in TARGETS.items():
        lo, top, ltop = cfg["lower"], cfg["top"], cfg["low_top"]
        # 같은 구 다른 동의 12개월 변화율(자기 동 제외)에 쓸 구·월 합계
        gsum_now, gsum_prev = defaultdict(float), defaultdict(float)
        for m, cur_m in months.items():
            prev_m = months.get(shift_month(m, -12))
            if prev_m is None:
                continue
            for c, rec in cur_m.items():
                if c in prev_m:
                    gsum_now[c[:5], m] += rec[band]; gsum_prev[c[:5], m] += prev_m[c][band]
        rows = []
        for p in usable:
            c, t = p["code"], p["month"]
            t12 = shift_month(t, -12)
            cur = P(c, t, band)
            ch = [cur - P(c, shift_month(t, -L), band) for L in (3, 6, 12)]
            prev = P(c, t12, band)
            r = {"code": c, "gu": p["gu"], "month": t, "cur": cur, "ch": ch,
                 "actual": P(c, shift_month(t, 12), band) - cur, "R0": max(0, cur + ch[2]) - cur,
                 "lo_cur": P(c, t, lo), "lo_ch12": P(c, t, lo) - P(c, t12, lo)}
            # C1(10세 구간 1/10 이동), C2(1세 이동), C3(0~9세 출생 유입 직접)
            if lo:
                s1 = lambda m: 0.9 * P(c, m, band) + 0.1 * P(c, m, lo)
                s2 = lambda m: P(c, m, band) - A(c, m, top) + A(c, m, ltop)
            else:
                s1 = lambda m: 0.9 * P(c, m, band)
                s2 = lambda m: P(c, m, band) - A(c, m, top)
            s3 = lambda m: P(c, m, band) - A(c, m, top) + A(c, m, 0)
            for sfx, fn in (("1", s1), ("2", s2), ("3", s3)):
                r[f"s{sfx}_now"], r[f"s{sfx}_prev"] = fn(t), fn(t12)
            r.update({"top_cur": A(c, t, top), "top_ch12": A(c, t, top) - A(c, t12, top),
                      "ltop_cur": A(c, t, ltop), "ltop_ch12": A(c, t, ltop) - A(c, t12, ltop)})
            # 1단계 새 변수
            p30 = P(c, t, "age_30_39")
            gp = gsum_prev[c[:5], t] - prev
            r["new"] = [P(c, t, "age_00_09") - P(c, t12, "age_00_09"),
                        p30 - P(c, t12, "age_30_39"),
                        P(c, t, "age_40_49") - P(c, t12, "age_40_49"),
                        P(c, t, "age_00_09") / (p30 + 1),
                        sum(A(c, t, a) for a in range(30, 35)) / (p30 + 1),
                        A(c, t, 0), A(c, t, 0) - A(c, t12, 0),
                        ((gsum_now[c[:5], t] - cur) - gp) / gp if gp > 0 else 0.0]
            if housing is not None:
                adm = months[t][c]["name"].replace("대구광역시 ", "")
                r["house"] = housing_feats(housing.get(adm, []), t, P(c, t, "total"))
            rows.append(r)
        # 구 단위 변화율
        for sfx in ("1", "2", "3"):
            gn, gpv = defaultdict(float), defaultdict(float)
            for r in rows:
                gn[r["gu"], r["month"]] += r["cur"]; gpv[r["gu"], r["month"]] += r[f"s{sfx}_prev"]
            for r in rows:
                g = gpv[r["gu"], r["month"]]
                r[f"r{sfx}_gu"] = gn[r["gu"], r["month"]] / g if g > 0 else 1.0
                r[f"r{sfx}_d"] = r["cur"] / r[f"s{sfx}_prev"] if r[f"s{sfx}_prev"] > 0 else None

        def coh(r, k, sfx):
            rd, rg, sp, sn = r[f"r{sfx}_d"], r[f"r{sfx}_gu"], r[f"s{sfx}_prev"], r[f"s{sfx}_now"]
            w = 0.0 if rd is None or k == float("inf") else sp / (sp + k) if k > 0 else 1.0
            return max(0, round(sn * (w * (rd or 0) + (1 - w) * rg))) - r["cur"]

        by_m = defaultdict(list)
        for r in rows:
            by_m[r["month"]].append(r)
        ms = sorted(by_m)
        dev = [r for r in rows if in_p(r["month"], DEV)]
        ref = [r for r in rows if in_p(r["month"], REF)]
        mae = lambda rs, key: float(np.mean([abs(r[key] - r["actual"]) for r in rs]))

        def roll(feat, target, base, factory, per):
            out = {}
            for m in ms:
                if not in_p(m, per):
                    continue
                last = shift_month(m, -12)
                train = [r for mm in ms if mm <= last for r in by_m[mm]]
                mdl = factory()
                mdl.fit(np.array([feat(r) for r in train], float), np.array([target(r) for r in train], float))
                pred = mdl.predict(np.array([feat(r) for r in by_m[m]], float))
                for r, pv in zip(by_m[m], pred):
                    out[id(r)] = max(0, round(r["cur"] + base(r) + float(pv))) - r["cur"]
            return out

        def put(key, preds):
            for r in rows:
                if id(r) in preds:
                    r[key] = preds[id(r)]

        ridge = lambda a: (lambda: make_pipeline(StandardScaler(), Ridge(alpha=a)))
        hgb = lambda: HistGradientBoostingRegressor(max_iter=200, max_leaf_nodes=15, min_samples_leaf=30,
                                                    learning_rate=0.05, random_state=7)
        info = {}
        # R1: A-07 릿지
        for per in (DEV, REF):
            put("R1", roll(lambda r: [r["cur"], *r["ch"]], lambda r: r["actual"], lambda r: 0.0, ridge(10), per))
        chk = [r for r in rows if in_p(r["month"], A07_FINAL_PERIOD)]
        pre = (round(mae(chk, "R0"), 2), round(mae(chk, "R1"), 2))
        assert pre == ce.A07_FINAL[band], f"A-07 재현 실패 {pre}"
        # C1·C2·C3: k 선택(새 개발 구간)
        sfxs = ("1", "2", "3") if band == "age_00_09" else ("1", "2")
        for sfx in sfxs:
            sc = {str(k): round(float(np.mean([abs(coh(r, k, sfx) - r["actual"]) for r in dev])), 3) for k in ce.KS}
            kb = min(ce.KS, key=lambda k: sc[str(k)])
            for r in rows:
                r[f"C{sfx}"] = coh(r, kb, sfx)
            info[f"C{sfx}_k"] = str(kb); info[f"C{sfx}_k_dev"] = sc
        b_base_feat = lambda r: [r["cur"], *r["ch"], r["lo_cur"], r["lo_ch12"], r["C1"] + r["cur"],
                                 r["r1_d"] or r["r1_gu"], r["r1_gu"], r["C2"] + r["cur"], r["r2_d"] or r["r2_gu"],
                                 r["r2_gu"], r["top_cur"], r["top_ch12"], r["ltop_cur"], r["ltop_ch12"]]

        def fit_resid(key, base_key, feat, factories):
            """보정 모델: 개발 구간에서 후보를 고르고 참고 구간에 같은 설정을 쓴다."""
            scores, preds = {}, {}
            for name, fac in factories.items():
                o = roll(feat, lambda r: r["actual"] - r[base_key], lambda r: r[base_key], fac, DEV)
                scores[name] = round(float(np.mean([abs(o[id(r)] - r["actual"]) for r in dev])), 3)
                preds[name] = o
            best = min(scores, key=scores.get)
            put(key, preds[best])
            put(key, roll(feat, lambda r: r["actual"] - r[base_key], lambda r: r[base_key], factories[best], REF))
            info[f"{key}_dev"] = scores; info[f"{key}_pick"] = best

        alphas = {f"alpha={a}": ridge(a) for a in ce.ALPHAS}
        fit_resid("B2", "C2", b_base_feat, alphas)
        base3 = "C2"
        if band == "age_00_09":
            base3 = "C3" if mae(dev, "C3") < mae(dev, "C2") else "C2"
        info["B3_base"] = base3
        new_feat = lambda r: [*b_base_feat(r), r[base3] + r["cur"], *r["new"]]
        fit_resid("B3", base3, new_feat, alphas)
        fit_resid("H3", base3, new_feat, {"hgb_fixed": hgb})

        methods = ["R0", "R1", "C1", "C2"] + (["C3"] if band == "age_00_09" else []) + ["B2", "B3", "H3"]
        if housing is not None:
            h_feat = lambda r: [*b_base_feat(r), *r["house"]]
            fit_resid("B4", base3, h_feat, alphas)
            fit_resid("H4", base3, h_feat, {"hgb_fixed": hgb})
            methods += ["B4", "H4"]
            dv = [r for r in rows if in_p(r["month"], DEV)]
            info["house_nonzero_share_dev"] = {"recent": round(float(np.mean([r["house"][0] > 0 for r in dv])), 3),
                                               "soon": round(float(np.mean([r["house"][1] > 0 for r in dv])), 3)}
        dev_m = {m: ce.metrics(dev, m) for m in methods}
        ref_m = {m: ce.metrics(ref, m) for m in methods}
        pick = min(methods, key=lambda m: dev_m[m]["mae_people"])
        ci = ce.boot_ci(ref, pick) if pick != "R0" else None
        ok = (pick != "R0" and ref_m[pick]["mae_people"] < min(ref_m["R0"]["mae_people"], ref_m["R1"]["mae_people"])
              and ref_m[pick]["direction_accuracy"] >= ref_m["R0"]["direction_accuracy"] and ci[1] < 0)
        res["bands"][band] = {"a07_reproduced_R0_R1": pre, "settings": info, "development": dev_m, "reference": ref_m,
                              "pick_on_dev": pick, "reference_improvement_vs_R0_ci95": ci, "provisional_pass": bool(ok)}
        print(band, "pick", pick, "| dev MAE", {m: round(dev_m[m]["mae_people"], 1) for m in methods})
        print("   ref MAE", {m: round(ref_m[m]["mae_people"], 1) for m in methods})
        print("   ref dir", {m: round(ref_m[m]["direction_accuracy"] * 100, 1) for m in methods}, "CI", ci, "잠정 통과", ok,
              flush=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
