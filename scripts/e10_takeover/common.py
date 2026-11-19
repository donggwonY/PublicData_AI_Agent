"""E-10 공통: 사례 표 읽기, 기준선 B1·B2, 이진 지표·자리 단위 부트스트랩 (계획 docs/e10/plan.md §3·§4)."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss, roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/e05_vacancy"))
import asof as A  # noqa: E402

DATA = Path("C:/claude_workspace/e10_data")
RES = ROOT / "docs/e10/results"
SEED, BOOT = 20261119, 1000
MIN_N = 30


def load():
    path = DATA / "cases.parquet"
    meta = json.loads((DATA / "cases_meta.json").read_text(encoding="utf-8"))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if sha != meta["sha256"]:
        raise SystemExit("cases.parquet 해시가 기록과 다릅니다.")
    d = pd.read_parquet(path).reset_index(drop=True)
    d["group11"] = d.service.map(A.GROUP)
    return d, sha


# ---------- 기준선 ----------
def b1(tr, te):
    """업종(인허가) 평균. 학습 표본 30건 미만 업종은 묶음(11개) 평균, 그것도 30건 미만이면 전체 평균."""
    overall = tr.y.mean()
    s = tr.groupby("service").y.agg(["mean", "size"])
    g = tr.groupby("group11").y.agg(["mean", "size"])
    out = []
    for sv, gr in zip(te.service, te.group11):
        if sv in s.index and s.at[sv, "size"] >= MIN_N:
            out.append(s.at[sv, "mean"])
        elif gr in g.index and g.at[gr, "size"] >= MIN_N:
            out.append(g.at[gr, "mean"])
        else:
            out.append(overall)
    return np.array(out, float)


def b2(tr, te):
    """업종 × 직전 가게 영업 기간 구간. 칸 표본 n < 30이면 B1과 섞는다(가중 n/30)."""
    p1 = b1(tr, te)
    c = tr.groupby(["service", "p_tenure_band"]).y.agg(["mean", "size"])
    out = np.empty(len(te))
    for i, (sv, bd) in enumerate(zip(te.service, te.p_tenure_band)):
        if (sv, bd) in c.index:
            m, n = c.loc[(sv, bd)]
            w = min(n / MIN_N, 1.0)
            out[i] = w * m + (1 - w) * p1[i]
        else:
            out[i] = p1[i]
    return out


# ---------- 평가 ----------
def metrics(y, p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return {"n": int(len(y)), "brier": float(np.mean((p - y) ** 2)),
            "auc": float(roc_auc_score(y, p)) if len(set(y)) > 1 else None,
            "logloss": float(log_loss(y, p, labels=[0, 1])), "mean_pred": float(p.mean()), "obs_rate": float(np.mean(y))}


def boot_diff(df, a, b):
    """자리(uid) 단위 부트스트랩: (a − b)의 Brier·AUC 차이 95% 구간."""
    rng = np.random.default_rng(SEED)
    idx = df.groupby("uid").indices
    keys = np.array(list(idx))
    y_all, pa_all, pb_all = df["y"].values, df[a].values, df[b].values
    db, da = [], []
    for _ in range(BOOT):
        rows = np.concatenate([idx[k] for k in rng.choice(keys, len(keys))])
        y, pa, pb = y_all[rows], pa_all[rows], pb_all[rows]
        db.append(np.mean((pa - y) ** 2) - np.mean((pb - y) ** 2))
        if len(set(y)) > 1:
            da.append(roc_auc_score(y, pa) - roc_auc_score(y, pb))
    q = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
    ma, mb = metrics(y_all, pa_all), metrics(y_all, pb_all)
    return {"a": a, "b": b, "brier_diff": ma["brier"] - mb["brier"], "brier_ci": q(db),
            "auc_diff": ma["auc"] - mb["auc"], "auc_ci": q(da)}


def calib(y, p, bins=10):
    q = pd.qcut(p, bins, labels=False, duplicates="drop")
    g = pd.DataFrame({"y": y, "p": p, "q": q}).groupby("q")
    return [{"n": int(len(x)), "pred": round(float(x["p"].mean()), 4), "obs": round(float(x["y"].mean()), 4)} for _, x in g]


def by_group(df, col, cols):
    out = {}
    for k, g in df.groupby(col, observed=True):
        out[str(k)] = {"n": int(len(g)), "obs": round(float(g.y.mean()), 3),
                       **{c: {"pred": round(float(g[c].mean()), 3),
                              "brier": round(float(np.mean((g[c] - g.y) ** 2)), 4)} for c in cols}}
    return out
