"""2단계: 기준선 B0~B2 를 검증 구간(2020~2021 폐업)에서 평가. 계획 docs/e05/vacancy_fill_plan.md 6·7절.

학습 = 2012~2019 폐업(정답 관측 종료 2021-12-31), 검증 = 2020~2021 폐업(관측 종료 2023-12-31). 평가 구간은 쓰지 않는다.
1단계: 90일 안 채워짐(분류). 2단계: 90일 시점에도 빈 사례, 시간 원점 = 폐업 + 90일.
"""
import json, os, sys
import numpy as np, pandas as pd
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss, log_loss
from sksurv.nonparametric import kaplan_meier_estimator
from sksurv.metrics import concordance_index_ipcw, cumulative_dynamic_auc, integrated_brier_score
from sksurv.util import Surv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as E5P

VF = E5P.VF
X = pd.read_parquet(os.path.join(VF, 'asof_episodes.parquet'))
OBS_END = {'train': pd.Timestamp('2021-12-31'), 'valid': pd.Timestamp('2023-12-31')}
MIN_N = 30
H = [180, 365, 730]                    # 평가 시점(90일 이후 경과일)
GRID = np.arange(30, 721, 30)          # IBS 시간 격자
TAU = 730
B = 1000
rng = np.random.default_rng(0)


def censor(d: pd.DataFrame, end: pd.Timestamp) -> pd.DataFrame:
    d = d.copy()
    lim = (end - d.t0).dt.days
    d['ev'] = d.event & (d['T'] <= lim)
    d['tt'] = np.where(d.ev, d['T'], np.minimum(d['T'], lim)).astype(float)
    return d


def gap_bin(v):
    return np.select([v.isna(), v <= 90, v <= 365], ['이력없음', '90일이하', '90일~1년'], '1년초과')


tr = censor(X[X.split == 'train'], OBS_END['train'])
va = censor(X[X.split == 'valid'], OBS_END['valid'])
for d in (tr, va):
    d['cell_b1'] = d.f_gu.fillna('?') + '|' + d.prev_group
    d['cell_b2'] = gap_bin(d.h_mean_gap_days)
checks = {
    'train_no_event_after_obs_end': bool(not (tr.ev & (tr.t0 + pd.to_timedelta(tr['T'], 'D') > OBS_END['train'])).any()),
    'valid_no_event_after_obs_end': bool(not (va.ev & (va.t0 + pd.to_timedelta(va['T'], 'D') > OBS_END['valid'])).any()),
}

# ───────────── 1단계: 90일 안 채워짐 ─────────────
def s1_frame(d):
    known = d.ev & (d.tt <= 90) | (d.tt > 90)          # 90일 전에 관측이 끊긴 사례(일괄등록 절단)는 제외
    d = d[known].copy(); d['y'] = (d.ev & (d.tt <= 90)).astype(int); return d


s1tr, s1va = s1_frame(tr), s1_frame(va)


def rate_by(cell_tr, y_tr, cell_va, fallback):
    g = pd.DataFrame({'c': cell_tr, 'y': y_tr}).groupby('c').y.agg(['mean', 'size'])
    g = g[g['size'] >= MIN_N]['mean']
    return cell_va.map(g).fillna(fallback).to_numpy()


p0 = s1tr.y.mean()
grp_rate = s1tr.groupby('prev_group').y.mean()
s1_pred = {
    'B0': np.full(len(s1va), p0),
    'B1': rate_by(s1tr.cell_b1, s1tr.y, s1va.cell_b1, s1va.prev_group.map(grp_rate).fillna(p0)),
    'B2': rate_by(s1tr.cell_b2, s1tr.y, s1va.cell_b2, pd.Series(p0, index=s1va.index)),
}


def s1_metrics(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    auc = roc_auc_score(y, p) if len(np.unique(p)) > 1 else 0.5
    return {'auc': auc, 'pr_auc': average_precision_score(y, p), 'brier': brier_score_loss(y, p), 'log_loss': log_loss(y, p)}


# ───────────── 2단계: 90일 이후 ─────────────
l_tr = tr[tr.tt > 90].copy(); l_va = va[va.tt > 90].copy()
for d in (l_tr, l_va):
    d['dur'] = d.tt - 90
y_tr = Surv.from_arrays(l_tr.ev.to_numpy(), l_tr.dur.to_numpy())
y_va = Surv.from_arrays(l_va.ev.to_numpy(), l_va.dur.to_numpy())


def km(ev, t):
    x, s = kaplan_meier_estimator(ev.astype(bool), t.astype(float))
    return x, s


def km_at(curve, times):
    x, s = curve
    idx = np.searchsorted(x, times, side='right') - 1
    return np.where(idx >= 0, s[np.clip(idx, 0, None)], 1.0)


all_curve = km(l_tr.ev.to_numpy(), l_tr.dur.to_numpy())


def curves_by(cell):
    out = {}
    for c, g in l_tr.groupby(cell):
        if len(g) >= MIN_N:
            out[c] = km(g.ev.to_numpy(), g.dur.to_numpy())
    return out


grp_curves = curves_by('prev_group')
b1_curves = curves_by('cell_b1')
b2_curves = curves_by('cell_b2')
times_all = np.unique(np.concatenate([GRID, H]))


def surv_matrix(cells, curves, fallback_cells=None, fallback_curves=None):
    rows = []
    for i, c in enumerate(cells):
        cur = curves.get(c)
        if cur is None and fallback_cells is not None:
            cur = fallback_curves.get(fallback_cells[i])
        if cur is None:
            cur = all_curve
        rows.append(km_at(cur, times_all))
    return pd.DataFrame(np.array(rows), columns=times_all)


S2 = {
    'B0': surv_matrix([None] * len(l_va), {}),
    'B1': surv_matrix(l_va.cell_b1.to_list(), b1_curves, l_va.prev_group.to_list(), grp_curves),
    'B2': surv_matrix(l_va.cell_b2.to_list(), b2_curves),
}
fallback_share = {
    'B1_cell': float(l_va.cell_b1.isin(b1_curves).mean()),
    'B1_group_fallback': float((~l_va.cell_b1.isin(b1_curves) & l_va.prev_group.isin(grp_curves)).mean()),
    'B2_cell': float(l_va.cell_b2.isin(b2_curves).mean()),
}


def s2_metrics(Sm, yv, ytr):
    risk1y = 1 - Sm[365].to_numpy()
    c = concordance_index_ipcw(ytr, yv, risk1y, tau=TAU)[0]
    risk = 1 - Sm[H].to_numpy()
    if np.ptp(risk, axis=0).max() == 0:
        aucs = [0.5] * len(H)
    else:
        aucs = list(cumulative_dynamic_auc(ytr, yv, risk, H)[0])
    t_ok = GRID[GRID < yv['time'].max()]
    ibs = integrated_brier_score(ytr, yv, Sm[t_ok].to_numpy(), t_ok)
    return {'c_index': c, 'auc_180': aucs[0], 'auc_365': aucs[1], 'auc_730': aucs[2], 'ibs': ibs,
            'p_fill_365_mean': float(risk1y.mean())}


# ───────────── 점추정 ─────────────
res = {'design': {'train': '2012-2019 폐업, 관측 종료 2021-12-31', 'valid': '2020-2021 폐업, 관측 종료 2023-12-31',
                  'min_cell_n': MIN_N, 'horizons_days_after_90': H, 'tau': TAU, 'ibs_grid': [int(GRID[0]), int(GRID[-1])],
                  'bootstrap': B},
       'n': {'stage1_train': len(s1tr), 'stage1_train_pos': int(s1tr.y.sum()), 'stage1_valid': len(s1va),
             'stage1_valid_pos': int(s1va.y.sum()), 'stage2_train': len(l_tr), 'stage2_train_events': int(l_tr.ev.sum()),
             'stage2_valid': len(l_va), 'stage2_valid_events': int(l_va.ev.sum()),
             'b1_cells_with_curve': len(b1_curves), 'b2_cells_with_curve': len(b2_curves)},
       'fallback_share_valid': fallback_share, 'checks': checks}
res['stage1'] = {k: s1_metrics(s1va.y.to_numpy(), p) for k, p in s1_pred.items()}
res['stage2'] = {k: s2_metrics(S, y_va, y_tr) for k, S in S2.items()}

# ───────────── 부트스트랩 ─────────────
n1, n2 = len(s1va), len(l_va)
boot1 = {k: [] for k in s1_pred}; boot2 = {k: [] for k in S2}
for b in range(B):
    i1 = rng.integers(0, n1, n1); i2 = rng.integers(0, n2, n2)
    yb1 = s1va.y.to_numpy()[i1]
    for k, p in s1_pred.items():
        boot1[k].append(s1_metrics(yb1, p[i1]))
    yv = y_va[i2]
    for k, S in S2.items():
        try:
            boot2[k].append(s2_metrics(S.iloc[i2].reset_index(drop=True), yv, y_tr))
        except ValueError:
            pass


def ci(rows, key):
    v = np.array([r[key] for r in rows]); return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]


def diff_ci(a, b, key):
    m = min(len(a), len(b)); v = np.array([a[i][key] - b[i][key] for i in range(m)])
    return {'mean': float(v.mean()), 'ci': [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]}


res['stage1_ci'] = {k: {m: ci(v, m) for m in ('auc', 'pr_auc', 'brier', 'log_loss')} for k, v in boot1.items()}
res['stage2_ci'] = {k: {m: ci(v, m) for m in ('c_index', 'auc_365', 'ibs')} for k, v in boot2.items()}
res['stage2_diff'] = {f'{a}-{b}': {m: diff_ci(boot2[a], boot2[b], m) for m in ('c_index', 'ibs')}
                      for a, b in (('B1', 'B0'), ('B2', 'B0'), ('B1', 'B2'))}
res['stage1_diff'] = {f'{a}-{b}': {m: diff_ci(boot1[a], boot1[b], m) for m in ('auc', 'brier')}
                      for a, b in (('B1', 'B0'), ('B2', 'B0'), ('B1', 'B2'))}
res['bootstrap_used'] = {k: len(v) for k, v in boot2.items()}

# ───────────── 보정(1년) ─────────────
cal = {}
for k, S in S2.items():
    p = 1 - S[365].to_numpy()
    q = pd.qcut(p, 10, labels=False, duplicates='drop') if np.ptp(p) > 0 else np.zeros(len(p), int)
    rows = []
    for b_ in np.unique(q):
        m = q == b_
        obs = 1 - km_at(km(l_va.ev.to_numpy()[m], l_va.dur.to_numpy()[m]), np.array([365]))[0]
        rows.append({'bin': int(b_), 'n': int(m.sum()), 'pred': float(p[m].mean()), 'obs_km': float(obs)})
    cal[k] = rows
res['calibration_365'] = cal
cal1 = {}
for k, p in s1_pred.items():
    q = pd.qcut(p, 10, labels=False, duplicates='drop') if np.ptp(p) > 0 else np.zeros(len(p), int)
    cal1[k] = [{'bin': int(b_), 'n': int((q == b_).sum()), 'pred': float(p[q == b_].mean()),
                'obs': float(s1va.y.to_numpy()[q == b_].mean())} for b_ in np.unique(q)]
res['calibration_stage1'] = cal1
# 점검
res['checks']['b0_c_index_is_half'] = abs(res['stage2']['B0']['c_index'] - 0.5) < 1e-9
res['checks']['survival_monotone'] = all(bool((np.diff(S.to_numpy(), axis=1) <= 1e-12).all()) for S in S2.values())
res['checks']['prob_in_range'] = all(bool(((S.to_numpy() >= 0) & (S.to_numpy() <= 1)).all()) for S in S2.values())
json.dump(res, open(os.path.join(VF, 'baseline_valid.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
          default=float)
print(json.dumps({k: res[k] for k in ('n', 'checks', 'fallback_share_valid', 'stage1', 'stage2', 'stage2_diff', 'stage1_diff')},
                 ensure_ascii=False, indent=1, default=float))
