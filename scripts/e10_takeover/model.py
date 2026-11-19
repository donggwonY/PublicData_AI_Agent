"""E-10 3~4단계: 모델 M1(로지스틱)·M2(LightGBM) 조정·검증, 평가 1회 (계획 docs/e10/plan.md §3·§4).

실행(저장소 루트, 실험 환경):
  C:/claude_workspace/e06_env/Scripts/python scripts/e10_takeover/model.py val   # 학습 안 시간 분할 조정 + 검증 비교, 선택 저장
  C:/claude_workspace/e06_env/Scripts/python scripts/e10_takeover/model.py test  # 평가 1회(선택 파일 필요, 결과 파일이 있으면 중단)
입력: C:/claude_workspace/e10_data/cases.parquet (build.py)
출력: docs/e10/results/{models_valid,selection,final_test}.json, 예측은 C:/claude_workspace/e10_data/pred_*.csv
"""
import json
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

import common as C

NUM = ["s_area_m2", "p_area_m2", "area_ratio", "p_tenure_years", "gap_days", "overlap", "same_category", "p_n_licenses",
       "open_month", "covid_open",
       "h_n_occ", "h_n_closed", "h_n_turnover", "h_mean_gap_days", "h_years_since_first", "h_n_groups",
       "o_nb_active", "o_nb_active_same", "o_nb_open_12m", "o_nb_close_12m", "o_nb_net_12m", "o_nb_net_same_12m",
       "o_nb_vacant", "o_nb_vacancy_rate", "o_dong_vacancy_rate", "o_dong_live_change_3y",
       "o_sub_dist_m", "o_sub_board_12m", "o_sub_board_yoy",
       "o_pop", "o_pop_2039_share", "o_pop_60plus_share", "o_pop_change_12m", "o_pop_is_dong"]
CAT = ["svc", "s_cat", "p_cat", "s_floor_class", "gu"]
GRID_LR = [{"C": c} for c in (0.01, 0.1, 1.0, 10.0)]
GRID_GBM = [{"n_estimators": n, "num_leaves": l, "min_child_samples": m}
            for n in (150, 300, 600) for l in (7, 15) for m in (20, 50)]


class Prep:
    """학습 구간 기준 전처리: 드문 범주(30건 미만) → 묶음/기타, 수치 1~99% 절단·중앙값 대체·결측 표시(로지스틱용)."""

    def fit(self, tr):
        self.keep = {}
        for c, src in (("svc", "service"), ("s_cat", "s_category"), ("p_cat", "category")):
            vc = tr[src].value_counts()
            self.keep[c] = set(vc[vc >= C.MIN_N].index)
        X = self._base(tr)
        self.cats = {c: sorted(X[c].dropna().unique()) for c in CAT}
        self.lo, self.hi = X[NUM].quantile(0.01), X[NUM].quantile(0.99)
        self.med = X[NUM].clip(self.lo, self.hi, axis=1).median()
        self.miss_cols = [c for c in NUM if X[c].isna().any()]
        Z = self._lr_raw(X)
        self.mu, self.sd = Z.mean(), Z.std().replace(0, 1)
        return self

    def _base(self, df):
        X = df[NUM].astype(float).copy()
        X["svc"] = df["service"].where(df["service"].isin(self.keep["svc"]), "묶음:" + df["group11"])
        X["s_cat"] = df["s_category"].where(df["s_category"].isin(self.keep["s_cat"]), "기타")
        X["p_cat"] = df["category"].where(df["category"].isin(self.keep["p_cat"]), "기타")
        X["s_floor_class"] = df["s_floor_class"]
        X["gu"] = df["gu"].fillna("미상")
        return X

    def gbm(self, df):
        X = self._base(df)
        for c in CAT:
            X[c] = pd.Categorical(X[c], categories=self.cats[c])
        return X

    def _lr_raw(self, X):
        Z = X[NUM].clip(self.lo, self.hi, axis=1)
        miss = Z[self.miss_cols].isna().astype(float).add_suffix("_na")
        Z = Z.fillna(self.med)
        dums = [pd.get_dummies(pd.Categorical(X[c], categories=self.cats[c]), prefix=c, dtype=float).set_index(X.index)
                for c in CAT]
        return pd.concat([Z, miss] + dums, axis=1)

    def lr(self, df):
        return (self._lr_raw(self._base(df)) - self.mu) / self.sd


def fit_predict(kind, params, tr, te, return_model=False):
    pr = Prep().fit(tr)
    if kind == "M1":
        m = LogisticRegression(C=params["C"], max_iter=5000)
        m.fit(pr.lr(tr), tr["y"])
        p = m.predict_proba(pr.lr(te))[:, 1]
    else:
        m = lgb.LGBMClassifier(learning_rate=0.03, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                               random_state=C.SEED, verbose=-1, deterministic=True, n_jobs=1, **params)
        m.fit(pr.gbm(tr), tr["y"])
        p = m.predict_proba(pr.gbm(te))[:, 1]
    return (p, m, pr) if return_model else p


def tune(tr_all):
    """학습 구간 안 시간 분할: 개업 2012(2011 포함)~2016 학습 → 2017~2018 확인, Brier 최소 설정."""
    a, b = tr_all[tr_all.open_year <= 2016], tr_all[tr_all.open_year.between(2017, 2018)]
    out = {"inner_n": [len(a), len(b)]}
    for kind, grid in (("M1", GRID_LR), ("M2", GRID_GBM)):
        scores = [(C.metrics(b.y.values, fit_predict(kind, g, a, b))["brier"], g) for g in grid]
        best = min(scores, key=lambda s: s[0])
        out[kind] = {"params": best[1], "inner_brier": best[0], "grid": [{"brier": s, **g} for s, g in scores]}
    out["inner_baseline_brier"] = {"B1": C.metrics(b.y.values, C.b1(a, b))["brier"],
                                   "B2": C.metrics(b.y.values, C.b2(a, b))["brier"]}
    return out


def importance(tr, sel):
    kind, params = sel["best_model"], sel["params"][sel["best_model"]]
    _, m, pr = fit_predict(kind, params, tr, tr.iloc[:5], return_model=True)
    if kind == "M2":
        imp = pd.Series(m.booster_.feature_importance("gain"), index=pr.gbm(tr.iloc[:5]).columns)
    else:
        imp = pd.Series(np.abs(m.coef_[0]), index=pr.lr(tr.iloc[:5]).columns)
    imp = imp / imp.sum()
    return {k: round(float(v), 4) for k, v in imp.sort_values(ascending=False).head(15).items()}


def run_val():
    d, sha = C.load()
    tr, va = d[d.split == "train"].copy(), d[d.split == "valid"].copy()
    del d                                     # 평가 구간은 쓰지 않음
    tuned = tune(tr)
    va["B1"], va["B2"] = C.b1(tr, va), C.b2(tr, va)
    for k in ("M1", "M2"):
        va[k] = fit_predict(k, tuned[k]["params"], tr, va)
    cols = ["B1", "B2", "M1", "M2"]
    y = va.y.values
    tbl = {c: C.metrics(y, va[c].values) for c in cols}
    best_b = min(("B1", "B2"), key=lambda c: tbl[c]["brier"])
    best_m = min(("M1", "M2"), key=lambda c: tbl[c]["brier"])
    other = "M1" if best_m == "M2" else "M2"
    svc = va.service.where(va.service.isin(["일반음식점", "담배소매업", "휴게음식점", "미용업", "즉석판매제조가공업"]), "그 밖")
    res = {"input_sha256": sha, "n_train": len(tr), "n_valid": len(va), "metrics": tbl,
           "best_baseline": best_b, "best_model": best_m, "tuning": tuned,
           "diff_model_vs_baseline": C.boot_diff(va, best_m, best_b),
           "diff_other_model_vs_baseline": C.boot_diff(va, other, best_b),
           "calibration": {c: C.calib(y, va[c].values) for c in (best_b, best_m)},
           "by_service": C.by_group(va.assign(svc=svc), "svc", [best_b, best_m]),
           "by_tenure_band": C.by_group(va, "p_tenure_band", [best_b, best_m])}
    sel = {"input_sha256": sha, "best_baseline": best_b, "best_model": best_m,
           "params": {k: tuned[k]["params"] for k in ("M1", "M2")}, "fixed": "2026-11-19 3단계, 평가 구간 미사용"}
    sel["importance_train_fit"] = importance(tr, sel)
    res["importance_train_fit"] = sel["importance_train_fit"]
    va[["uid", "s_occupant_id", "open_year", "service", "p_tenure_band", "y"] + cols].to_csv(C.DATA / "pred_valid.csv", index=False)
    (C.RES / "models_valid.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (C.RES / "selection.json").write_text(json.dumps(sel, ensure_ascii=False, indent=1), encoding="utf-8")
    print(pd.DataFrame(tbl).T.round(4).to_string())
    print("조정:", {k: (tuned[k]["params"], round(tuned[k]["inner_brier"], 4)) for k in ("M1", "M2")},
          "내부 기준선", {k: round(v, 4) for k, v in tuned["inner_baseline_brier"].items()})
    print("선택:", best_b, best_m)
    print("차이(후보 − 기준선):", json.dumps(res["diff_model_vs_baseline"]))
    print("차이(다른 모델 − 기준선):", json.dumps(res["diff_other_model_vs_baseline"]))
    print(json.dumps(res["by_service"], ensure_ascii=False))
    print(json.dumps(res["by_tenure_band"], ensure_ascii=False))
    print(json.dumps(res["calibration"], ensure_ascii=False))
    print(json.dumps(res["importance_train_fit"], ensure_ascii=False))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "val"
    if mode == "val":
        run_val()
    else:
        raise SystemExit("test 모드는 4단계에서 추가합니다.")


if __name__ == "__main__":
    main()
