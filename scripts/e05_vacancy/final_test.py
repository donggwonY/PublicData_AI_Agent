"""4단계: 평가 구간(2022–2023) 1회 평가. 계획 docs/e05/final_test_plan.md. 결과 $E05_WORK/final_test.json"""
import json, os, sys, time, warnings
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as E5P
import mlib as L
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
import lightgbm as lgb

VF = E5P.VF; OUT = os.path.join(VF, 'final_test.json')
t0 = time.time(); log = lambda *a: print(f'[{time.time()-t0:6.0f}s]', *a, flush=True)
SGC = ['sg_floor_total', 'sg_floor_other', 'sg_bldg_other', 'sg_floor_new_other', 'sg_nb_total', 'sg_nb_other_share',
       'sg_nb_change_1y']
L.LOG |= {'sg_floor_total', 'sg_floor_other', 'sg_bldg_other', 'sg_floor_new_other', 'sg_nb_total'}
X = pd.read_parquet(os.path.join(VF, 'asof_episodes.parquet')).merge(
    pd.read_parquet(os.path.join(VF, 'sangga_features.parquet')), on='occupant_id', how='left', validate='one_to_one')
prev = json.load(open(os.path.join(VF, 'models_sangga.json'), encoding='utf-8'))
P_M3 = prev['stage2']['params']['M3_rsf|sangga']; P_M1 = prev['stage2']['params']['M1_cox|sangga']
REF = '2026-11-06'
tr = L.split(X, (2016, 2021), '2023-12-31'); te = L.split(X, (2022, 2023), REF)
res = {'params': {'M3': P_M3, 'M1': P_M1}, 'n': {}}
save = lambda: json.dump(res, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
ci = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]

# ───────────── 2단계 ─────────────
s2tr, s2te = L.stage2(tr), L.stage2(te)
res['n']['stage2'] = {'train': {'n': len(s2tr), 'events': int(s2tr.ev.sum())}, 'test': {'n': len(s2te), 'events': int(s2te.ev.sum())}}
NUM = L.numeric_cols('s2') + ['s2_' + c for c in SGC]
ytr, yte = L.surv_y(s2tr), L.surv_y(s2te)
S = {}
pr3 = L.Prep(NUM, False).fit(s2tr); m3 = L.M3RSF(**P_M3).fit(pr3.transform(s2tr), s2tr); S['M3'] = m3.surv(pr3.transform(s2te))
pr1 = L.Prep(NUM, True).fit(s2tr); m1 = L.M1Cox(**P_M1).fit(pr1.transform(s2tr), s2tr); S['M1'] = m1.surv(pr1.transform(s2te))
S['B1'] = L.b1_surv(s2tr, s2te).to_numpy()
res['test'] = {k: L.s2_metrics(v, yte, ytr) for k, v in S.items()}
log('test', {k: round(v['c_index'], 4) for k, v in res['test'].items()})
rng = np.random.default_rng(0); B = 1000; n = len(s2te); bt = {k: [] for k in S}
for b in range(B):
    i = rng.integers(0, n, n); yb = yte[i]
    for k, v in S.items():
        try: bt[k].append(L.s2_metrics(v[i], yb, ytr))
        except ValueError: bt[k].append(None)
ok = [j for j in range(B) if all(bt[k][j] is not None for k in S)]
res['bootstrap_used'] = len(ok)
res['test_ci'] = {k: {m: ci([bt[k][j][m] for j in ok]) for m in ('c_index', 'auc_365', 'ibs')} for k in S}
res['diff_vs_B1'] = {}
for k in ('M3', 'M1'):
    dc = [bt[k][j]['c_index'] - bt['B1'][j]['c_index'] for j in ok]; di = [bt[k][j]['ibs'] - bt['B1'][j]['ibs'] for j in ok]
    pc = res['test'][k]['c_index'] - res['test']['B1']['c_index']; pi = res['test'][k]['ibs'] - res['test']['B1']['ibs']
    res['diff_vs_B1'][k] = {'c_index': {'point': pc, 'ci': ci(dc)}, 'ibs': {'point': pi, 'ci': ci(di)},
                            'pass_c': bool(pc >= 0.02 and ci(dc)[0] > 0), 'pass_ibs': bool(pi < 0 and ci(di)[1] < 0)}
    res['diff_vs_B1'][k]['pass_both'] = res['diff_vs_B1'][k]['pass_c'] and res['diff_vs_B1'][k]['pass_ibs']
res['calibration_365'] = {k: L.calib_365(v, s2te) for k, v in S.items()}
save(); log('bootstrap done')

# 오류 분석(M3)
col365 = list(L.TIMES).index(365); p1y = 1 - S['M3'][:, col365]
te2 = s2te.assign(p1y=p1y, has_sg_floor=s2te['s2_sg_floor_total'].notna().map({True: '층정보 있음', False: '층정보 없음'}))
sub = {}
for by in ('prev_group', 'f_gu', 'floor_class', 'close_year', 'has_sg_floor'):
    rows = []
    for g, d in te2.groupby(by):
        idx = te2.index.get_indexer(d.index)
        r = {'group': str(g), 'n': len(d), 'events': int(d.ev.sum()), 'pred_1y_mean': float(d.p1y.mean()),
             'obs_1y_km': float(1 - L.km_at(L.km(d.ev, d.dur), np.array([365]))[0])}
        if d.ev.sum() >= 30:
            try: r['c_index'] = float(L.s2_metrics(S['M3'][idx], yte[idx], ytr)['c_index'])
            except ValueError: r['c_index'] = None
        rows.append(r)
    sub[by] = sorted(rows, key=lambda r: -r['n'])
res['subgroups_M3'] = sub
# 크게 틀린 사례
q_hi, q_lo = np.quantile(p1y, 0.9), np.quantile(p1y, 0.1)
hi = te2[(te2.p1y >= q_hi) & ~(te2.ev & (te2.dur <= 730)) & (te2.dur >= 730)]
lo = te2[(te2.p1y <= q_lo) & te2.ev & (te2.dur <= 180)]
sgq = pd.read_parquet(os.path.join(VF, 'sangga_quarters.parquet'), columns=['q', 'bkey', 'floor', 'other'])
last = sgq[sgq.q == sgq.q.max()]
fl_other = last[last.other & last.floor.notna()].groupby(['bkey', 'floor']).size()
bl_other = last[last.other].groupby('bkey').size()
hi_has_floor = hi.floor.notna()
res['big_errors_M3'] = {
    'high_pred_not_filled_2y': {
        'n': len(hi), 'threshold_pred_1y': float(q_hi),
        'with_floor_info': int(hi_has_floor.sum()),
        'other_store_same_floor_2026_09_pct_of_with_floor': float(np.mean([(b, f) in fl_other.index for b, f in zip(hi.building_key[hi_has_floor], hi.floor[hi_has_floor])]) * 100) if hi_has_floor.any() else None,
        'other_store_same_building_2026_09_pct': float(hi.building_key.isin(bl_other.index).mean() * 100),
        'prev_group_top': hi.prev_group.value_counts().head(5).to_dict()},
    'low_pred_filled_180d': {'n': len(lo), 'threshold_pred_1y': float(q_lo),
                             'next_service_top': lo.next_service.value_counts().head(8).to_dict(),
                             'prev_group_top': lo.prev_group.value_counts().head(5).to_dict()},
    'note': '진단용: 결과 이후(2026-09 상가정보, 실제 다음 업종)를 일부러 본 것이며 모델에 반영하지 않음'}
save(); log('error analysis done')

# ───────────── 1단계 ─────────────
def s1(years, end):
    d = L.stage1(L.split(X, years, end)); return d[d.next_ld.isna() | (d.next_ld > d.t0)].copy()


i1tr, i1va, s1tr, s1te = s1((2016, 2017), '2019-12-31'), s1((2018, 2019), '2021-12-31'), s1((2016, 2021), '2023-12-31'), s1((2022, 2023), REF)
NUM1 = L.numeric_cols('s1') + ['s1_' + c for c in SGC]


def lgbm(p, a, b):
    pr = L.Prep(NUM1, False).fit(a)
    m = lgb.LGBMClassifier(num_leaves=p['leaves'], n_estimators=p['trees'], learning_rate=0.05, min_child_samples=100,
                           subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=0, verbose=-1).fit(pr.transform(a), a.y)
    return m.predict_proba(pr.transform(b))[:, 1]


grid = [{'leaves': l, 'trees': t} for l in (15, 31) for t in (200, 500)]
best = max(grid, key=lambda p: roc_auc_score(i1va.y, lgbm(p, i1tr, i1va)))
p_lgb = lgbm(best, s1tr, s1te)
p0 = s1tr.y.mean(); cell = lambda d: d.f_gu.fillna('?') + '|' + d.prev_group
g = s1tr.groupby(cell(s1tr)).y.agg(['mean', 'size']); g = g[g['size'] >= L.MIN_N]['mean']
p_b1 = cell(s1te).map(g).fillna(s1te.prev_group.map(s1tr.groupby('prev_group').y.mean())).fillna(p0).to_numpy()
y = s1te.y.to_numpy()
mm = lambda y, p: {'auc': float(roc_auc_score(y, p)), 'pr_auc': float(average_precision_score(y, p)), 'brier': float(brier_score_loss(y, p))}
res['stage1'] = {'n': {'train': {'n': len(s1tr), 'pos': int(s1tr.y.sum())}, 'test': {'n': len(s1te), 'pos': int(y.sum())}},
                 'lgbm_params': best, 'test': {'LGBM': mm(y, p_lgb), 'B1': mm(y, p_b1)}}
bt1 = []
for b in range(B):
    i = rng.integers(0, len(y), len(y)); a, c = mm(y[i], p_lgb[i]), mm(y[i], p_b1[i])
    bt1.append((a['auc'] - c['auc'], a['brier'] - c['brier']))
bt1 = np.array(bt1)
d_auc = res['stage1']['test']['LGBM']['auc'] - res['stage1']['test']['B1']['auc']
d_br = res['stage1']['test']['LGBM']['brier'] - res['stage1']['test']['B1']['brier']
res['stage1']['diff_vs_B1'] = {'auc': {'point': d_auc, 'ci': ci(bt1[:, 0])}, 'brier': {'point': d_br, 'ci': ci(bt1[:, 1])},
                               'pass': bool(ci(bt1[:, 0])[0] > 0 and ci(bt1[:, 1])[1] < 0)}
q = pd.qcut(p_lgb, 10, labels=False, duplicates='drop')
res['stage1']['calibration_lgbm'] = [{'bin': int(b), 'n': int((q == b).sum()), 'pred': float(p_lgb[q == b].mean()),
                                      'obs': float(y[q == b].mean())} for b in np.unique(q)]
res['seconds'] = round(time.time() - t0)
save(); log('done')
