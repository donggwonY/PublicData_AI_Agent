"""E-06 시험 구간(목표 연도 2023–2025) 1회 평가. 계획 docs/e06/test_plan.md (2026-11-15 고정, 열기 전).

검증과 같은 코드를 쓰기 위해 models.py 의 함수 정의 부분(`res = {` 앞까지)을 그대로 읽어 실행하고,
마지막 사건 연도만 2022 → 2025 로 바꾼다. 사전 점검으로 검증 G1 폐업 MAE(2.5035)를 다시 계산해 같을 때만 진행한다.
실행(저장소 루트): C:\\claude_workspace\\e06_env\\Scripts\\python scripts/e06_competition/test_eval.py
"""
import json
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
src = (HERE / 'models.py').read_text(encoding='utf-8')
prefix = src.split('\nres = {')[0]
assert 'LAST_YEAR, FIRST_TARGET = 2022, 2010' in prefix
prefix = prefix.replace('LAST_YEAR, FIRST_TARGET = 2022, 2010', 'LAST_YEAR, FIRST_TARGET = 2025, 2010')
ns = {'__file__': str(HERE / 'models.py'), '__name__': 'e06_models_prefix'}
exec(compile(prefix, 'models.py(함수 정의 부분)', 'exec'), ns)
build, rolling, rolling_lgb, ppf_counts, nb_alpha, mae = (ns[k] for k in
    ('build', 'rolling', 'rolling_lgb', 'ppf_counts', 'nb_alpha', 'mae'))
boot, FOCUS = ns['boot'], ns['FOCUS']

OUT = ROOT / 'docs/e06/results/test.json'
TEST, VALY = [2023, 2024, 2025], [2020, 2021, 2022]
LAM_CLOSE, LGB_CLOSE = 0.3, (7, 400)
units = json.loads((ROOT / 'docs/e06/results/models.json').read_text(encoding='utf-8'))['industry_units']['all']


def cov_nb(y, mu, years, alpha):
    ok = np.zeros(len(y), bool)
    for yr in np.unique(years):
        m = years == yr
        ok[m] = (y[m] >= ppf_counts(0.1, mu[m], alpha[yr])) & (y[m] <= ppf_counts(0.9, mu[m], alpha[yr]))
    return float(ok.mean())


def alpha_roll(P, col, pred):
    """시험 연도 y 마다 목표 연도 2014 … y−1 행의 기준선 잔차로 α 추정."""
    return {y: nb_alpha(P.loc[P.year.between(2014, y - 1) & pred.notna(), col].values,
                        pred[P.year.between(2014, y - 1) & pred.notna()].values) for y in TEST}


def direction(net, pn):
    nz = net != 0
    if nz.sum() == 0: return None
    acc = float(np.mean((pn[nz] > 0) == (net[nz] > 0)))
    maj = float(max(np.mean(net[nz] > 0), np.mean(net[nz] < 0)))
    return {'n': int(nz.sum()), 'acc': round(acc, 3), 'majority': round(maj, 3), 'pass': bool(acc >= 0.65 and acc >= maj + 0.05)}


res = {'plan': 'docs/e06/test_plan.md', 'input_sha256': ns['snapshot_sha256'](ns['SRC'])}

# ── 1층 ─────────────────────────────────────────────────────
T1 = build(['gu'])
pre, _ = rolling(T1, 'closes', VALY, LAM_CLOSE)
v = T1.year.isin(VALY)
pre_mae = round(mae(T1.loc[v, 'closes'], pre[v]), 4)
res['precheck_val_G1_closes_mae'] = pre_mae
assert pre_mae == 2.5035, f'사전 점검 실패: {pre_mae}'
print('사전 점검 통과', pre_mae)

g1c, _ = rolling(T1, 'closes', TEST, LAM_CLOSE)
g2c, _ = rolling_lgb(T1, 'closes', TEST, LGB_CLOSE)
Tt = T1.year.isin(TEST)
bc = {'B1': T1.closes_l1, 'B2': T1.closes_m3, 'B3': T1.closes_m5}
y = T1.loc[Tt, 'closes'].values
by_year = {str(yr): {n: round(mae(T1.loc[T1.year == yr, 'closes'], p[T1.year == yr]), 4)
                     for n, p in {'G1': g1c, 'G2': g2c, **bc}.items()} for yr in TEST}
c1 = all(by_year[str(yr)]['G1'] < min(by_year[str(yr)][b] for b in bc) for yr in TEST)
best_b = min(bc, key=lambda b: mae(y, bc[b][Tt]))
ci = boot(np.abs(y - g1c[Tt].values) - np.abs(y - bc[best_b][Tt].values),
          (T1.loc[Tt, 'year'].astype(str) + '|' + T1.loc[Tt, 'category']).values)
cp = float(np.mean((y >= ppf_counts(0.1, g1c[Tt].values)) & (y <= ppf_counts(0.9, g1c[Tt].values))))
res['tier1_closes'] = {'cells': int(Tt.sum()), 'mae': {n: round(mae(y, p[Tt]), 4) for n, p in {'G1': g1c, 'G2': g2c, **bc}.items()},
                       'by_year': by_year, 'best_baseline': best_b, 'c1_all_years_better': c1,
                       'improvement_vs_best_ci95': ci, 'c2_ci_upper_below_0': ci[1] < 0,
                       'cov80_poisson': round(cp, 3), 'c3_cov_ok': 0.75 <= cp <= 0.85,
                       'pass': bool(c1 and ci[1] < 0 and 0.75 <= cp <= 0.85)}
print('1층 폐업', res['tier1_closes'])

a1 = alpha_roll(T1, 'opens', T1.opens_m3)
T1['c_pred'] = g1c
T1['o_pred'] = T1.opens_m3

# ── 2층 ─────────────────────────────────────────────────────
T2 = build(['gu', 'dong'])
gu = T1[['gu', 'category', 'year', 'opens_m3', 'opens_s5', 'active_prev', 'c_pred']].rename(
    columns={'opens_m3': 'gu_b2', 'opens_s5': 'gu_s5', 'active_prev': 'gu_act', 'c_pred': 'gu_c'})
T2 = T2.merge(gu, on=['gu', 'category', 'year'], how='left')
act_share = np.where(T2.gu_act > 0, T2.active_prev / T2.gu_act, 0.0)
share0 = np.where(T2.gu_s5 > 0, T2.opens_s5 / T2.gu_s5, act_share)
T2['o_pred'] = T2.gu_b2 * share0
T2['c_pred'] = T2.gu_c * share0
a2 = alpha_roll(T2, 'opens', T2.o_pred)
res['alpha'] = {'tier1_opens': {str(k): round(v, 4) for k, v in a1.items()}, 'tier2_opens': {str(k): round(v, 4) for k, v in a2.items()}}


def layer(P, a, mask):
    V = P[mask & P.year.isin(TEST)]
    if len(V) == 0: return None
    yy, mu = V.opens.values, V.o_pred.values
    return {'cells': int(len(V)), 'mean_opens': round(float(yy.mean()), 2), 'mae': round(mae(yy, mu), 4),
            'wape': round(float(np.abs(yy - mu).sum() / max(yy.sum(), 1)), 3),
            'cov80_poisson': round(float(np.mean((yy >= ppf_counts(0.1, mu)) & (yy <= ppf_counts(0.9, mu)))), 3),
            'cov80_negbin': round(cov_nb(yy, mu, V.year.values, a), 3),
            'direction': direction(V.net.values, (V.o_pred - V.c_pred).values)}


res['tier1_opens_B2'] = layer(T1, a1, T1.year > 0)
res['tier2_opens_B4'] = layer(T2, a2, T2.year > 0)
print('1층 개업 B2', res['tier1_opens_B2']); print('2층 개업 B4', res['tier2_opens_B4'])

# ── 업종별 단위 ───────────────────────────────────────────────
per = {}
for cat, u in units.items():
    d = layer(T2, a2, T2.category == cat)
    g = layer(T1, a1, T1.category == cat)
    per[cat] = {'unit': u['unit'], 'test_dong': d, 'test_gu': g}
summ = {}
for scheme in ('all_dong', 'mixed'):
    rows = []
    for c, r in per.items():
        use = 'test_dong' if scheme == 'all_dong' or r['unit'] == '동' else ('test_gu' if r['unit'] == '구' else None)
        if use and r[use] and r['test_dong']:
            rows.append((r['test_dong']['cells'], r[use]))
    w = np.array([x[0] for x in rows], float)
    agg = lambda f: round(float(sum(wi * f(x) for wi, (_, x) in zip(w, rows) if f(x) is not None) /
                                sum(wi for wi, (_, x) in zip(w, rows) if f(x) is not None)), 3)
    summ[scheme] = {'industries': len(rows), 'wape_w': agg(lambda x: x['wape']), 'cov80_negbin_w': agg(lambda x: x['cov80_negbin']),
                    'cov80_poisson_w': agg(lambda x: x['cov80_poisson']),
                    'direction_acc_w': agg(lambda x: x['direction']['acc'] if x['direction'] else None)}
mixed_pass = 0.75 <= summ['mixed']['cov80_negbin_w'] <= 0.85
res['industry_units'] = {'summary_weighted_by_dong_cells': summ, 'mixed_range_pass': bool(mixed_pass),
                         'focus': {c: per[c] for c in FOCUS if c in per}, 'all': per}
print('업종별 단위', summ, '범위 통과', mixed_pass)

# 방향 표시 후보(구 단위)
dirs = {c: per[c]['test_gu']['direction'] for c in ('경양식', '일식')}
res['direction_candidates'] = dirs
print('방향 후보', dirs)
for c in FOCUS:
    r = per.get(c)
    if r:
        x = r['test_dong'] if r['unit'] == '동' else r['test_gu']
        print(' ', c, r['unit'], {k: x[k] for k in ('cells', 'wape', 'cov80_poisson', 'cov80_negbin')}, x['direction'])

# ── 주점 묶음(동) ─────────────────────────────────────────────
PUB = ['호프/통닭', '정종/대포집/소주방', '감성주점']
s_orig = ns['s']
ns['s'] = s_orig.assign(category=s_orig.category.where(~s_orig.category.isin(PUB), '주점'))
G1p, G2p = build(['gu']), build(['gu', 'dong'])
ns['s'] = s_orig
G1p, G2p = G1p[G1p.category == '주점'].copy(), G2p[G2p.category == '주점'].copy()
gp = G1p[['gu', 'year', 'opens_m3', 'opens_s5', 'active_prev']].rename(
    columns={'opens_m3': 'gu_b2', 'opens_s5': 'gu_s5', 'active_prev': 'gu_act'})
G2p = G2p.merge(gp, on=['gu', 'year'], how='left').reset_index(drop=True)
sh = np.where(G2p.gu_s5 > 0, G2p.opens_s5 / G2p.gu_s5, np.where(G2p.gu_act > 0, G2p.active_prev / G2p.gu_act, 0.0))
G2p['o_pred'] = G2p.gu_b2 * sh
G2p['c_pred'] = np.nan
ap = alpha_roll(G2p, 'opens', G2p.o_pred)
pub = layer(G2p, ap, G2p.year > 0)
pub.pop('direction')
pub['pass'] = bool(0.75 <= pub['cov80_negbin'] <= 0.85)
res['pub_group_dong'] = pub
print('주점 묶음', pub)
OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
