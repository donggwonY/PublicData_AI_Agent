"""E-09 3~4단계: M1 다항 로지스틱·M2 LightGBM (계획 docs/e09/plan.md §3~5).

실행(저장소 루트에서):
  C:/claude_workspace/e06_env/Scripts/python scripts/e09_next_tenant/model.py val    조정(학습 안 분할) + 검증 비교 → results/models_valid.json, selection.json
  C:/claude_workspace/e06_env/Scripts/python scripts/e09_next_tenant/model.py test   평가 1회 → results/final_test.json (이미 있으면 중단)
"""
import json
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

import common as C

CAT = ["prev_group", "service", "category", "floor_class", "f_gu"]
BASE_NUM = ["prev_life_years", "prev_area_m2", "prev_n_licenses", "close_month", "covid",
            "h_n_occ", "h_n_closed", "h_n_turnover", "h_mean_gap_days", "h_years_since_first", "h_n_groups",
            "s1_nb_active", "s1_nb_active_same", "s1_nb_open_12m", "s1_nb_close_12m", "s1_nb_net_12m", "s1_nb_net_same_12m",
            "s1_nb_vacant", "s1_nb_vacancy_rate", "s1_dong_vacancy_rate", "s1_dong_live_change_3y",
            "s1_sub_dist_m", "s1_sub_board_12m", "s1_sub_board_yoy",
            "s1_pop", "s1_pop_2039_share", "s1_pop_60plus_share", "s1_pop_change_12m", "s1_pop_is_dong"]
ADD_NUM = ([f"nb_act_share_{k}" for k in C.KEYS] + [f"nb_open12_share_{k}" for k in C.KEYS] + ["nb_open12_total"]
           + [f"city_reopen36_share_{k}" for k in C.KEYS])
GRID_LR = [{"C": c} for c in (0.01, 0.1, 1.0)]
GRID_GBM = [{"n_estimators": n, "num_leaves": l, "min_child_samples": m}
            for n in (100, 200, 400) for l in (7, 15) for m in (20, 50)]


class Prep:
    """학습 구간 기준: 드문 범주(30건 미만) → 기타, 수치 1~99% 절단·중앙값 대체·결측 표시(로지스틱)."""
    def __init__(self, num):
        self.num = num

    def fit(self, tr):
        self.keep = {c: set(tr[c].value_counts()[lambda s: s >= 30].index) for c in CAT}
        X = self._base(tr)
        self.cats = {c: sorted(X[c].unique()) for c in CAT}
        self.lo, self.hi = X[self.num].quantile(0.01), X[self.num].quantile(0.99)
        self.med = X[self.num].clip(self.lo, self.hi, axis=1).median()
        self.miss = [c for c in self.num if X[c].isna().any()]
        Z = self._lr_raw(X)
        self.mu, self.sd = Z.mean(), Z.std().replace(0, 1)
        return self

    def _base(self, df):
        X = df[self.num].astype(float).copy()
        for c in CAT:
            X[c] = df[c].where(df[c].isin(self.keep[c]), "기타").fillna("기타").astype(str)
        return X

    def gbm(self, df):
        X = self._base(df)
        for c in CAT:
            X[c] = pd.Categorical(X[c], categories=self.cats[c])
        return X

    def _lr_raw(self, X):
        Z = X[self.num].clip(self.lo, self.hi, axis=1)
        na = Z[self.miss].isna().astype(float).add_suffix("_na")
        Z = Z.fillna(self.med)
        dums = [pd.get_dummies(pd.Categorical(X[c], categories=self.cats[c]), prefix=c, dtype=float).set_index(X.index) for c in CAT]
        return pd.concat([Z, na] + dums, axis=1)

    def lr(self, df):
        return (self._lr_raw(self._base(df)) - self.mu) / self.sd


def fit_predict(kind, params, tr, te, num):
    pr = Prep(num).fit(tr)
    if kind == "M1":
        m = LogisticRegression(C=params["C"], max_iter=5000)
        m.fit(pr.lr(tr), tr["yi"])
        p = m.predict_proba(pr.lr(te))
        cls = m.classes_
    else:
        m = lgb.LGBMClassifier(objective="multiclass", learning_rate=0.03, subsample=0.8, subsample_freq=1,
                               colsample_bytree=0.8, random_state=C.SEED, verbose=-1, deterministic=True, n_jobs=1, **params)
        m.fit(pr.gbm(tr), tr["yi"])
        p = m.predict_proba(pr.gbm(te))
        cls = m.classes_
    out = np.zeros((len(te), C.K))
    out[:, cls] = p
    return out


def tune(tr, num):
    a, b = tr[tr.close_year <= 2017], tr[tr.close_year.between(2018, 2019)]
    res = {}
    for kind, grid in (("M1", GRID_LR), ("M2", GRID_GBM)):
        sc = [(C.metrics(b["yi"].values, fit_predict(kind, g, a, b, num))["logloss"], g) for g in grid]
        best = min(sc, key=lambda s: s[0])
        res[kind] = {"params": best[1], "inner_logloss": best[0], "grid": [{"logloss": s, **g} for s, g in sc]}
    return res


def run_val():
    d, h = C.load()
    tr, va = d[d.split == "train"], d[d.split == "valid"].reset_index(drop=True)
    num = BASE_NUM + ADD_NUM
    tuned = tune(tr, num)
    yi = va["yi"].values
    preds = {"B1": C.b1(tr, va)}
    for k in ("M1", "M2"):
        preds[k] = fit_predict(k, tuned[k]["params"], tr, va, num)
    # 변수 묶음 기여(보고만): M2 기본 변수만, 같은 방식으로 조정
    tuned_base = tune(tr, BASE_NUM)
    preds["M2_base_only"] = fit_predict("M2", tuned_base["M2"]["params"], tr, va, BASE_NUM)
    best = min(("M1", "M2"), key=lambda k: C.metrics(yi, preds[k])["logloss"])
    res = {"cases_sha256": h, "n_train": len(tr), "n_valid": len(va),
           "metrics": {k: C.metrics(yi, p) for k, p in preds.items()},
           "by_year": {int(y): {k: C.metrics(yi[m], p[m]) for k, p in preds.items()}
                       for y in sorted(va.close_year.unique()) for m in [va.close_year.values == y]},
           "per_class": {k: C.per_class(yi, preds[k]) for k in ("B1", best)},
           "tuning": tuned, "tuning_base_only_M2": tuned_base["M2"], "best_model": best,
           "diff_best_vs_B1": C.boot_diff(va.uid.values, yi, preds[best], preds["B1"]),
           "diff_other_vs_B1": C.boot_diff(va.uid.values, yi, preds["M1" if best == "M2" else "M2"], preds["B1"]),
           "diff_M2_added_vs_base_only": C.boot_diff(va.uid.values, yi, preds["M2"], preds["M2_base_only"])}
    C.RES.mkdir(parents=True, exist_ok=True)
    (C.RES / "models_valid.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    sel = {"baseline": "B1", "model": best, "params": tuned[best]["params"], "features": num, "cases_sha256": h}
    (C.RES / "selection.json").write_text(json.dumps(sel, ensure_ascii=False, indent=1), encoding="utf-8")
    out = pd.DataFrame({k: list(map(list, np.round(p, 5))) for k, p in preds.items()})
    out.insert(0, "occupant_id", va.occupant_id.values)
    out.to_parquet(C.DATA / "pred_valid.parquet", index=False)
    for k, m in res["metrics"].items():
        print(k, {a: round(b, 4) for a, b in m.items()})
    for y, t in res["by_year"].items():
        print(y, {k: round(m["logloss"], 4) for k, m in t.items()})
    print("params", {k: v["params"] for k, v in tuned.items()}, "base_only", tuned_base["M2"]["params"])
    for k in ("diff_best_vs_B1", "diff_other_vs_B1", "diff_M2_added_vs_base_only"):
        print(k, {a: (np.round(b, 4).tolist() if isinstance(b, list) else round(b, 4)) for a, b in res[k].items()})
    print({c: (v["mean_pred"], v["obs_rate"], v["recall"]) for c, v in res["per_class"][best].items()})


def run_test():
    out_path = C.RES / "final_test.json"
    if out_path.exists():
        raise SystemExit("평가 결과가 이미 있습니다. 평가 구간은 한 번만 봅니다.")
    sel = json.loads((C.RES / "selection.json").read_text(encoding="utf-8"))
    d, h = C.load()
    if h != sel["cases_sha256"]:
        raise SystemExit("대상 표가 선택 당시와 다릅니다.")
    tr, te = d[d.split.isin(["train", "valid"])], d[d.split == "test"].reset_index(drop=True)
    yi = te["yi"].values
    pb = C.b1(tr, te)
    pm = fit_predict(sel["model"], sel["params"], tr, te, sel["features"])
    dif = C.boot_diff(te.uid.values, yi, pm, pb)
    res = {"selection": sel, "n_train": len(tr), "n_test": len(te),
           "metrics": {"B1": C.metrics(yi, pb), sel["model"]: C.metrics(yi, pm)},
           "diff": dif,
           "adopted": bool(dif["logloss_ci"][1] < 0 and dif["accuracy_diff"] >= 0.02),
           "per_class": {"B1": C.per_class(yi, pb), sel["model"]: C.per_class(yi, pm)},
           "confusion": {"rows_actual_cols_pred": C.CLASSES,
                         "B1": pd.crosstab(yi, pb.argmax(1)).reindex(index=range(C.K), columns=range(C.K), fill_value=0).values.tolist(),
                         sel["model"]: pd.crosstab(yi, pm.argmax(1)).reindex(index=range(C.K), columns=range(C.K), fill_value=0).values.tolist()}}
    groups = {"prev_group": te["prev_group"], "gu": te["f_gu"], "floor": te["floor_class"], "close_year": te["close_year"]}
    res["errors"] = {g: {str(k): {"n": int(m.sum()), "B1": C.metrics(yi[m], pb[m]), "model": C.metrics(yi[m], pm[m])}
                         for k in sorted(s.dropna().unique()) for m in [(s == k).values] if m.sum() >= 30}
                     for g, s in groups.items()}
    ll = -np.log(np.clip(pm[np.arange(len(yi)), yi], 1e-9, 1))
    top = np.argsort(-ll)[:20]
    res["largest_errors"] = [{"occupant_id": int(te.occupant_id[i]), "prev": te.prev_group[i], "service": te.service[i],
                              "category": te.category[i], "actual": C.CLASSES[yi[i]], "pred": C.CLASSES[pm[i].argmax()],
                              "p_actual": round(float(pm[i, yi[i]]), 3), "p_pred": round(float(pm[i].max()), 3),
                              "b1_p_actual": round(float(pb[i, yi[i]]), 3), "gu": te.f_gu[i], "floor": te.floor_class[i]}
                             for i in top]
    out_path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    pd.DataFrame({"occupant_id": te.occupant_id, "yi": yi, **{f"B1_{c}": pb[:, k] for k, c in enumerate(C.KEYS)},
                  **{f"M_{c}": pm[:, k] for k, c in enumerate(C.KEYS)}}).to_parquet(C.DATA / "pred_test.parquet", index=False)
    for k, m in res["metrics"].items():
        print(k, {a: round(b, 4) for a, b in m.items()})
    print("diff", res["diff"], "adopted", res["adopted"])


if __name__ == "__main__":
    {"val": run_val, "test": run_test}[sys.argv[1] if len(sys.argv) > 1 else "val"]()
