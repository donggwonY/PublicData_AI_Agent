"""상가정보 확장 비교. 계획 docs/e05/sangga_plan.md 6·7절.
같은 2016+ 표본에서 M1·M3·M4(2단계), 로지스틱·LightGBM(1단계)을 상가정보 없이/포함해 학습하고
'포함 − 없음' 차이를 부트스트랩으로 판정. 경계 업종 6개를 42종 밖으로 바꾼 민감도도 함께."""
import json, os, sys, time, warnings
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as E5P
import mlib as L
import sangga as G
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, brier_score_loss
import lightgbm as lgb

VF = E5P.VF; OUT = os.path.join(VF, 'models_sangga.json')
t0 = time.time(); log = lambda *a: print(f'[{time.time()-t0:6.0f}s]', *a, flush=True)
SGC = ['sg_floor_total', 'sg_floor_other', 'sg_bldg_other', 'sg_floor_new_other', 'sg_nb_total', 'sg_nb_other_share',
       'sg_nb_change_1y']
L.LOG |= {'sg_floor_total', 'sg_floor_other', 'sg_bldg_other', 'sg_floor_new_other', 'sg_nb_total'}
X0 = pd.read_parquet(os.path.join(VF, 'asof_episodes.parquet'))


def with_feats(F):
    return X0.merge(F, on='occupant_id', how='left', validate='one_to_one')


X = with_feats(pd.read_parquet(os.path.join(VF, 'sangga_features.parquet')))
res = {'n': {}, 'stage2': {}, 'stage1': {}}
save = lambda: json.dump(res, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
SPLITS = {'itr': ((2016, 2017), '2019-12-31'), 'iva': ((2018, 2019), '2021-12-31'),
          'tr': ((2016, 2019), '2021-12-31'), 'va': ((2020, 2021), '2023-12-31')}


def parts(X):
    return {k: L.split(X, y, e) for k, (y, e) in SPLITS.items()}


SPECS = {'M1_cox': (True, L.M1Cox, [{'alpha': a} for a in (0.1, 1, 10)]),
         'M3_rsf': (False, L.M3RSF, [{'leaf': l, 'mf': m} for l in (30, 100) for m in ('sqrt', 0.3)]),
         'M4_cure': (True, L.M4Cure, [{'l2': v} for v in (0.1, 1, 10)])}


def s2_run(X, tag, num_extra, only=None):
    P = {k: L.stage2(v) for k, v in parts(X).items()}
    res['n'].setdefault('stage2', {k: {'n': len(v), 'events': int(v.ev.sum())} for k, v in P.items()})
    ytr_i, yva_i, ytr, yva = (L.surv_y(P[k]) for k in ('itr', 'iva', 'tr', 'va'))
    out = {}
    for name, (scale, cls, grid) in SPECS.items():
        if only and name not in only:
            continue
        for fs, extra in (('base', []), ('sangga', num_extra)):
            num = L.numeric_cols('s2') + extra
            best, bc = None, -1
            for p in grid:
                pr = L.Prep(num, scale).fit(P['itr'])
                m = cls(**p).fit(pr.transform(P['itr']), P['itr'])
                c = L.s2_metrics(m.surv(pr.transform(P['iva'])), yva_i, ytr_i)['c_index']
                if c > bc: bc, best = c, p
            pr = L.Prep(num, scale).fit(P['tr'])
            m = cls(**best).fit(pr.transform(P['tr']), P['tr'])
            out[f'{name}|{fs}'] = {'S': m.surv(pr.transform(P['va'])), 'params': best, 'tune_c': bc}
            log(tag, name, fs, best, round(bc, 4))
    out['B1|base'] = {'S': L.b1_surv(P['tr'], P['va']).to_numpy(), 'params': None, 'tune_c': None}
    return out, yva, ytr, P['va']


def boot_s2(out, yva, ytr, B=1000):
    rng = np.random.default_rng(0); n = len(yva); keys = list(out)
    pts = {k: L.s2_metrics(out[k]['S'], yva, ytr) for k in keys}
    bt = {k: [] for k in keys}
    for b in range(B):
        i = rng.integers(0, n, n); yb = yva[i]
        for k in keys:
            try: bt[k].append(L.s2_metrics(out[k]['S'][i], yb, ytr))
            except ValueError: bt[k].append(None)
    ok = [j for j in range(B) if all(bt[k][j] is not None for k in keys)]
    ci = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
    diff = lambda a, b, m: {'point': pts[a][m] - pts[b][m], 'ci': ci([bt[a][j][m] - bt[b][j][m] for j in ok])}
    models = sorted({k.split('|')[0] for k in keys if k != 'B1|base'})
    return {'valid': pts, 'params': {k: out[k]['params'] for k in keys}, 'bootstrap_used': len(ok),
            'sangga_minus_base': {m: {'c_index': diff(f'{m}|sangga', f'{m}|base', 'c_index'),
                                      'ibs': diff(f'{m}|sangga', f'{m}|base', 'ibs')} for m in models},
            'vs_B1': {k: {'c_index': diff(k, 'B1|base', 'c_index'), 'ibs': diff(k, 'B1|base', 'ibs')}
                      for k in keys if k != 'B1|base'}}


SG2 = ['s2_' + c for c in SGC]
out, yva, ytr, va = s2_run(X, 'main', SG2)
r = boot_s2(out, yva, ytr)
for m, v in r['sangga_minus_base'].items():
    v['helps'] = bool(v['c_index']['ci'][0] > 0)
res['stage2'] = r
res['stage2']['calibration_365'] = {k: L.calib_365(out[k]['S'], va) for k in out}
save(); log('stage2 done', {m: (round(v['c_index']['point'], 4), [round(x, 4) for x in v['c_index']['ci']]) for m, v in r['sangga_minus_base'].items()})

# ── 민감도: 경계 6개를 42종 밖으로 ──
cm = pd.read_csv(E5P.SANGGA_MAP, dtype=str)
cm.loc[cm['경계'] == 'True', '구분'] = '42종 밖'
alt_csv = os.path.join(VF, 'sangga_category_map_alt.csv'); cm.to_csv(alt_csv, index=False, encoding='utf-8-sig')
d_alt = G.load_quarters(os.path.join(E5P.AUX, 'sangga'), alt_csv)
sg_alt = G.SG(d_alt)
F_alt = pd.concat([sg_alt.features(X0, X0.t0, 's1_'), sg_alt.features(X0, X0.t0 + pd.Timedelta(days=90), 's2_')], axis=1)
F_alt.insert(0, 'occupant_id', X0.occupant_id.to_numpy())
Xa = with_feats(F_alt)
out_a, yva_a, ytr_a, _ = s2_run(Xa, 'alt', SG2)
ra = boot_s2(out_a, yva_a, ytr_a, B=500)
for m, v in ra['sangga_minus_base'].items():
    v['helps'] = bool(v['c_index']['ci'][0] > 0)
res['stage2_sensitivity_boundary_as_other'] = {k: ra[k] for k in ('valid', 'sangga_minus_base', 'bootstrap_used')}
save(); log('sensitivity done')

# ── 1단계(정의 수정본) ──
def s1_parts(X):
    o = {}
    for k, v in parts(X).items():
        d = L.stage1(v); o[k] = d[d.next_ld.isna() | (d.next_ld > d.t0)].copy()
    return o


P1 = s1_parts(X)
res['n']['stage1'] = {k: {'n': len(v), 'pos': int(v.y.sum())} for k, v in P1.items()}
SG1 = ['s1_' + c for c in SGC]
G1 = {'logit': [{'C': c} for c in (0.01, 0.1, 1)], 'lgbm': [{'leaves': l, 'trees': t} for l in (15, 31) for t in (200, 500)]}


def s1_fit(kind, p, num, a, b):
    pr = L.Prep(num, kind == 'logit').fit(a); A, Bm = pr.transform(a), pr.transform(b)
    m = (LogisticRegression(C=p['C'], max_iter=3000) if kind == 'logit' else
         lgb.LGBMClassifier(num_leaves=p['leaves'], n_estimators=p['trees'], learning_rate=0.05, min_child_samples=100,
                            subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=0, verbose=-1)).fit(A, a.y)
    return m.predict_proba(Bm)[:, 1]


pred = {}
for kind, grid in G1.items():
    for fs, extra in (('base', []), ('sangga', SG1)):
        num = L.numeric_cols('s1') + extra
        best = max(grid, key=lambda p: roc_auc_score(P1['iva'].y, s1_fit(kind, p, num, P1['itr'], P1['iva'])))
        pred[f'{kind}|{fs}'] = s1_fit(kind, best, num, P1['tr'], P1['va'])
y = P1['va'].y.to_numpy(); n = len(y); rng = np.random.default_rng(0)
pt = {k: {'auc': roc_auc_score(y, p), 'brier': brier_score_loss(y, p)} for k, p in pred.items()}
bt = {k: [] for k in pred}
for b in range(1000):
    i = rng.integers(0, n, n)
    for k, p in pred.items():
        bt[k].append({'auc': roc_auc_score(y[i], p[i]), 'brier': brier_score_loss(y[i], p[i])})
ci = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
res['stage1'] = {'valid': pt, 'sangga_minus_base': {
    k: {m: {'point': pt[f'{k}|sangga'][m] - pt[f'{k}|base'][m],
            'ci': ci([bt[f'{k}|sangga'][j][m] - bt[f'{k}|base'][j][m] for j in range(1000)])} for m in ('auc', 'brier')}
    for k in G1}}
for k, v in res['stage1']['sangga_minus_base'].items():
    v['helps'] = bool(v['auc']['ci'][0] > 0)
res['seconds'] = round(time.time() - t0)
save(); log('done')
