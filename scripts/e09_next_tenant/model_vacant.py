"""E-09 2차 3~4단계: 이미 빈 자리 기준 M1·M2 (계획 docs/e09/plan_vacant.md §3~4).

실행(scripts/e09_next_tenant 에서):
  C:/claude_workspace/e06_env/Scripts/python model_vacant.py val    조정(랜드마크 ~2017 → 2018~2019) + 검증 비교 → results/vacant_models_valid.json, vacant_selection.json
  C:/claude_workspace/e06_env/Scripts/python model_vacant.py test   평가 1회 → results/vacant_final_test.json (이미 있으면 중단)
전처리·학습은 1차 model.py 의 Prep·fit_predict 를 그대로 쓴다.
"""
import json
import sys

import numpy as np
import pandas as pd

import common as C
import model as M

VAC_NUM = (["vacant_days", "nb_active_change_since_close", "since_close_open_total"]
           + [f"since_close_open_share_{k}" for k in C.KEYS])
FEATURES = M.BASE_NUM + M.ADD_NUM + VAC_NUM
NAME = "vacant_cases"


def tune(tr, num):
    a, b = tr[tr.lm_year <= 2017], tr[tr.lm_year.between(2018, 2019)]
    res = {}
    for kind, grid in (("M1", M.GRID_LR), ("M2", M.GRID_GBM)):
        sc = [(C.metrics(b["yi"].values, M.fit_predict(kind, g, a, b, num))["logloss"], g) for g in grid]
        best = min(sc, key=lambda s: s[0])
        res[kind] = {"params": best[1], "inner_logloss": best[0], "grid": [{"logloss": s, **g} for s, g in sc]}
    return res


def diffs(uid, yi, pa, pb):
    return {**C.boot_diff(uid, yi, pa, pb), **C.boot_diff_top3(uid, yi, pa, pb)}


def by_landmark(df, yi, preds):
    return {int(L): {"n": int(m.sum()), **{k: C.metrics(yi[m], p[m]) for k, p in preds.items()}}
            for L in sorted(df.L.unique()) for m in [df.L.values == L]}


def run_val():
    d, h = C.load(NAME)
    tr, va = d[d.split == "train"], d[d.split == "valid"].reset_index(drop=True)
    yi, uid = va["yi"].values, va.uid.values
    tuned = tune(tr, FEATURES)
    preds = {"B1": C.b1(tr, va)}
    for k in ("M1", "M2"):
        preds[k] = M.fit_predict(k, tuned[k]["params"], tr, va, FEATURES)
    no_vac = M.BASE_NUM + M.ADD_NUM
    tuned_nv = tune(tr, no_vac)
    preds["M2_no_vacancy_vars"] = M.fit_predict("M2", tuned_nv["M2"]["params"], tr, va, no_vac)
    best = min(("M1", "M2"), key=lambda k: C.metrics(yi, preds[k])["logloss"])
    res = {"cases_sha256": h, "n_train": len(tr), "n_valid": len(va), "uids_valid": int(va.uid.nunique()),
           "metrics": {k: C.metrics(yi, p) for k, p in preds.items()},
           "by_landmark": by_landmark(va, yi, preds),
           "per_class": {k: C.per_class(yi, preds[k]) for k in ("B1", best)},
           "tuning": tuned, "tuning_no_vacancy_vars_M2": tuned_nv["M2"], "best_model": best,
           "diff_best_vs_B1": diffs(uid, yi, preds[best], preds["B1"]),
           "diff_other_vs_B1": diffs(uid, yi, preds["M1" if best == "M2" else "M2"], preds["B1"]),
           "diff_M2_vs_no_vacancy_vars": diffs(uid, yi, preds["M2"], preds["M2_no_vacancy_vars"])}
    C.RES.mkdir(parents=True, exist_ok=True)
    (C.RES / "vacant_models_valid.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    sel = {"baseline": "B1", "model": best, "params": tuned[best]["params"], "features": FEATURES, "cases_sha256": h}
    (C.RES / "vacant_selection.json").write_text(json.dumps(sel, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, m in res["metrics"].items():
        print(k, {a: round(b, 4) for a, b in m.items()})
    for L, t in res["by_landmark"].items():
        print(L, t["n"], {k: (round(t[k]["logloss"], 3), round(t[k]["top3"], 3)) for k in preds})
    print("params", {k: v["params"] for k, v in tuned.items()}, "no_vac", tuned_nv["M2"]["params"])
    for k in ("diff_best_vs_B1", "diff_other_vs_B1", "diff_M2_vs_no_vacancy_vars"):
        print(k, {a: (np.round(b, 4).tolist() if isinstance(b, list) else round(b, 4)) for a, b in res[k].items()})
    print({c: (v["mean_pred"], v["obs_rate"], v["recall"]) for c, v in res["per_class"][best].items()})


def run_test():
    out_path = C.RES / "vacant_final_test.json"
    if out_path.exists():
        raise SystemExit("평가 결과가 이미 있습니다. 평가 구간은 한 번만 봅니다.")
    sel = json.loads((C.RES / "vacant_selection.json").read_text(encoding="utf-8"))
    d, h = C.load(NAME)
    if h != sel["cases_sha256"]:
        raise SystemExit("사례 표가 선택 당시와 다릅니다.")
    tr, te = d[d.split.isin(["train", "valid"])], d[d.split == "test"].reset_index(drop=True)
    yi, uid = te["yi"].values, te.uid.values
    pb = C.b1(tr, te)
    pm = M.fit_predict(sel["model"], sel["params"], tr, te, sel["features"])
    dif = diffs(uid, yi, pm, pb)
    mk = sel["model"]
    res = {"selection": sel, "n_train": len(tr), "n_test": len(te), "uids_test": int(te.uid.nunique()),
           "metrics": {"B1": C.metrics(yi, pb), mk: C.metrics(yi, pm)}, "diff": dif,
           "adopted": bool(dif["logloss_ci"][1] < 0 and dif["top3_diff"] >= -0.01),
           "by_landmark": by_landmark(te, yi, {"B1": pb, mk: pm}),
           "per_class": {"B1": C.per_class(yi, pb), mk: C.per_class(yi, pm)},
           "confusion": {"rows_actual_cols_pred": C.CLASSES,
                         "B1": pd.crosstab(yi, pb.argmax(1)).reindex(index=range(C.K), columns=range(C.K), fill_value=0).values.tolist(),
                         mk: pd.crosstab(yi, pm.argmax(1)).reindex(index=range(C.K), columns=range(C.K), fill_value=0).values.tolist()}}
    groups = {"prev_group": te["prev_group"], "gu": te["f_gu"], "floor": te["floor_class"], "lm_year": te["lm_year"]}
    res["errors"] = {g: {str(k): {"n": int(m.sum()), "B1": C.metrics(yi[m], pb[m]), "model": C.metrics(yi[m], pm[m])}
                         for k in sorted(s.dropna().unique()) for m in [(s == k).values] if m.sum() >= 30}
                     for g, s in groups.items()}
    ll = -np.log(np.clip(pm[np.arange(len(yi)), yi], 1e-9, 1))
    res["largest_errors"] = [{"occupant_id": int(te.occupant_id[i]), "L": int(te.L[i]), "prev": te.prev_group[i],
                              "category": te.category[i], "actual": C.CLASSES[yi[i]], "pred": C.CLASSES[pm[i].argmax()],
                              "p_actual": round(float(pm[i, yi[i]]), 3), "b1_p_actual": round(float(pb[i, yi[i]]), 3),
                              "gu": te.f_gu[i], "floor": te.floor_class[i]} for i in np.argsort(-ll)[:20]]
    out_path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    pd.DataFrame({"occupant_id": te.occupant_id, "L": te.L, "yi": yi, **{f"B1_{c}": pb[:, k] for k, c in enumerate(C.KEYS)},
                  **{f"M_{c}": pm[:, k] for k, c in enumerate(C.KEYS)}}).to_parquet(C.DATA / "vacant_pred_test.parquet", index=False)
    for k, m in res["metrics"].items():
        print(k, {a: round(b, 4) for a, b in m.items()})
    print("diff", {a: (np.round(b, 4).tolist() if isinstance(b, list) else round(b, 4)) for a, b in dif.items()}, "adopted", res["adopted"])


if __name__ == "__main__":
    {"val": run_val, "test": run_test}[sys.argv[1] if len(sys.argv) > 1 else "val"]()
