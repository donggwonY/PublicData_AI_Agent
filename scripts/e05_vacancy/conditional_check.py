"""사후 점검: 폐업 후 d일째에도 빈 자리의 조건부 1년 확률. 계획 docs/e05/conditional_check_plan.md
결과 $E05_WORK/conditional_check.json. 모델·설정은 final_test.py와 동일(재학습만, 튜닝 없음)."""
import json, os, sys, time, warnings
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as E5P
import mlib as L
from sksurv.metrics import concordance_index_ipcw
from sksurv.util import Surv

VF = E5P.VF; OUT = os.path.join(VF, 'conditional_check.json')
t0 = time.time(); log = lambda *a: print(f'[{time.time()-t0:6.0f}s]', *a, flush=True)
SGC = ['sg_floor_total', 'sg_floor_other', 'sg_bldg_other', 'sg_floor_new_other', 'sg_nb_total', 'sg_nb_other_share',
       'sg_nb_change_1y']
L.LOG |= {'sg_floor_total', 'sg_floor_other', 'sg_bldg_other', 'sg_floor_new_other', 'sg_nb_total'}
X = pd.read_parquet(os.path.join(VF, 'asof_episodes.parquet')).merge(
    pd.read_parquet(os.path.join(VF, 'sangga_features.parquet')), on='occupant_id', how='left', validate='one_to_one')
prev = json.load(open(os.path.join(VF, 'models_sangga.json'), encoding='utf-8'))
P_M3 = prev['stage2']['params']['M3_rsf|sangga']; P_M1 = prev['stage2']['params']['M1_cox|sangga']
REF = '2026-11-06'
LANDMARKS = [90, 180, 365, 730, 1095]          # 폐업 후 경과일. 1095는 참고용
JUDGED = [180, 365, 730]
HZ = 365
tr = L.split(X, (2016, 2021), '2023-12-31'); te = L.split(X, (2022, 2023), REF)
s2tr, s2te = L.stage2(tr), L.stage2(te)
NUM = L.numeric_cols('s2') + ['s2_' + c for c in SGC]

# 필요한 시점(90일 기준점 이후 경과일)
need = sorted({d - 90 for d in LANDMARKS} | {d - 90 + HZ for d in LANDMARKS})


def eval_fns(fns, times):
    out = np.empty((len(fns), len(times)))
    for i, f in enumerate(fns):
        t = np.asarray(times, float)
        v = np.ones_like(t)
        m = t >= f.x[0]
        v[m] = f(np.minimum(t[m], f.x[-1]))
        out[i] = v
    return out


S = {}
pr3 = L.Prep(NUM, False).fit(s2tr); m3 = L.M3RSF(**P_M3).fit(pr3.transform(s2tr), s2tr)
S['M3'] = eval_fns(m3.m.predict_survival_function(pr3.transform(s2te).to_numpy(np.float32)), need); log('M3 done')
pr1 = L.Prep(NUM, True).fit(s2tr); m1 = L.M1Cox(**P_M1).fit(pr1.transform(s2tr), s2tr)
S['M1'] = eval_fns(m1.m.predict_survival_function(pr1.transform(s2te).to_numpy()), need); log('M1 done')
# B1: 구×직전 업종 KM(학습, 90일 기준점 이후)
allc = L.km(s2tr.ev, s2tr.dur)
cell = lambda d: d.f_gu.fillna('?') + '|' + d.prev_group
cur = {c: L.km(g.ev, g.dur) for c, g in s2tr.groupby(cell(s2tr)) if len(g) >= L.MIN_N}
grp = {c: L.km(g.ev, g.dur) for c, g in s2tr.groupby('prev_group') if len(g) >= L.MIN_N}
S['B1'] = np.array([L.km_at(cur.get(c) or grp.get(g) or allc, np.array(need, float))
                    for c, g in zip(cell(s2te), s2te.prev_group)])
col = {t: i for i, t in enumerate(need)}

# 재현 확인: d=90의 조건 없는 1년 확률이 final_test와 같은지
ft = json.load(open(os.path.join(os.path.dirname(E5P.SANGGA_MAP), 'results', 'final_test.json'), encoding='utf-8'))
res = {'plan': 'docs/e05/conditional_check_plan.md', 'params': {'M3': P_M3, 'M1': P_M1},
       'reproduce_d90_p_fill_365_mean': {k: {'now': float((1 - S[k][:, col[HZ]]).mean()),
                                             'final_test': ft['test'][k]['p_fill_365_mean']} for k in S},
       'landmarks': {}}
save = lambda: json.dump(res, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
km1y = lambda ev, t: float(1 - L.km_at(L.km(ev, t), np.array([HZ]))[0])
ci = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]


def quint(p, ev, t):
    q = pd.qcut(p, 5, labels=False, duplicates='drop'); rows = []
    for b in np.unique(q):
        m = q == b
        rows.append({'q': int(b), 'n': int(m.sum()), 'events_1y': int((ev[m] & (t[m] <= HZ)).sum()),
                     'pred': float(p[m].mean()), 'obs_km': km1y(ev[m], t[m])})
    inv = sum(rows[i + 1]['obs_km'] < rows[i]['obs_km'] for i in range(len(rows) - 1))
    return rows, int(inv)


rng = np.random.default_rng(0); B = 1000
for d in LANDMARKS:
    a, b = d - 90, d - 90 + HZ
    mte = (s2te.dur > a).to_numpy(); mtr = (s2tr.dur > a).to_numpy()
    ev = s2te.ev.to_numpy()[mte]; t = (s2te.dur.to_numpy() - a)[mte]
    ytr = Surv.from_arrays(s2tr.ev.to_numpy()[mtr], (s2tr.dur.to_numpy() - a)[mtr])
    yte = Surv.from_arrays(ev, t)
    P = {k: 1 - S[k][mte, col[b]] / np.clip(S[k][mte, col[a]], 1e-9, None) for k in S}
    naive = {k: 1 - S[k][mte, col[HZ]] for k in S}
    obs = km1y(ev, t)
    r = {'judged': d in JUDGED, 'n': int(mte.sum()), 'events_total': int(ev.sum()), 'events_1y': int((ev & (t <= HZ)).sum()),
         'censored_before_1y': int((~ev & (t < HZ)).sum()), 'obs_1y_km': obs, 'models': {}}
    cidx = lambda p, yy: float(concordance_index_ipcw(ytr, yy, p, tau=HZ)[0])
    for k in S:
        rows, inv = quint(P[k], ev, t)
        r['models'][k] = {'c_index': cidx(P[k], yte), 'pred_mean': float(P[k].mean()),
                          'naive_unconditional_pred_mean': float(naive[k].mean()), 'quintiles': rows, 'inversions': inv}
    bt = {k: {'c': [], 'cal': []} for k in S}; n = len(t)
    for _ in range(B):
        i = rng.integers(0, n, n); yb = yte[i]; ob = km1y(ev[i], t[i])
        for k in S:
            try: c = cidx(P[k][i], yb)
            except ValueError: c = np.nan
            bt[k]['c'].append(c); bt[k]['cal'].append(P[k][i].mean() - ob)
    for k in S:
        mk = r['models'][k]
        mk['c_index_ci'] = ci(np.array(bt[k]['c'])[~np.isnan(bt[k]['c'])])
        mk['cal_diff'] = mk['pred_mean'] - obs; mk['cal_diff_ci'] = ci(bt[k]['cal'])
    for k in ('M3', 'M1'):
        dc = np.array(bt[k]['c']) - np.array(bt['B1']['c']); dc = dc[~np.isnan(dc)]
        mk = r['models'][k]
        mk['c_diff_vs_B1'] = {'point': mk['c_index'] - r['models']['B1']['c_index'], 'ci': ci(dc)}
        lo, hi = mk['cal_diff_ci']
        mk['pass_order'] = bool(ci(dc)[0] > 0)
        mk['pass_calibration'] = bool(((lo >= -0.02 and hi <= 0.02) or (lo <= 0 <= hi)) and mk['inversions'] <= 1)
        mk['pass_both'] = mk['pass_order'] and mk['pass_calibration']
    res['landmarks'][str(d)] = r; save()
    log(d, 'n', r['n'], 'ev1y', r['events_1y'], 'obs', round(obs, 4),
        {k: (round(r['models'][k]['c_index'], 3), round(r['models'][k]['pred_mean'], 4)) for k in S})
res['seconds'] = round(time.time() - t0); save(); log('done')
