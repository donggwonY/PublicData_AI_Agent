"""E-09 공통: 대상 표 읽기, 기준선 B0~B3, 다중 분류 지표·자리 단위 부트스트랩 (계획 docs/e09/plan.md §3·§5)."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path("C:/claude_workspace/e09_data")
ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "docs/e09/results"
CLASSES = ["음식점", "카페·제과", "미용·이용", "식품판매", "담배", "오락", "기타"]
KEYS = [c.replace("·", "_") for c in CLASSES]
K = len(CLASSES)
SEED, BOOT = 20261119, 1000
RECENT_DAYS, RECENT_MIN = 3 * 365, 30
B3_PRIOR = 5.0


def load():
    path = DATA / "cases.parquet"
    meta = json.loads((DATA / "cases_meta.json").read_text(encoding="utf-8"))
    if hashlib.sha256(path.read_bytes()).hexdigest() != meta["sha256"]:
        raise SystemExit("cases.parquet 해시가 기록과 다릅니다.")
    d = pd.read_parquet(path).reset_index(drop=True)
    d["yi"] = d["y"].map(CLASSES.index)
    return d, meta["sha256"]


def onehot(yi):
    return np.eye(K)[yi]


# ---------- 기준선 ----------
def b0(tr, n):
    p = np.bincount(tr["yi"], minlength=K) / len(tr)
    return np.tile(p, (n, 1))


def transition(tr):
    t = pd.crosstab(tr["prev7"], tr["yi"]).reindex(columns=range(K), fill_value=0)
    return t.div(t.sum(1), axis=0)


def b1(tr, te):
    T = transition(tr)
    base = b0(tr, 1)[0]
    return np.vstack([T.loc[g].values if g in T.index else base for g in te["prev7"]])


def b2(pool, tr, te):
    """최근 3년 이동표: t0 이전 3년 안에 폐업하고 t0 이전에 다음 가게가 들어온 사례(pool, 분할 무관)로 만든 직전 묶음별 비율.
    표본 n < 30이면 B1(학습 이동표)과 섞는다(가중 n/30)."""
    p1 = b1(tr, te)
    out = np.empty_like(p1)
    pt0 = pool["t0"].values.astype("datetime64[D]")
    pnx = pool["next_ld"].values.astype("datetime64[D]")
    pg = pool["prev7"].values
    py = pool["yi"].values
    for i, (t0, g) in enumerate(zip(te["t0"].values.astype("datetime64[D]"), te["prev7"].values)):
        m = (pg == g) & (pt0 < t0) & (pt0 >= t0 - np.timedelta64(RECENT_DAYS, "D")) & (pnx < t0)
        n = int(m.sum())
        if n == 0:
            out[i] = p1[i]
            continue
        rec = np.bincount(py[m], minlength=K) / n
        w = min(n / RECENT_MIN, 1.0)
        out[i] = w * rec + (1 - w) * p1[i]
    return out


def b3(tr, te):
    """반경 약 300m 최근 1년 개업 묶음 비중 + 학습 분포 가상 표본 5건(가법 평활). 개업 0건·좌표 없음은 학습 분포."""
    prior = b0(tr, 1)[0]
    share = te[[f"nb_open12_share_{k}" for k in KEYS]].values
    tot = te["nb_open12_total"].values
    cnt = np.nan_to_num(share * tot[:, None])
    tot = np.nan_to_num(tot)
    return (cnt + B3_PRIOR * prior) / (tot[:, None] + B3_PRIOR)


# ---------- 지표 ----------
def metrics(yi, p):
    p = np.clip(p, 1e-9, 1)
    p = p / p.sum(1, keepdims=True)
    n = len(yi)
    top = np.argsort(-p, axis=1)
    return {"logloss": float(-np.mean(np.log(p[np.arange(n), yi]))),
            "brier": float(np.mean(((p - onehot(yi)) ** 2).sum(1))),
            "accuracy": float(np.mean(top[:, 0] == yi)),
            "top2": float(np.mean((top[:, 0] == yi) | (top[:, 1] == yi)))}


def per_class(yi, p):
    pred = p.argmax(1)
    return {CLASSES[k]: {"n": int((yi == k).sum()), "mean_pred": round(float(p[:, k].mean()), 4),
                         "obs_rate": round(float((yi == k).mean()), 4),
                         "recall": None if (yi == k).sum() == 0 else round(float((pred[yi == k] == k).mean()), 4),
                         "predicted_n": int((pred == k).sum())} for k in range(K)}


def boot_diff(uid, yi, pa, pb):
    """자리(uid) 단위 부트스트랩: a − b 의 로그 손실·정확도 차이 95% 구간."""
    rng = np.random.default_rng(SEED)
    idx = pd.Series(np.arange(len(uid))).groupby(np.asarray(uid)).indices
    units = list(idx)
    la = -np.log(np.clip(pa[np.arange(len(yi)), yi], 1e-9, 1))
    lb = -np.log(np.clip(pb[np.arange(len(yi)), yi], 1e-9, 1))
    aa, ab = pa.argmax(1) == yi, pb.argmax(1) == yi
    dl, dacc = [], []
    for _ in range(BOOT):
        rows = np.concatenate([idx[units[j]] for j in rng.integers(0, len(units), len(units))])
        dl.append(la[rows].mean() - lb[rows].mean())
        dacc.append(aa[rows].mean() - ab[rows].mean())
    q = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
    return {"logloss_diff": float(la.mean() - lb.mean()), "logloss_ci": q(dl),
            "accuracy_diff": float(aa.mean() - ab.mean()), "accuracy_ci": q(dacc)}
