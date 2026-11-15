"""E-06 2단계: 층별 모델 후보 비교. 계획 docs/e06/models_plan.md (2026-11-15 고정, 결과 보기 전).

1층 구×세부 업종: 기준선 B1~B3 vs G1 포아송 회귀(L2).
2층 법정동×세부 업종: 기준선 B2·B4 vs H1 계층 보정(부분 풀링) · H2 포아송 회귀.
시점 이동 학습: 목표 연도 y 예측은 목표 연도 ≤ y−1(2년 합계는 ≤ y−2) 행으로만 학습. 변수는 전년 말 기준.
하이퍼파라미터는 개발 구간(2014–2019)에서만 고르고, 검증(2020–2022)은 보고만 한다. 2022년 이후 사건은 쓰지 않는다.
실행(저장소 루트): service/.venv/Scripts/python scripts/e06_competition/models.py
"""
import json, sys, time
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from snapshot_hashes import snapshot_sha256

SRC = ROOT / 'service/data/processed/stores.parquet'
OUT = ROOT / 'docs/e06/results/models.json'
LAST_YEAR, FIRST_TARGET = 2022, 2010
DEV, VAL = list(range(2014, 2020)), [2020, 2021, 2022]
MERGE = {'통닭(치킨)': '호프/통닭', '까페': '커피숍'}
FOCUS = ['한식', '커피숍', '일반미용업', '호프/통닭', '분식', '중국식', '경양식',
         '일식', '제과점영업', '네일아트업', '피부미용업', '편의점']
LAMBDAS = [0.3, 3, 30, 300]
KS = [0, 1, 3, 10, 30, 100]
B = 1000
rng = np.random.default_rng(0)
T0 = time.time()

# ── 데이터 ──────────────────────────────────────────────────
s = pd.read_parquet(SRC)
s = s[s.is_primary & ~s.short_event.astype(bool)].copy()
s['category'] = s.category.replace(MERGE)
s = s[s.dong.notna()].copy()                    # 두 층이 같은 가게 집합을 쓰도록 법정동 없는 기록 제외(1단계와 같음)
s['oy'] = s.ld.dt.year
s['cy'] = np.where(s.closed, s.cd.dt.year, np.nan)
YEARS = list(range(2003, LAST_YEAR + 1))


def build(keys):
    d = s.copy()
    d['key'] = d[keys + ['category']].astype(str).agg('|'.join, axis=1)
    o = d[d.oy.between(YEARS[0], LAST_YEAR)].groupby(['key', 'oy']).size()
    c = d[d.cy.between(YEARS[0], LAST_YEAR)].groupby(['key', 'cy']).size()
    idx = pd.MultiIndex.from_product([d.key.unique(), YEARS], names=['key', 'year'])
    P = pd.DataFrame({'opens': o.reindex(idx, fill_value=0).values,
                      'closes': c.reindex(idx, fill_value=0).values}, index=idx)
    act = {}
    for y in YEARS:
        end = pd.Timestamp(f'{y}-12-31')
        act[y] = d[(d.ld <= end) & (~d.closed | (d.cd > end))].groupby('key').size()
    P['active_end'] = [act[y].get(k, 0) for k, y in P.index]
    P = P.reset_index().sort_values(['key', 'year']).reset_index(drop=True)
    parts = P.key.str.split('|', expand=True)
    for i, k in enumerate(keys):
        P[k] = parts[i]
    P['category'] = parts[len(keys)]
    g = P.groupby('key')
    for col in ('opens', 'closes'):
        for L in (1, 2, 3):
            P[f'{col}_l{L}'] = g[col].shift(L)
        P[f'{col}_m3'] = g[col].transform(lambda x: x.shift(1).rolling(3).mean())
        P[f'{col}_m5'] = g[col].transform(lambda x: x.shift(1).rolling(5).mean())
    P['opens_s5'] = P.opens_m5 * 5
    P['opens_2y'] = P.opens + g.opens.shift(-1)          # y, y+1 합계 (y+1 ≤ 2022 일 때만 값)
    P['active_prev'] = g.active_end.shift(1)
    P['opens_prev3'] = P.opens_m3 * 3
    P['net'] = P.opens - P.closes
    # 대구 같은 업종 추세, 상위 지역 전체 추세: 전년 ÷ 직전 3년 평균(로그)
    D = s.groupby(['category', 'oy']).size().unstack(fill_value=0).reindex(columns=YEARS, fill_value=0)
    tr = np.log((D.shift(1, axis=1) + 1) / (D.shift(2, axis=1).T.rolling(3).mean().T + 1))
    P['daegu_cat_trend'] = tr.stack().reindex(pd.MultiIndex.from_arrays([P.category, P.year])).values
    G = s.groupby(['gu', 'oy']).size().unstack(fill_value=0).reindex(columns=YEARS, fill_value=0)
    trg = np.log((G.shift(1, axis=1) + 1) / (G.shift(2, axis=1).T.rolling(3).mean().T + 1))
    P['gu_trend'] = trg.stack().reindex(pd.MultiIndex.from_arrays([P.gu, P.year])).values
    P = P[P.year.between(FIRST_TARGET, LAST_YEAR)]
    P = P[(P.active_prev >= 1) | (P.opens_prev3 >= 1)].reset_index(drop=True)
    return P


NUM = ['opens_l1', 'opens_l2', 'opens_l3', 'opens_m3', 'opens_m5', 'closes_l1', 'closes_m3', 'active_prev']


def design(P, extra=()):
    X = np.column_stack([np.log1p(P[c].values) for c in NUM] +
                        [P.daegu_cat_trend.fillna(0).values, P.gu_trend.fillna(0).values] +
                        [np.log(P[c].values + 0.1) for c in extra])
    return X


def fit_poisson(X, y, cats, lam, cat_levels):
    """L2 포아송 회귀(IRLS). 숫자 변수는 학습 행 기준 표준화, 업종 고정효과(원핫), 절편은 벌점 없음."""
    mu_, sd_ = X.mean(0), X.std(0) + 1e-9
    Z = np.column_stack([np.ones(len(X)), (X - mu_) / sd_, (cats[:, None] == cat_levels[None, :]).astype(float)])
    pen = np.full(Z.shape[1], lam); pen[0] = 0
    beta = np.zeros(Z.shape[1]); beta[0] = np.log(y.mean() + 1e-6)
    for _ in range(50):
        eta = np.clip(Z @ beta, -20, 8); m = np.exp(eta)
        grad = Z.T @ (y - m) - pen * beta
        H = (Z * m[:, None]).T @ Z + np.diag(pen)
        step = np.linalg.solve(H, grad); beta += step
        if np.max(np.abs(step)) < 1e-7: break
    return lambda Xn, cn: np.exp(np.clip(np.column_stack(
        [np.ones(len(Xn)), (Xn - mu_) / sd_, (cn[:, None] == cat_levels[None, :]).astype(float)]) @ beta, -20, 8))


def nb_alpha(y, m):
    return float(max(0.0, ((y - m) ** 2 - m).sum() / (m ** 2).sum()))


def rolling(P, target, years, lam, extra=(), lag=1):
    """years 각각에 대해 목표 연도 ≤ y−lag 행으로 학습해 y 행을 예측. (예측, 각 시점 α)"""
    out = pd.Series(np.nan, index=P.index); alphas = {}
    cat_levels = np.array(sorted(P.category.unique()), dtype=object)
    X = design(P, extra)
    for y in years:
        tr = (P.year <= y - lag) & P[target].notna() & np.isfinite(X).all(1)
        te = (P.year == y) & np.isfinite(X).all(1)
        f = fit_poisson(X[tr.values], P.loc[tr, target].values.astype(float), P.loc[tr, 'category'].to_numpy(dtype=object), lam, cat_levels)
        out[te] = f(X[te.values], P.loc[te, 'category'].to_numpy(dtype=object))
        alphas[y] = nb_alpha(P.loc[tr, target].values, f(X[tr.values], P.loc[tr, 'category'].to_numpy(dtype=object)))
    return out, alphas


def ppf_counts(q, mu, alpha=0.0):
    """포아송(alpha=0) 또는 음이항 분위수, 벡터."""
    mu = np.maximum(np.asarray(mu, float), 1e-9); k = np.zeros_like(mu)
    if alpha <= 0:
        pmf = np.exp(-mu); ratio = lambda i: mu / i
    else:
        r = 1 / alpha; pmf = (r / (r + mu)) ** r; ratio = lambda i: (i - 1 + r) / i * mu / (r + mu)
    cdf = pmf.copy()
    for i in range(1, 5000):
        need = cdf < q
        if not need.any(): break
        pmf = np.where(need, pmf * ratio(i), pmf); cdf = np.where(need, cdf + pmf, cdf); k = np.where(need, i, k)
    return k


def cover(y, mu, alpha):
    lo, hi = ppf_counts(0.1, mu, alpha), ppf_counts(0.9, mu, alpha)
    return float(np.mean((y >= lo) & (y <= hi)))


def boot(diff, blocks):
    """블록 부트스트랩: 블록별 합·개수로 평균 차이의 95% 구간."""
    df = pd.DataFrame({'d': diff, 'b': blocks}).groupby('b').d.agg(['sum', 'count'])
    S, N = df['sum'].values, df['count'].values
    idx = rng.integers(0, len(S), size=(B, len(S)))
    m = S[idx].sum(1) / N[idx].sum(1)
    return [round(float(np.percentile(m, 2.5)), 4), round(float(np.percentile(m, 97.5)), 4)]


def mae(a, b):
    return float(np.mean(np.abs(a - b)))


def summarize(P, preds, target, alphas, base_names, blocks, val=VAL):
    """검증 연도별 MAE·채택 기준 1·2·3 판정."""
    VAL = val
    V = P[P.year.isin(VAL)]
    y = V[target].values
    res = {'cells': int(len(V)), 'mae': {}, 'by_year': {}}
    for n, p in preds.items():
        res['mae'][n] = round(mae(y, p[V.index]), 4)
    for yr in VAL:
        W = P.year == yr
        res['by_year'][str(yr)] = {n: round(mae(P.loc[W, target], p[W]), 4) for n, p in preds.items()}
    best_base = min(base_names, key=lambda n: res['mae'][n])
    res['best_baseline'] = best_base
    res['models'] = {}
    for n in preds:
        if n in base_names: continue
        c1 = all(res['by_year'][str(yr)][n] < min(res['by_year'][str(yr)][b] for b in base_names) for yr in VAL)
        diff = np.abs(y - preds[n][V.index].values) - np.abs(y - preds[best_base][V.index].values)
        ci = boot(diff, blocks(V))
        cov_p = cover(y, preds[n][V.index].values, 0)
        cov_nb = float(np.mean([cover(P.loc[P.year == yr, target].values, preds[n][P.year == yr].values, alphas[n][yr]) for yr in VAL]))
        res['models'][n] = {'c1_all_years_better': c1, 'improvement_vs_best_ci95': ci, 'c2_ci_upper_below_0': ci[1] < 0,
                            'cov80_poisson': round(cov_p, 3), 'cov80_negbin': round(cov_nb, 3),
                            'alpha_by_year': {str(k): round(v, 4) for k, v in alphas[n].items() if k in VAL},
                            'c3_cov_ok': {'poisson': 0.75 <= cov_p <= 0.85, 'negbin': 0.75 <= cov_nb <= 0.85}}
        res['models'][n]['adopt'] = bool(c1 and ci[1] < 0 and (res['models'][n]['c3_cov_ok']['poisson'] or res['models'][n]['c3_cov_ok']['negbin']))
    return res


def net_eval(P, op, cp, base_net):
    V = P[P.year.isin(VAL)]
    pn = op[V.index] - cp[V.index]
    nz = V.net != 0
    r = {'mae_model': round(mae(V.net, pn), 4), **{f'mae_{k}': round(mae(V.net, v[V.index]), 4) for k, v in base_net.items()},
         'sign_acc_model': round(float(np.mean((pn[nz] > 0) == (V.net[nz] > 0))), 3),
         **{f'sign_acc_{k}': round(float(np.mean((v[V.index][nz] > 0) == (V.net[nz] > 0))), 3) for k, v in base_net.items()},
         'increase_share': round(float(np.mean(V.net[nz] > 0)), 3), 'nonzero_cells': int(nz.sum())}
    by_cat = {}
    for c in FOCUS:
        m = nz & (V.category == c)
        if m.sum() == 0: continue
        acc = float(np.mean((pn[m] > 0) == (V.net[m] > 0)))
        maj = float(max(np.mean(V.net[m] > 0), np.mean(V.net[m] < 0)))
        by_cat[c] = {'n': int(m.sum()), 'sign_acc': round(acc, 3), 'majority': round(maj, 3),
                     'show_direction': bool(acc >= 0.65 and acc >= maj + 0.05)}
    r['focus'] = by_cat
    return r


def pick_lambda(P, target, extra=(), lag=1, years=DEV):
    scores = {}
    for lam in LAMBDAS:
        p, _ = rolling(P, target, years, lam, extra, lag)
        m = P.year.isin(years) & p.notna()
        scores[lam] = mae(P.loc[m, target], p[m])
    return min(scores, key=scores.get), {str(k): round(v, 4) for k, v in scores.items()}


# ── G2 LightGBM (models_plan.md 변경 기록 1) ──────────────────
import lightgbm as lgb
GRID_LGB = [(7, 150), (7, 400), (15, 150), (15, 400)]       # (잎 수, 나무 수)


def rolling_lgb(P, target, years, params, extra=(), lag=1):
    X = pd.DataFrame(design(P, extra), index=P.index).add_prefix('x')
    ok = np.isfinite(X.values).all(1)
    X['cat'] = pd.Categorical(P.category.values, categories=sorted(P.category.unique()))
    out = pd.Series(np.nan, index=P.index); alphas = {}
    leaves, trees = params
    for y in years:
        tr = (P.year <= y - lag) & P[target].notna() & ok
        te = (P.year == y) & ok
        m = lgb.LGBMRegressor(objective='poisson', num_leaves=leaves, n_estimators=trees, learning_rate=0.05,
                              min_child_samples=20, random_state=0, deterministic=True, force_row_wise=True,
                              n_jobs=4, verbose=-1)
        m.fit(X[tr], P.loc[tr, target].astype(float), categorical_feature=['cat'])
        out[te] = m.predict(X[te])
        alphas[y] = nb_alpha(P.loc[tr, target].values, m.predict(X[tr]))
    return out, alphas


def pick_lgb(P, target, extra=(), lag=1, years=DEV):
    scores = {}
    for prm in GRID_LGB:
        p, _ = rolling_lgb(P, target, years, prm, extra, lag)
        m = P.year.isin(years) & p.notna()
        scores[prm] = mae(P.loc[m, target], p[m])
    best = min(scores, key=scores.get)
    return best, {f'{k[0]}x{k[1]}': round(v, 4) for k, v in scores.items()}


res = {'plan': 'docs/e06/models_plan.md', 'input_sha256': snapshot_sha256(SRC), 'tier1': {}, 'tier2': {}}

# ── 1층 ─────────────────────────────────────────────────────
T1 = build(['gu'])
ALL = DEV + VAL
yb1 = lambda V: V.year.astype(str) + '|' + V.category
t1 = {}
for target, lag in (('opens', 1), ('closes', 1), ('opens_2y', 2)):
    lam, sc = pick_lambda(T1, target, lag=lag)
    yrs = [y for y in ALL if y + lag - 1 <= LAST_YEAR]
    g1, al = rolling(T1, target, yrs, lam, lag=lag)
    h = 2 if target == 'opens_2y' else 1
    src = 'opens' if target == 'opens_2y' else target
    base = {'B1': T1[f'{src}_l1'] * h, 'B2': T1[f'{src}_m3'] * h, 'B3': T1[f'{src}_m5'] * h}
    prm, scl = pick_lgb(T1, target, lag=lag)
    g2, alg = rolling_lgb(T1, target, yrs, prm, lag=lag)
    t1[target] = {'G1': g1, 'G2': g2, **base}
    if target == 'opens':
        res_al1 = {'G1': al, 'G2': alg}
    Pv = T1 if target != 'opens_2y' else T1[T1.year <= LAST_YEAR - 1]
    r = summarize(Pv, {k: v.reindex(Pv.index) for k, v in t1[target].items()}, target, {'G1': al, 'G2': alg}, list(base), yb1,
                  val=[2020, 2021] if target == 'opens_2y' else VAL)
    r['lambda'] = lam; r['dev_mae_by_lambda'] = sc
    r['lgb_params'] = f'{prm[0]}x{prm[1]}'; r['dev_mae_by_lgb'] = scl
    res['tier1'][target] = r
    print('tier1', target, r['mae'], r['models'], f'{time.time()-T0:.0f}s')
res['tier1']['net'] = net_eval(T1, t1['opens']['G1'], t1['closes']['G1'],
                               {'B0': T1.opens * 0.0, 'B3': T1.opens_m5 - T1.closes_m5})
print('tier1 net', {k: v for k, v in res['tier1']['net'].items() if k != 'focus'})
res['tier1']['net_G2'] = net_eval(T1, t1['opens']['G2'], t1['closes']['G2'],
                                  {'B0': T1.opens * 0.0, 'B3': T1.opens_m5 - T1.closes_m5})
print('tier1 net_G2', {k: v for k, v in res['tier1']['net_G2'].items() if k != 'focus'})

# 1층 최선(개발 구간 MAE 기준)으로 2층에 넘길 구 예측 선택. 개업·폐업 따로(변경 기록 1)
dev1 = T1.year.isin(DEV)
picks = {}
for target in ('opens', 'closes'):
    cand = {n: t1[target][n] for n in ('G1', 'G2', 'B2')}
    sc_ = {n: mae(T1.loc[dev1, target], p[dev1]) for n, p in cand.items()}
    picks[target] = min(sc_, key=sc_.get)
    res['tier1'].setdefault('pick_for_tier2', {})[target] = {'pick': picks[target], 'dev_mae': {k: round(v, 4) for k, v in sc_.items()}}
tier1_pick = picks['opens']
gu_pred = T1.assign(p=t1['opens'][picks['opens']], pc=t1['closes'][picks['closes']],
                    gu_s5=T1.opens_s5, gu_act=T1.active_prev)[['gu', 'category', 'year', 'p', 'pc', 'gu_s5', 'gu_act']]

# ── 2층 ─────────────────────────────────────────────────────
T2 = build(['gu', 'dong'])
T2 = T2.merge(gu_pred, on=['gu', 'category', 'year'], how='left')
T2['act_share'] = np.where(T2.gu_act > 0, T2.active_prev / T2.gu_act, 0.0)
gu_b2 = T1[['gu', 'category', 'year', 'opens_m3', 'closes_m3']].rename(columns={'opens_m3': 'gu_b2', 'closes_m3': 'gu_c_b2'})
T2 = T2.merge(gu_b2, on=['gu', 'category', 'year'], how='left')
share0 = np.where(T2.gu_s5 > 0, T2.opens_s5 / T2.gu_s5, T2.act_share)
T2['B4'] = T2.gu_b2 * share0


def h1(k, col='p'):
    share = (T2.opens_s5 + k * T2.act_share) / (T2.gu_s5 + k)
    share = np.where((T2.gu_s5 + k) > 0, share, T2.act_share)
    return T2[col] * share


kd = {k: mae(T2.loc[T2.year.isin(DEV) & T2.p.notna(), 'opens'], h1(k)[T2.year.isin(DEV) & T2.p.notna()]) for k in KS}
k_best = min(kd, key=kd.get)
T2['H1'] = h1(k_best)
T2['H1c'] = h1(k_best, 'pc')          # 폐업도 같은 점유율 보정(점유율은 개업 기준)
lam2, sc2 = pick_lambda(T2[T2.year >= 2014].reset_index(drop=True), 'opens', extra=('H1', 'B4'), years=[2016, 2017, 2018, 2019])
T2v = T2[T2.year >= 2014].reset_index(drop=True)
h2, al2 = rolling(T2v, 'opens', [2016, 2017, 2018, 2019] + VAL, lam2, extra=('H1', 'B4'))
lamc, _ = pick_lambda(T2v, 'closes', extra=('H1c',), years=[2016, 2017, 2018, 2019])
h2c, _ = rolling(T2v, 'closes', VAL, lamc, extra=('H1c',))
al_h1 = {}
for y in VAL:
    tr = T2v.year.between(2014, y - 1) & T2v.H1.notna()
    al_h1[y] = nb_alpha(T2v.loc[tr, 'opens'].values, T2v.loc[tr, 'H1'].values)
D2 = [2016, 2017, 2018, 2019]
prm2, scl2 = pick_lgb(T2v, 'opens', extra=('H1', 'B4'), years=D2)
g2o, alg2 = rolling_lgb(T2v, 'opens', D2 + VAL, prm2, extra=('H1', 'B4'))
prm2c, _ = pick_lgb(T2v, 'closes', extra=('H1c',), years=D2)
g2c, _ = rolling_lgb(T2v, 'closes', D2 + VAL, prm2c, extra=('H1c',))
h2c_all, _ = rolling(T2v, 'closes', D2 + VAL, lamc, extra=('H1c',))
preds2 = {'B2': T2v.opens_m3, 'B4': T2v.B4, 'H1': T2v.H1, 'H2': h2, 'G2': g2o}
yb2 = lambda V: V.gu + '|' + V.dong
r2 = summarize(T2v, preds2, 'opens', {'H1': al_h1, 'H2': al2, 'G2': alg2}, ['B2', 'B4'], yb2)
r2['k'] = k_best; r2['dev_mae_by_k'] = {str(k): round(v, 4) for k, v in kd.items()}
r2['lambda_H2'] = lam2; r2['dev_mae_by_lambda_H2'] = sc2
r2['lgb_params'] = f'{prm2[0]}x{prm2[1]}'; r2['dev_mae_by_lgb'] = scl2
res['tier2']['opens'] = r2
print('tier2 opens', r2['mae'], r2['models'])
res['tier2']['net_H2'] = net_eval(T2v, h2, h2c, {'B0': T2v.opens * 0.0, 'B3': T2v.opens_m5 - T2v.closes_m5})
res['tier2']['net_H1'] = net_eval(T2v, T2v.H1, T2v.H1c, {'B0': T2v.opens * 0.0, 'B3': T2v.opens_m5 - T2v.closes_m5})
res['tier2']['net_G2'] = net_eval(T2v, g2o, g2c, {'B0': T2v.opens * 0.0, 'B3': T2v.opens_m5 - T2v.closes_m5})
for n in ('net_H1', 'net_H2', 'net_G2'):
    print('tier2', n, {k: v for k, v in res['tier2'][n].items() if k != 'focus'})

# ── 업종별 예측 단위 (변경 기록 1) ────────────────────────────
# 층마다 최선 모델: 개발 구간 MAE(2층은 2016–2019, 모든 후보가 예측을 가진 연도)
dev2 = T2v.year.isin(D2)
best1 = {t: min(['G1', 'G2', 'B1', 'B2', 'B3'], key=lambda n: mae(T1.loc[dev1, t], t1[t][n][dev1])) for t in ('opens', 'closes')}
c2 = {'B4': T2v.H1c * 0 + T2v.gu_c_b2 * np.where(T2v.gu_s5 > 0, T2v.opens_s5 / T2v.gu_s5, T2v.act_share),
      'H1': T2v.H1c, 'H2': h2c_all, 'G2': g2c}
best2 = {'opens': min(['B4', 'H1', 'H2', 'G2'], key=lambda n: mae(T2v.loc[dev2, 'opens'], preds2[n][dev2])),
         'closes': min(list(c2), key=lambda n: mae(T2v.loc[dev2, 'closes'], c2[n][dev2]))}
# 음이항 α: 층 최선 개업 모델의 시점별 α(기준선이 최선이면 그 층 G1/H1 α를 쓴다). 보고용 추가 항목(선택 규칙과 무관)
alpha1 = {'G1': res_al1['G1'], 'G2': res_al1['G2']}.get(best1['opens'], res_al1['G1'])
alpha2 = {'H1': al_h1, 'H2': al2, 'G2': alg2}.get(best2['opens'], al_h1)
L1 = {'P': T1, 'o': t1['opens'][best1['opens']], 'c': t1['closes'][best1['closes']], 'a': alpha1}
L2 = {'P': T2v, 'o': preds2[best2['opens']], 'c': c2[best2['closes']], 'a': alpha2}


def layer_metrics(L, cat):
    P = L['P']; V = P.year.isin(VAL) & (P.category == cat)
    if V.sum() == 0: return None
    y, mu = P.loc[V, 'opens'].values, L['o'][V].values
    pn = L['o'][V] - L['c'][V]; nz = P.loc[V, 'net'] != 0
    acc = float(np.mean((pn[nz] > 0) == (P.loc[V, 'net'][nz] > 0))) if nz.sum() else None
    maj = float(max(np.mean(P.loc[V, 'net'][nz] > 0), np.mean(P.loc[V, 'net'][nz] < 0))) if nz.sum() else None
    yrs = P.loc[V, 'year'].values
    cnb = float(np.mean(np.concatenate([((y[yrs == yr] >= ppf_counts(0.1, mu[yrs == yr], L['a'][yr])) &
                                         (y[yrs == yr] <= ppf_counts(0.9, mu[yrs == yr], L['a'][yr]))) for yr in VAL if (yrs == yr).any()])))
    return {'cells': int(V.sum()), 'mean_opens': round(float(y.mean()), 2),
            'wape': round(float(np.abs(y - mu).sum() / max(y.sum(), 1)), 3), 'cov80_poisson': round(cover(y, mu, 0), 3),
            'cov80_negbin': round(cnb, 3),
            'net_sign_acc': None if acc is None else round(acc, 3), 'net_majority': None if maj is None else round(maj, 3),
            'net_nonzero': int(nz.sum()),
            'show_direction': bool(acc is not None and acc >= 0.65 and acc >= maj + 0.05)}


units = {}
for cat in sorted(T2v.category.unique()):
    d2 = T2v[(T2v.year.isin(DEV)) & (T2v.category == cat)]
    d1 = T1[(T1.year.isin(DEV)) & (T1.category == cat)]
    m_dong = float(d2.opens.mean()) if len(d2) else 0.0
    cov_dong = cover(d2.opens.values, d2.B4.values, 0) if len(d2) else None
    m_gu = float(d1.opens.mean()) if len(d1) else 0.0
    unit = ('동' if m_dong >= 2 and cov_dong is not None and 0.75 <= cov_dong <= 0.90
            else '구' if m_gu >= 2 else '대구 추세만')
    units[cat] = {'unit': unit, 'dev_mean_opens_dong': round(m_dong, 2), 'dev_cov80_B4_dong': None if cov_dong is None else round(cov_dong, 3),
                  'dev_mean_opens_gu': round(m_gu, 2), 'val_dong': layer_metrics(L2, cat), 'val_gu': layer_metrics(L1, cat)}
cnt = pd.Series({c: u['unit'] for c, u in units.items()}).value_counts().to_dict()
# 창업자 관심 칸 기준 요약: 동 칸 수로 가중(어느 업종이 몇 개 동에 걸치는지)
summ = {}
for scheme in ('all_dong', 'mixed'):
    rows = []
    for c, u in units.items():
        use = 'val_dong' if scheme == 'all_dong' or u['unit'] == '동' else ('val_gu' if u['unit'] == '구' else None)
        if use and u[use]: rows.append((u['val_dong']['cells'] if u['val_dong'] else 0, u[use]))
    w = np.array([r[0] for r in rows], float)
    agg = lambda k: round(float(np.nansum([r[1][k] * wi for wi, r in zip(w, rows) if r[1][k] is not None]) /
                                np.sum([wi for wi, r in zip(w, rows) if r[1][k] is not None])), 3)
    summ[scheme] = {'industries': len(rows), 'cov80_poisson_w': agg('cov80_poisson'), 'cov80_negbin_w': agg('cov80_negbin'),
                    'net_sign_acc_w': agg('net_sign_acc'),
                    'wape_w': agg('wape'), 'show_direction_industries': int(sum(r[1]['show_direction'] for r in rows))}
res['industry_units'] = {'best_models': {'tier1': best1, 'tier2': best2}, 'unit_counts': cnt, 'summary_weighted_by_dong_cells': summ,
                         'focus': {c: units[c] for c in FOCUS if c in units}, 'all': units}
print('units', cnt, summ, best1, best2)
for c in FOCUS:
    u = units.get(c)
    if u: print(c, u['unit'], u['dev_mean_opens_dong'], u['dev_cov80_B4_dong'], u['dev_mean_opens_gu'], '| dong', u['val_dong'], '| gu', u['val_gu'])
res['runtime_s'] = round(time.time() - T0)
OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
