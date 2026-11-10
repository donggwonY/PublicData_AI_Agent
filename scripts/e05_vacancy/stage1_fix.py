"""1단계 재평가: 대상 = 폐업 시점에 다음 인허가가 아직 없는 사례. 계획 models_plan.md 변경 기록(2026-11-09)."""
import json, os, sys, warnings
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as E5P
import mlib as L
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss, log_loss
import lightgbm as lgb

VF = E5P.VF
X = pd.read_parquet(os.path.join(VF, 'asof_episodes.parquet'))


def s1(years, end):
    d = L.stage1(L.split(X, years, end))
    keep = d.next_ld.isna() | (d.next_ld > d.t0)          # 폐업 시점에 아직 다음 인허가 없음
    return d[keep].copy(), int((~keep).sum())


(itr, x1), (iva, x2), (tr, x3), (va, x4) = s1((2012, 2017), '2019-12-31'), s1((2018, 2019), '2021-12-31'), \
    s1((2012, 2019), '2021-12-31'), s1((2020, 2021), '2023-12-31')
NUM1 = L.numeric_cols('s1')


def gap_bin(v):
    return np.select([v.isna(), v <= 90, v <= 365], ['이력없음', '90일이하', '90일~1년'], '1년초과')


def base(dtr, dte):
    p0 = dtr.y.mean()
    cell = lambda d: d.f_gu.fillna('?') + '|' + d.prev_group
    g = dtr.groupby(cell(dtr)).y.agg(['mean', 'size']); g = g[g['size'] >= L.MIN_N]['mean']
    gr = dtr.groupby('prev_group').y.mean()
    b2 = dtr.groupby(gap_bin(dtr.h_mean_gap_days)).y.agg(['mean', 'size']); b2 = b2[b2['size'] >= L.MIN_N]['mean']
    return {'B0': np.full(len(dte), p0),
            'B1': cell(dte).map(g).fillna(dte.prev_group.map(gr)).fillna(p0).to_numpy(),
            'B2': pd.Series(gap_bin(dte.h_mean_gap_days)).map(b2).fillna(p0).to_numpy()}


def fit(kind, p, dtr, dte):
    pr = L.Prep(NUM1, kind == 'logit').fit(dtr); A, B = pr.transform(dtr), pr.transform(dte)
    if kind == 'logit':
        m = LogisticRegression(C=p['C'], max_iter=3000).fit(A, dtr.y)
    else:
        m = lgb.LGBMClassifier(num_leaves=p['leaves'], n_estimators=p['trees'], learning_rate=0.05, min_child_samples=100,
                               subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=0, verbose=-1).fit(A, dtr.y)
    return m.predict_proba(B)[:, 1], m, pr


def met(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    auc = roc_auc_score(y, p) if np.ptp(p) > 0 else 0.5
    return {'auc': float(auc), 'pr_auc': float(average_precision_score(y, p)), 'brier': float(brier_score_loss(y, p)),
            'log_loss': float(log_loss(y, p))}


res = {'definition': '폐업 시점에 다음 인허가가 아직 없는 사례(다음 인허가일 > 폐업일 또는 없음)',
       'excluded_pre_registered': {'tune_train': x1, 'tune_valid': x2, 'train': x3, 'valid': x4},
       'n': {k: {'n': len(d), 'pos': int(d.y.sum())} for k, d in
             (('tune_train', itr), ('tune_valid', iva), ('train', tr), ('valid', va))},
       'tuning': {}, 'chosen': {}}
GRID = {'logit': [{'C': c} for c in (0.01, 0.1, 1)], 'lgbm': [{'leaves': l, 'trees': t} for l in (15, 31) for t in (200, 500)]}
pred = base(tr, va)
fitted = {}
for kind, grid in GRID.items():
    rows = [met(iva.y, fit(kind, p, itr, iva)[0]) | {'params': p} for p in grid]
    res['tuning'][kind] = rows
    best = max(rows, key=lambda r: r['auc'])['params']; res['chosen'][kind] = best
    pred[kind], m, pr = fit(kind, best, tr, va); fitted[kind] = (m, pr)
res['valid'] = {k: met(va.y, p) for k, p in pred.items()}
y = va.y.to_numpy(); n = len(y); rng = np.random.default_rng(0); B = 1000
bt = {k: [] for k in pred}
for b in range(B):
    i = rng.integers(0, n, n)
    for k, p in pred.items():
        bt[k].append(met(y[i], p[i]))
ci = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
res['valid_ci'] = {k: {m: ci([r[m] for r in v]) for m in ('auc', 'brier')} for k, v in bt.items()}
res['diff_vs_B1'] = {k: {m: {'point': res['valid'][k][m] - res['valid']['B1'][m],
                             'ci': ci([bt[k][j][m] - bt['B1'][j][m] for j in range(B)])} for m in ('auc', 'brier')}
                     for k in ('B0', 'B2', 'logit', 'lgbm')}
# 보정(로지스틱)
p = pred['logit']; q = pd.qcut(p, 10, labels=False, duplicates='drop')
res['calibration_logit'] = [{'bin': int(b), 'n': int((q == b).sum()), 'pred': float(p[q == b].mean()),
                             'obs': float(y[q == b].mean())} for b in np.unique(q)]
# 로지스틱 계수 상위(표준화 변수 기준)
m, pr = fitted['logit']
co = pd.Series(m.coef_[0], index=pr.transform(va.head(5)).columns)
res['logit_top_coef'] = co.reindex(co.abs().sort_values(ascending=False).index).head(12).round(3).to_dict()
json.dump(res, open(os.path.join(VF, 'stage1_fix.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
print(json.dumps({k: res[k] for k in ('excluded_pre_registered', 'n', 'chosen', 'valid', 'valid_ci', 'diff_vs_B1',
                                      'calibration_logit', 'logit_top_coef')}, ensure_ascii=False, indent=1, default=float))
