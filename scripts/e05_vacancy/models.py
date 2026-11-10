"""3단계 실행: 튜닝(학습 구간 내부) → 최종 학습 → 검증 비교(B1 대비) → 묶음 기여·중요도·보정·PH 점검·1단계.
계획 docs/e05/models_plan.md. 결과 $E05_WORK/models_valid.json"""
import json, os, sys, time, warnings
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as E5P
import mlib as L
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss, log_loss
import lightgbm as lgb

VF = E5P.VF
OUT = os.path.join(VF, 'models_valid.json')
t0 = time.time()
log = lambda *a: print(f'[{time.time()-t0:6.0f}s]', *a, flush=True)
X = pd.read_parquet(os.path.join(VF, 'asof_episodes.parquet'))
itr, iva = L.split(X, (2012, 2017), '2019-12-31'), L.split(X, (2018, 2019), '2021-12-31')
tr, va = L.split(X, (2012, 2019), '2021-12-31'), L.split(X, (2020, 2021), '2023-12-31')
res = {'n': {}, 'tuning': {}, 'chosen': {}, 'valid': {}, 'notes': []}
save = lambda: json.dump(res, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)

# ───────────── 2단계 ─────────────
i2tr, i2va, s2tr, s2va = map(L.stage2, (itr, iva, tr, va))
res['n']['stage2'] = {k: {'n': len(d), 'events': int(d.ev.sum())} for k, d in
                      (('tune_train', i2tr), ('tune_valid', i2va), ('train', s2tr), ('valid', s2va))}
NUM = L.numeric_cols('s2')
SPECS = {
    'M1_cox': (True, lambda p: L.M1Cox(**p), [{'alpha': a} for a in (0.1, 1, 10)]),
    'M2a_discrete_logit': (True, lambda p: L.M2Discrete('logit', **p), [{'C': c} for c in (0.01, 0.1, 1)]),
    'M2b_discrete_lgbm': (False, lambda p: L.M2Discrete('lgbm', **p),
                          [{'leaves': l, 'trees': t} for l in (15, 31) for t in (200, 500)]),
    'M3_rsf': (False, lambda p: L.M3RSF(**p), [{'leaf': l, 'mf': m} for l in (30, 100) for m in ('sqrt', 0.3)]),
    'M4_cure': (True, lambda p: L.M4Cure(**p), [{'l2': v} for v in (0.1, 1, 10)]),
}


def fit_eval(spec, params, dtr, dte, num=NUM):
    scale, make, _ = spec
    pr = L.Prep(num, scale).fit(dtr)
    m = make(params).fit(pr.transform(dtr), dtr)
    S = m.surv(pr.transform(dte))
    return m, pr, S


ytr_i = L.surv_y(i2tr); yva_i = L.surv_y(i2va)
for name, spec in SPECS.items():
    rows = []
    for p in spec[2]:
        try:
            m, _, S = fit_eval(spec, p, i2tr, i2va)
            r = L.s2_metrics(S, yva_i, ytr_i) | {'params': p}
            if name == 'M4_cure':
                r |= {'converged': m.ok, 'message': m.msg}
        except Exception as e:  # noqa: BLE001
            r = {'params': p, 'error': repr(e)}
        rows.append(r); log(name, p, {k: round(v, 4) for k, v in r.items() if isinstance(v, float)})
    res['tuning'][name] = rows
    ok = [r for r in rows if 'c_index' in r]
    res['chosen'][name] = max(ok, key=lambda r: (round(r['c_index'], 4), -r['ibs']))['params']
    save()
# B1 튜닝 검증 참고값
b1_i = L.b1_surv(i2tr, i2va)
res['tuning']['B1'] = L.s2_metrics(b1_i.to_numpy(), yva_i, ytr_i)
log('B1 tune', res['tuning']['B1'])

# 최종 학습 → 검증
ytr = L.surv_y(s2tr); yva = L.surv_y(s2va)
Smat = {'B1': L.b1_surv(s2tr, s2va).to_numpy()}
models = {}
for name, spec in SPECS.items():
    m, pr, S = fit_eval(spec, res['chosen'][name], s2tr, s2va)
    Smat[name] = S; models[name] = (m, pr)
    res['valid'][name] = L.s2_metrics(S, yva, ytr)
    if name == 'M4_cure':
        res['valid'][name] |= {'converged': m.ok, 'susceptible_mean_valid': float(m.susceptible(pr.transform(s2va)).mean())}
    log('valid', name, {k: round(v, 4) for k, v in res['valid'][name].items() if isinstance(v, float)})
res['valid']['B1'] = L.s2_metrics(Smat['B1'], yva, ytr)
save()

# 부트스트랩(같은 재표본)
rng = np.random.default_rng(0); B = 1000; n = len(s2va)
boot = {k: [] for k in Smat}
for b in range(B):
    i = rng.integers(0, n, n); yb = yva[i]
    for k, S in Smat.items():
        try:
            boot[k].append(L.s2_metrics(S[i], yb, ytr))
        except ValueError:
            boot[k].append(None)
    if b % 200 == 0:
        log('boot', b)
ok_idx = [j for j in range(B) if all(boot[k][j] is not None for k in boot)]
res['bootstrap_used'] = len(ok_idx)


def ci(v): return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]


res['valid_ci'] = {k: {m: ci([boot[k][j][m] for j in ok_idx]) for m in ('c_index', 'auc_365', 'ibs')} for k in boot}
res['diff_vs_B1'] = {}
for k in SPECS:
    dc = np.array([boot[k][j]['c_index'] - boot['B1'][j]['c_index'] for j in ok_idx])
    di = np.array([boot[k][j]['ibs'] - boot['B1'][j]['ibs'] for j in ok_idx])
    pc = res['valid'][k]['c_index'] - res['valid']['B1']['c_index']
    pi = res['valid'][k]['ibs'] - res['valid']['B1']['ibs']
    res['diff_vs_B1'][k] = {'c_index': {'point': pc, 'ci': ci(dc)}, 'ibs': {'point': pi, 'ci': ci(di)},
                            'pass_c': bool(pc >= 0.02 and ci(dc)[0] > 0), 'pass_ibs': bool(pi < 0 and ci(di)[1] < 0)}
    res['diff_vs_B1'][k]['pass_both'] = res['diff_vs_B1'][k]['pass_c'] and res['diff_vs_B1'][k]['pass_ibs']
res['calibration_365'] = {k: L.calib_365(S, s2va) for k, S in Smat.items()}
save(); log('bootstrap done')

# 묶음 기여: 튜닝 검증 C-index 최고 모델 유형
best_type = max(SPECS, key=lambda k: max(r.get('c_index', 0) for r in res['tuning'][k]))
res['best_type_by_tuning'] = best_type
abl = {}
for sets in (('L',), ('L', 'S'), ('L', 'S', 'P')):
    _, _, S = fit_eval(SPECS[best_type], res['chosen'][best_type], s2tr, s2va, num=L.numeric_cols('s2', sets))
    abl['+'.join(sets)] = L.s2_metrics(S, yva, ytr)
res['ablation_valid'] = abl; save(); log('ablation', {k: round(v['c_index'], 4) for k, v in abl.items()})

# 묶음별 순열 중요도(최종 best_type 모델, 검증)
m, pr = models[best_type]
base_c = res['valid'][best_type]['c_index']
raw = {g: [('s2_' + c if c in L.NB + L.SUB + L.POP else c) for c in cols] for g, cols in L.GROUPS.items()}
raw['직전가게'] = L.CAT + L.BASE_NUM + ['close_month']
imp = {}
for g, cols in raw.items():
    drops = []
    for r in range(5):
        d2 = s2va.copy(); perm = np.random.default_rng(100 + r).permutation(len(d2))
        for c in cols:
            d2[c] = d2[c].iloc[perm].to_numpy()
        drops.append(base_c - L.s2_metrics(m.surv(pr.transform(d2)), yva, ytr)['c_index'])
    imp[g] = {'mean_drop': float(np.mean(drops)), 'sd': float(np.std(drops))}
res['permutation_importance_valid'] = imp; save(); log('importance', {k: round(v['mean_drop'], 4) for k, v in imp.items()})

# Cox 비례위험 점검
try:
    from lifelines import CoxPHFitter
    from lifelines.statistics import proportional_hazard_test
    pr = L.Prep(NUM, True).fit(s2tr); Z = pr.transform(s2tr)
    Z = Z.loc[:, Z.std() > 0]
    df = Z.assign(dur=s2tr.dur.to_numpy(), ev=s2tr.ev.to_numpy().astype(int))
    cph = CoxPHFitter(penalizer=0.01).fit(df, 'dur', 'ev')
    ph = proportional_hazard_test(cph, df, time_transform='rank')
    pv = ph.summary['p']
    res['cox_ph_check'] = {'n_vars': int(len(pv)), 'p_lt_0.01': int((pv < 0.01).sum()),
                           'worst': pv.sort_values().head(8).round(5).to_dict()}
except Exception as e:  # noqa: BLE001
    res['cox_ph_check'] = {'error': repr(e)}
save(); log('ph', res['cox_ph_check'])

# ───────────── 1단계 ─────────────
i1tr, i1va, s1tr, s1va = map(L.stage1, (itr, iva, tr, va))
NUM1 = L.numeric_cols('s1')
res['n']['stage1'] = {k: {'n': len(d), 'pos': int(d.y.sum())} for k, d in
                      (('tune_train', i1tr), ('tune_valid', i1va), ('train', s1tr), ('valid', s1va))}


def s1_fit(kind, p, dtr, dte):
    pr = L.Prep(NUM1, kind == 'logit').fit(dtr); A, Bm = pr.transform(dtr), pr.transform(dte)
    if kind == 'logit':
        m = LogisticRegression(C=p['C'], max_iter=3000).fit(A, dtr.y)
    else:
        m = lgb.LGBMClassifier(num_leaves=p['leaves'], n_estimators=p['trees'], learning_rate=0.05, min_child_samples=100,
                               subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=0, verbose=-1).fit(A, dtr.y)
    return m.predict_proba(Bm)[:, 1]


def s1m(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return {'auc': float(roc_auc_score(y, p)), 'pr_auc': float(average_precision_score(y, p)),
            'brier': float(brier_score_loss(y, p)), 'log_loss': float(log_loss(y, p))}


def s1_b1(dtr, dte):
    p0 = dtr.y.mean(); cell = lambda d: d.f_gu.fillna('?') + '|' + d.prev_group
    g = dtr.groupby(cell(dtr)).y.agg(['mean', 'size']); g = g[g['size'] >= L.MIN_N]['mean']
    gr = dtr.groupby('prev_group').y.mean()
    return cell(dte).map(g).fillna(dte.prev_group.map(gr)).fillna(p0).to_numpy()


S1 = {'logit': [{'C': c} for c in (0.01, 0.1, 1)], 'lgbm': [{'leaves': l, 'trees': t} for l in (15, 31) for t in (200, 500)]}
res['stage1'] = {'tuning': {}, 'chosen': {}, 'valid': {}}
pred1 = {'B1': s1_b1(s1tr, s1va)}
for kind, grid in S1.items():
    rows = [s1m(i1va.y, s1_fit(kind, p, i1tr, i1va)) | {'params': p} for p in grid]
    res['stage1']['tuning'][kind] = rows
    best = max(rows, key=lambda r: r['auc'])['params']; res['stage1']['chosen'][kind] = best
    pred1[kind] = s1_fit(kind, best, s1tr, s1va)
for k, p in pred1.items():
    res['stage1']['valid'][k] = s1m(s1va.y, p)
y1 = s1va.y.to_numpy(); n1 = len(y1); bt = {k: [] for k in pred1}
for b in range(B):
    i = rng.integers(0, n1, n1)
    for k, p in pred1.items():
        bt[k].append(s1m(y1[i], p[i]))
res['stage1']['diff_vs_B1'] = {k: {m: {'point': res['stage1']['valid'][k][m] - res['stage1']['valid']['B1'][m],
                                       'ci': ci([bt[k][j][m] - bt['B1'][j][m] for j in range(B)])} for m in ('auc', 'brier')}
                               for k in S1}
res['seconds'] = round(time.time() - t0)
save(); log('done')
