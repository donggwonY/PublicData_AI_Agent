"""E-08 2~4단계: 기준선 B0~B2, 모델 M1(로지스틱)·M2(LightGBM) (계획 docs/e08/plan.md §4~6).

실행(저장소 루트, 실험 환경):
  C:/claude_workspace/e06_env/Scripts/python scripts/e08_franchise/model.py val    # 조정(학습 안 분할) + 검증 비교, 선택 저장
  C:/claude_workspace/e06_env/Scripts/python scripts/e08_franchise/model.py test   # 시험 1회(선택 파일 필요, 결과 파일이 있으면 중단)
입력: C:/claude_workspace/e08_data/panel.parquet (panel.py)
출력: docs/e08/results/{val,selection,test}.json, 예측은 C:/claude_workspace/e08_data/pred_*.csv
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, log_loss

ROOT = Path(__file__).resolve().parents[2]
DATA = Path("C:/claude_workspace/e08_data")
RES = ROOT / "docs/e08/results"
SEED, BOOT = 20261119, 1000
NUM = ["dg_frcs_log", "dg_dms", "dg_prev_missing", "dg_chg", "dg_chg_rate", "nat_chg_rate", "dg_share", "nat_frcs_log",
       "n_sido", "new_rate", "end_rate", "cancel_rate", "namechg_rate", "sales_log", "sales_area_log", "sales_chg_rate",
       "stats_unlinked", "brand_age", "hq_brands", "induty_prev_decline"]
CAT = ["induty_l", "induty_mg"]
GRID_LR = [{"C": c} for c in (0.01, 0.1, 1.0, 10.0)]
GRID_GBM = [{"n_estimators": n, "num_leaves": l, "min_child_samples": m}
            for n in (150, 300, 600) for l in (7, 15) for m in (20, 50)]


def load(target: str = "y"):
    p = pd.read_parquet(DATA / "panel.parquet")
    if target == "y":
        p = p[p["status"] != "absent"].copy()
    p["target"] = p[target]
    return p


# ---------- 기준선 ----------
def direction(df):
    prev = np.exp(df["dg_frcs_log"]) - 1 - df["dg_chg"]
    d = np.where(df["dg_chg"].isna(), "unknown",
                 np.where(prev.round() <= 0, "new", np.where(df["dg_chg"] < 0, "dec", np.where(df["dg_chg"] > 0, "inc", "same"))))
    return pd.Series(d, index=df.index)


def fit_baselines(tr):
    overall = tr["target"].mean()
    b1 = tr.groupby(direction(tr))["target"].mean()
    mid = tr.groupby("induty_m")["target"].agg(["mean", "size"])
    lcl = tr.groupby("induty_l")["target"].agg(["mean", "size"])
    return {"overall": overall, "b1": b1, "mid": mid[mid["size"] >= 30]["mean"], "lcl": lcl[lcl["size"] >= 30]["mean"]}


def predict_baselines(b, df):
    out = pd.DataFrame(index=df.index)
    out["B0"] = b["overall"]
    out["B1"] = direction(df).map(b["b1"]).fillna(b["overall"])
    out["B2"] = df["induty_m"].map(b["mid"]).fillna(df["induty_l"].map(b["lcl"])).fillna(b["overall"])
    return out


# ---------- 모델 ----------
class Prep:
    """학습 구간 기준 전처리: 드문 중분류(30건 미만) → 기타, 수치 1~99% 절단·중앙값 대체·결측 표시(로지스틱용)."""
    def fit(self, tr):
        vc = tr["induty_m"].value_counts()
        self.keep_m = set(vc[vc >= 30].index)
        self.cats = {}
        X = self._base(tr)
        self.cats = {c: sorted(X[c].dropna().unique()) for c in CAT}
        self.lo, self.hi = X[NUM].quantile(0.01), X[NUM].quantile(0.99)
        self.med = X[NUM].clip(self.lo, self.hi, axis=1).median()
        self.miss_cols = [c for c in NUM if X[c].isna().any()]
        Z = self._lr_raw(X)
        self.mu, self.sd = Z.mean(), Z.std().replace(0, 1)
        return self

    def _base(self, df):
        X = df[NUM + ["induty_l"]].copy()
        X["induty_mg"] = df["induty_m"].where(df["induty_m"].isin(self.keep_m), "기타")
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


def fit_predict(kind, params, tr, te):
    pr = Prep().fit(tr)
    if kind == "M1":
        m = LogisticRegression(C=params["C"], max_iter=5000)
        m.fit(pr.lr(tr), tr["target"])
        return m.predict_proba(pr.lr(te))[:, 1]
    m = lgb.LGBMClassifier(learning_rate=0.03, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                           random_state=SEED, verbose=-1, deterministic=True, n_jobs=1, **params)
    m.fit(pr.gbm(tr), tr["target"])
    return m.predict_proba(pr.gbm(te))[:, 1]


# ---------- 평가 ----------
def metrics(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return {"brier": float(np.mean((p - y) ** 2)), "auc": float(roc_auc_score(y, p)) if len(set(y)) > 1 else None,
            "logloss": float(log_loss(y, p, labels=[0, 1]))}


def boot_diff(df, a, b):
    """브랜드 단위 부트스트랩: (a − b)의 Brier·AUC 차이 95% 구간."""
    rng = np.random.default_rng(SEED)
    brands = df["brandMnno"].unique()
    idx = df.groupby("brandMnno").indices
    db, da = [], []
    for _ in range(BOOT):
        rows = np.concatenate([idx[x] for x in rng.choice(brands, len(brands))])
        y, pa, pb = df["target"].values[rows], df[a].values[rows], df[b].values[rows]
        db.append(np.mean((pa - y) ** 2) - np.mean((pb - y) ** 2))
        if len(set(y)) > 1:
            da.append(roc_auc_score(y, pa) - roc_auc_score(y, pb))
    q = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
    full = metrics(df["target"].values, df[a].values), metrics(df["target"].values, df[b].values)
    return {"brier_diff": full[0]["brier"] - full[1]["brier"], "brier_ci": q(db),
            "auc_diff": full[0]["auc"] - full[1]["auc"], "auc_ci": q(da)}


def calib(y, p, bins=10):
    q = pd.qcut(p, bins, labels=False, duplicates="drop")
    g = pd.DataFrame({"y": y, "p": p, "q": q}).groupby("q")
    return [{"n": int(len(x)), "pred": round(float(x["p"].mean()), 4), "obs": round(float(x["y"].mean()), 4)} for _, x in g]


def table(df, cols):
    y = df["target"].values
    return {c: metrics(y, df[c].values) for c in cols}


def tune(tr_all):
    """학습 구간 안 시간 분할: 2017~2020 학습 → 2021~2022 확인, Brier 최소 설정."""
    a, b = tr_all[tr_all["N"] <= 2020], tr_all[tr_all["N"].between(2021, 2022)]
    out = {}
    for kind, grid in (("M1", GRID_LR), ("M2", GRID_GBM)):
        scores = [(metrics(b["target"].values, fit_predict(kind, g, a, b))["brier"], g) for g in grid]
        best = min(scores, key=lambda s: s[0])
        out[kind] = {"params": best[1], "inner_brier": best[0], "grid": [{"brier": s, **g} for s, g in scores]}
    return out


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_val(target="y"):
    p = load(target)
    tr, va = p[p["N"] <= 2022], p[p["N"].between(2023, 2024)].copy()
    tuned = tune(tr)
    b = fit_baselines(tr)
    va = va.join(predict_baselines(b, va))
    for k in ("M1", "M2"):
        va[k] = fit_predict(k, tuned[k]["params"], tr, va)
    cols = ["B0", "B1", "B2", "M1", "M2"]
    res = {"target": target, "n_train": len(tr), "n_val": len(va), "pos_val": int(va["target"].sum()),
           "metrics": table(va, cols), "by_year": {int(n): table(g, cols) for n, g in va.groupby("N")}}
    best_b = min(("B1", "B2"), key=lambda c: res["metrics"][c]["brier"])
    best_m = min(("M1", "M2"), key=lambda c: res["metrics"][c]["brier"])
    res.update({"best_baseline": best_b, "best_model": best_m, "tuning": tuned,
                "diff_model_vs_baseline": boot_diff(va, best_m, best_b),
                "diff_other_model_vs_baseline": boot_diff(va, "M1" if best_m == "M2" else "M2", best_b),
                "calibration": {c: calib(va["target"].values, va[c].values) for c in (best_b, best_m)},
                "panel_sha256": sha(DATA / "panel.parquet")})
    va[["brandMnno", "N", "target"] + cols].to_csv(DATA / f"pred_val_{target}.csv", index=False)
    return res, va


def errors(df, col):
    """오류 분석 묶음별 지표."""
    d = df.assign(size=pd.cut(np.expm1(df["dg_frcs_log"]).round(), [2, 4, 9, 29, np.inf], labels=["3~4", "5~9", "10~29", "30+"]),
                  age=pd.cut(df["brand_age"], [-1, 3, 7, 15, np.inf], labels=["0~3", "4~7", "8~15", "16+"]),
                  linked=np.where(df["stats_unlinked"] == 1, "unlinked", "linked"))
    out = {}
    for g in ("induty_l", "size", "age", "linked"):
        out[g] = {str(k): {"n": int(len(x)), "pos": int(x["target"].sum()),
                           **{c: metrics(x["target"].values, x[c].values) for c in (col, "B1", "B2")}}
                  for k, x in d.groupby(g, observed=True) if len(x) >= 20}
    return out


def run_test():
    sel_path = RES / "selection.json"
    out_path = RES / "test.json"
    if out_path.exists():
        raise SystemExit("시험 결과가 이미 있습니다. 시험 구간은 한 번만 봅니다.")
    sel = json.loads(sel_path.read_text(encoding="utf-8"))
    res = {"selection": sel, "panel_sha256": sha(DATA / "panel.parquet")}
    if res["panel_sha256"] != sel["panel_sha256"]:
        raise SystemExit("패널이 선택 당시와 다릅니다.")
    for target in ("y", "y_absent_as_decline"):
        p = load(target)
        tr, te = p[p["N"] <= 2024], p[p["N"] == 2025].copy()
        b = fit_baselines(tr)
        te = te.join(predict_baselines(b, te))
        m = sel["best_model"]
        te[m] = fit_predict(m, sel["params"][m], tr, te)
        cols = ["B0", "B1", "B2", m]
        r = {"n_train": len(tr), "n_test": len(te), "pos_test": int(te["target"].sum()),
             "metrics": table(te, cols), "diff": boot_diff(te, m, sel["best_baseline"]),
             "diff_vs_other_baseline": boot_diff(te, m, "B2" if sel["best_baseline"] == "B1" else "B1"),
             "calibration": {c: calib(te["target"].values, te[c].values) for c in (sel["best_baseline"], m)}}
        if target == "y":
            d = r["diff"]
            r["adopted"] = bool(d["brier_ci"][1] < 0 and d["auc_diff"] >= 0.02)
            r["errors"] = errors(te, m)
            te["err"] = (te[m] - te["target"]).abs()
            r["largest_errors"] = te.nlargest(20, "err")[["brandMnno", "N", "target", m, "B1", "B2"]].round(3).to_dict("records")
        te[["brandMnno", "N", "target"] + cols].to_csv(DATA / f"pred_test_{target}.csv", index=False)
        res[target] = r
    out_path.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return res


def main():
    RES.mkdir(parents=True, exist_ok=True)
    mode = sys.argv[1] if len(sys.argv) > 1 else "val"
    if mode == "val":
        res, _ = run_val("y")
        sens, _ = run_val("y_absent_as_decline")
        res["sensitivity_absent_as_decline"] = {k: sens[k] for k in ("n_val", "pos_val", "metrics", "best_baseline", "best_model", "diff_model_vs_baseline")}
        (RES / "val.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
        sel = {"best_baseline": res["best_baseline"], "best_model": res["best_model"],
               "params": {k: res["tuning"][k]["params"] for k in ("M1", "M2")}, "panel_sha256": res["panel_sha256"]}
        (RES / "selection.json").write_text(json.dumps(sel, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({k: res[k] for k in ("n_train", "n_val", "pos_val", "metrics", "best_baseline", "best_model",
                                              "diff_model_vs_baseline", "diff_other_model_vs_baseline")}, ensure_ascii=False, indent=1))
        print("params", sel["params"])
        print("sens", json.dumps(res["sensitivity_absent_as_decline"]["metrics"], indent=0)[:800])
    elif mode == "test":
        res = run_test()
        r = res["y"]
        print(json.dumps({k: r[k] for k in ("n_test", "pos_test", "metrics", "diff", "diff_vs_other_baseline", "adopted")}, ensure_ascii=False, indent=1))
        print("sens", json.dumps({k: res["y_absent_as_decline"][k] for k in ("n_test", "metrics", "diff")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
